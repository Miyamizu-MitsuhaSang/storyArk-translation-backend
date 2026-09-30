# Translation Memory Persistent Index Design

## Status

Proposed design for the persistent Translation Memory (TM) index worker. This document is the design source for the implementation plan in `docs/superpowers/plans/2026-09-30-translation-memory-persistent-index.md`.

## Goal

Add a restart-safe, version-aware background indexing pipeline for TM libraries while keeping PostgreSQL as the source of truth, Redis as an optional cache only, and exact SQL search available as a safe fallback.

## Current State

- TM libraries and entries are persisted in PostgreSQL through Tortoise ORM.
- Each library has a monotonically increasing `content_version`.
- Exact search uses normalized source hashes and database filtering.
- Celery is configured and already handles large TM imports.
- `TranslationMemoryTaskDispatcher.enqueue_rebuild()` currently raises `RuntimeError` because no persistent index backend exists.
- The bundled `translate-manager-rag` SDK currently exposes in-memory `TopKMipsIndex` and `SparseMipsRetriever` build/search operations, but no stable persistence or loading API.
- Redis is intentionally used only for bounded search-result caching; it is not the source of index truth.

## Decision

Use a hybrid, versioned artifact architecture:

1. PostgreSQL remains the authoritative TM data store and records library versions, jobs, and index artifact metadata.
2. A Celery worker builds a complete immutable index snapshot for one `library_id` and one `content_version`.
3. The first artifact store is a configurable local filesystem directory for development and single-host deployments. The storage interface must allow an S3-compatible implementation later without changing application services.
4. The RAG SDK receives a versioned persistence envelope containing its serialized index, vectorizer metadata, document-to-entry mapping, and checksum. The SDK must provide explicit save/load behavior; backend code must not depend on private native object internals.
5. An artifact becomes searchable only after checksum verification and an atomic database publication step. A worker finishing an old content version must never replace a newer active artifact.
6. Exact TM queries continue to use SQL. Fuzzy or semantic queries use the artifact only when a compatible active artifact exists; otherwise they return the documented `503 INDEX_NOT_AVAILABLE` response rather than silently returning stale semantic results.

## Data Model

### Background jobs

Introduce a minimal reusable `BackgroundJob` model for TM indexing and future document/terminology jobs:

- `id`: UUID primary key.
- `type`: stable job type such as `tm_index_rebuild`.
- `status`: `queued`, `running`, `succeeded`, `failed`, or `cancelled`.
- `resource_type` and `resource_id`: the logical resource, initially `translation_memory_library` and its UUID.
- `requested_version`: the library `content_version` captured when the job is submitted.
- `attempts`, `max_attempts`, `available_at`, `started_at`, `finished_at`.
- `worker_id` and `lease_expires_at` for reclaiming crashed workers.
- `result`: JSON result metadata with artifact ID and row count; no secrets.
- `error_code` and `error_message` with bounded, redacted failure details.
- `created_at` and `updated_at`.

The model is deliberately generic, but this feature owns only the TM index job behavior. Other job types can reuse the model later.

### TM index artifacts

Add a `TranslationMemoryIndexArtifact` model:

- `id`: UUID.
- `library_id`: foreign key to the TM library.
- `content_version`: immutable source version used for the build.
- `status`: `building`, `ready`, `active`, `superseded`, or `failed`.
- `storage_uri`: opaque artifact-store location; never construct paths from untrusted request text.
- `checksum`: SHA-256 of the complete artifact envelope.
- `format_version`: artifact schema version.
- `vectorizer_version`: deterministic vectorizer version.
- `row_count` and `feature_count`.
- `build_job_id`, `built_at`, `activated_at`, and `failure_reason`.

Enforce uniqueness on `(library_id, content_version, format_version)` and ensure at most one active artifact per library. Publication must be a transaction that demotes the previous active artifact and activates the new artifact only when the library still has the requested `content_version`.

## Worker Data Flow

1. `POST /projects/{project_id}/translation-memories/reindex` verifies project membership and determines the effective libraries.
2. For each library, read the current `content_version` and create or reuse a `BackgroundJob` with `(type, resource_id, requested_version)` idempotency.
3. The dispatcher submits the job ID to Celery and returns `202` with the job references. If broker or artifact storage is unavailable, return `503 INDEX_NOT_AVAILABLE` and do not create a false success record.
4. The worker claims the job with a short lease. A second worker cannot process the same active lease.
5. The worker reads a consistent snapshot of active, non-deleted TM entries for the requested version, creates deterministic sparse vectors, and builds the SDK index plus entry metadata mapping.
6. The worker writes the envelope to a temporary artifact, fsyncs/flushes it, computes the checksum, and atomically renames it into its final content-addressed location.
7. In a database transaction, verify the library version is still `requested_version`. If it changed, mark the job `superseded` and enqueue the newer version; do not publish the stale artifact.
8. If the version is unchanged, mark the artifact `ready`, update the library's active artifact pointer, mark the job `succeeded`, and mark the old artifact `superseded`.
9. On failure, record a redacted error, increment attempts, and retry with bounded exponential backoff. After the retry limit, mark the job `failed` and leave the previous active artifact intact.

## Search Behavior

- Permission and effective-library filtering always happen before artifact access.
- `match_mode=exact` continues to use the database path and remains available without a worker or artifact.
- Future `fuzzy` and `semantic` modes require an active artifact whose library and `content_version` match the database version.
- An artifact with a lower version is stale and cannot be used for semantic results.
- An absent, corrupt, incompatible, or unavailable artifact returns `503 INDEX_NOT_AVAILABLE` for modes that require it.
- Redis cache keys continue to include user, project, query filters, library IDs, and content versions. Artifact publication invalidates affected cache entries.

## SDK Contract

Extend `translate-manager-rag` with public, versioned persistence APIs rather than serializing pybind objects from the backend:

- `TopKMipsIndex.serialize() -> bytes` and `TopKMipsIndex.deserialize(payload: bytes) -> TopKMipsIndex`.
- `SparseMipsRetriever.serialize() -> bytes` and `SparseMipsRetriever.deserialize(payload: bytes) -> SparseMipsRetriever`.
- The envelope records `sdk_version`, `format_version`, `feature_count`, row count, and document metadata.
- Loading validates magic bytes, format version, dimensions, and checksum before exposing the index for search.
- Existing in-memory `build/search/clear` behavior remains backward compatible.

The backend owns the text-to-sparse-vector adapter and its versioned vocabulary/tokenization metadata. A vectorizer change creates a new `vectorizer_version` and requires a rebuild; it cannot reinterpret an old artifact.

## Storage Evolution

### Phase 1: Local artifact store

Use `TM_INDEX_STORAGE_DIR` with per-library, per-version, content-addressed files. This supports local development and one worker host. The filesystem implementation must use temporary files, atomic rename, checksum verification, bounded artifact size, and safe cleanup.

### Phase 2: Shared object storage

Implement the same store protocol for S3-compatible storage. Workers upload to a temporary key, verify the remote checksum, then publish database metadata. API workers load artifacts through a bounded local cache.

### Phase 3: Scale and retention

Keep the active artifact and a configurable number of previous artifacts, delete only superseded artifacts that have no running job reference, and add per-library or per-language sharding when the data volume requires it.

## API and Operations

- Keep `POST /projects/{project_id}/translation-memories/reindex` as `202` with job references.
- Add or reuse `GET /jobs/{job_id}` to expose status, attempts, requested version, artifact result, and redacted error details.
- Add an internal health/readiness check for database, Celery broker, artifact store, and SDK loadability; do not equate process health with index readiness.
- Log job ID, library ID, requested version, active version, duration, row count, artifact checksum, and failure code. Never log source text, API keys, or raw metadata.
- Expose metrics for queue latency, build duration, stale-build discard count, retries, artifact load failures, cache hit rate, and SQL fallback count.

## Failure and Recovery Rules

- Worker crash: lease expiry allows a later worker to reclaim the job.
- Broker outage: reject submission with `503`; retain no misleading queued-success response.
- Storage outage: fail/retry the job; preserve the last active artifact.
- Database version changed during build: discard publication and enqueue the newer version.
- Corrupt artifact: quarantine it, mark the artifact failed, and use SQL exact fallback where supported.
- Deployment rollback: old application versions can continue using SQL exact search; artifact format versions prevent incompatible loads.

## Security and Privacy

- Scope and project membership are checked before reading artifact metadata or results.
- Artifact paths and object keys are generated from UUIDs and hashes, never user-provided names.
- Artifact envelopes contain only TM text, language metadata, vectorizer data, and entry IDs required for retrieval; no API keys or prompt/completion payloads.
- Enforce maximum entry count, text size, artifact size, and worker memory limits.
- Redact exception messages before persisting or returning them.

## Verification Strategy

- Unit tests for serialization round trips, checksum rejection, vectorizer determinism, lease handling, stale-version protection, retry policy, and atomic publication.
- Integration tests with SQLite/PostgreSQL-compatible schema for job/artifact transitions and version races.
- Celery eager-mode tests for successful build, retry, failure, and requeue behavior.
- API tests for `202`, `503`, job status, permission isolation, and exact fallback.
- SDK tests remain in the SDK repository and must pass before backend integration is enabled.
- Operational smoke tests cover worker startup, artifact-store permissions, database migration, and restart recovery.

## Non-Goals

- Do not use Redis as the authoritative index store.
- Do not replace PostgreSQL TM data with artifact files.
- Do not enable semantic search before a compatible vectorizer and persisted SDK load path exist.
- Do not implement document parsing, terminology mining, or unrelated generic jobs in the first worker release.
