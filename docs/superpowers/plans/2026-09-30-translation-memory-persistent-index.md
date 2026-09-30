# Translation Memory Persistent Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a restart-safe, version-aware TM index worker backed by persisted SDK artifacts, while preserving PostgreSQL as the source of truth and exact SQL fallback.

**Architecture:** Add a generic job record and TM artifact metadata in PostgreSQL, build immutable versioned artifacts through a Celery worker, store them behind a local-filesystem/object-storage interface, and publish them atomically only when the source `content_version` still matches. Extend the RAG SDK with public serialization APIs and use a backend-owned deterministic sparse vectorizer; semantic/fuzzy search becomes available only for a compatible active artifact.

**Tech Stack:** Python 3.13, FastAPI, Tortoise ORM, Aerich, PostgreSQL, Celery/Redis, pytest, `translate-manager-rag`, local filesystem storage first, S3-compatible storage later.

**Spec:** `docs/superpowers/specs/2026-09-30-translation-memory-persistent-index-design.md`

## Global Constraints

- PostgreSQL TM rows and `content_version` remain the source of truth.
- Redis is an optional result cache, never the authoritative index store.
- Exact search remains available through SQL without a worker or artifact.
- A stale worker must never publish an artifact over a newer library version.
- All persisted errors and logs must be redacted and bounded.
- Artifact paths use generated UUID/hash components only.
- Every implementation task starts with a failing test and ends with a focused passing test.
- Do not modify unrelated auth, project, terminology, or frontend changes already present in the worktree.
- After each task's focused test passes, commit only that task's listed files; do not include unrelated worktree changes.

## Test Harness Conventions

All backend tests in this plan reuse a module-scoped async SQLite fixture that initializes `translation_backend.app.models`, generates schemas, and closes Tortoise connections in teardown. The shared fixture module defines `make_user()`, `make_project_with_owner()`, `make_library(content_version=1)`, `make_artifact(library, content_version)`, and `service_with_local_store(tmp_path)`. Tests that need a service use the returned `TranslationMemoryIndexService`; tests that need publication query `TranslationMemoryIndexArtifact.filter(...).first()` directly. SDK tests use only public SDK constructors and bytes returned by `serialize()`.

The same fixture module provides `bump_library_version(library_id, version)`, `build_and_publish_fixture_artifact()`, and `make_search_service()`. `StaleIndexVersionError`, `IndexResourceLimitError`, and `TranslationMemoryIndexUnavailableError` are typed exceptions produced by the tasks where they first appear; later tests import them from their defining module.

---

## Phase 0: Lock the contracts and migration boundary

### Task 0: Freeze the design contracts

**Files:**
- Read: `docs/superpowers/specs/2026-09-30-translation-memory-persistent-index-design.md`
- Modify: `docs/api.md` only if the final job-status or artifact-status response differs from the existing contract.
- Test: `tests/test_translation_memory_api.py`

**Interfaces:**
- Produces the stable names used by later tasks: `BackgroundJob`, `TranslationMemoryIndexArtifact`, `IndexArtifactStore`, `TranslationMemoryIndexBackend`, and `TranslationMemoryIndexService`.

- [ ] **Step 1: Write the failing contract test**

```python
def test_tm_reindex_contract_exposes_job_status_and_requested_version():
    operation = app.openapi()["paths"][
        "/api/v1/projects/{project_id}/translation-memories/reindex"
    ]["post"]
    assert "202" in operation["responses"]
    assert "requested_version" in str(operation["responses"]["202"])
```

- [ ] **Step 2: Run the test and confirm the response contract is incomplete**

Run: `uv run pytest tests/test_translation_memory_api.py::test_tm_reindex_contract_exposes_job_status_and_requested_version -q`

Expected: FAIL because the current response only exposes the existing minimal job reference.

- [ ] **Step 3: Record the exact response shape in the design/API contract**

Use a response containing `job_id`, `status`, `requested_version`, and a stable `type` value of `tm_index_rebuild`. Do not implement the handler in this task.

- [ ] **Step 4: Run the focused test again**

Run: `uv run pytest tests/test_translation_memory_api.py::test_tm_reindex_contract_exposes_job_status_and_requested_version -q`

Expected: PASS after the contract fixture/schema is updated.

## Phase 1: Persistence substrate and job lifecycle

### Task 1: Add the reusable background job model

**Files:**
- Create: `app/models/jobs.py`
- Modify: `app/models/__init__.py`
- Create: `migrations/models/7_20260930190000_add_background_jobs.py`
- Test: `tests/test_translation_memory_jobs.py`

**Interfaces:**
- Produces `BackgroundJob.claim()`, `BackgroundJob.complete()`, `BackgroundJob.fail()`, and lease fields used by the worker.

- [ ] **Step 1: Write the failing state-transition tests**

```python
async def test_job_claim_is_single_owner():
    job = await BackgroundJob.create(type="tm_index_rebuild", status="queued")
    first = await job.claim(worker_id="worker-a")
    second = await (await BackgroundJob.get(id=job.id)).claim(worker_id="worker-b")
    assert first is True
    assert second is False
```

- [ ] **Step 2: Run the test to verify the model/helper is missing**

Run: `uv run pytest tests/test_translation_memory_jobs.py::test_job_claim_is_single_owner -q`

Expected: FAIL with the missing model or claim helper.

- [ ] **Step 3: Implement the model and migration**

Use a transaction with `select_for_update`, status filtering, lease expiry checks, `attempts`, `max_attempts`, `requested_version`, and bounded failure fields. Add an index on `(status, available_at)` and `(resource_type, resource_id, requested_version)`.

- [ ] **Step 4: Run the lifecycle tests**

Run: `uv run pytest tests/test_translation_memory_jobs.py -q`

Expected: PASS for queued-to-running, lease expiry reclaim, success, failure, and retry-limit transitions.

### Task 2: Add TM index artifact metadata

**Files:**
- Modify: `app/models/translation_memory.py`
- Modify: `app/models/__init__.py`
- Create: `migrations/models/8_20260930191000_add_tm_index_artifacts.py`
- Test: `tests/test_translation_memory_artifacts.py`

**Interfaces:**
- Produces `TranslationMemoryIndexArtifact` with immutable `(library_id, content_version, format_version)` identity and one active artifact per library.

- [ ] **Step 1: Write the failing publication test**

```python
async def test_publish_artifact_rejects_stale_library_version():
    library = await make_library(content_version=4)
    artifact = await make_artifact(library, content_version=3)
    with pytest.raises(StaleIndexVersionError):
        await TranslationMemoryIndexService().publish_if_current(artifact.id)
```

- [ ] **Step 2: Run the test and verify stale publication is not protected**

Run: `uv run pytest tests/test_translation_memory_artifacts.py::test_publish_artifact_rejects_stale_library_version -q`

Expected: FAIL because no artifact state model/publication transaction exists.

- [ ] **Step 3: Implement metadata, constraints, and publication transaction**

Add statuses, checksum, storage URI, SDK/vectorizer/format versions, row and feature counts, job linkage, timestamps, and failure reason. Publish only when the library row is locked and its current version equals the artifact version.

- [ ] **Step 4: Run artifact tests**

Run: `uv run pytest tests/test_translation_memory_artifacts.py -q`

Expected: PASS for uniqueness, active replacement, stale rejection, and superseding the old artifact.

## Phase 2: SDK persistence and deterministic vectorization

### Task 3: Add public SDK serialization APIs

**Files:**
- Modify: `../../packages/translate-manager-rag/translate_manager_rag/native.py`
- Modify: `../../packages/translate-manager-rag/translate_manager_rag/retriever.py`
- Modify: `../../packages/translate-manager-rag/translate_manager_rag/__init__.py`
- Test: `../../packages/translate-manager-rag/tests/test_persistence.py`

**Interfaces:**
- Produces `TopKMipsIndex.serialize()`, `TopKMipsIndex.deserialize(payload)`, `SparseMipsRetriever.serialize()`, and `SparseMipsRetriever.deserialize(payload)`.

- [ ] **Step 1: Write the failing round-trip test**

```python
def test_sparse_mips_index_round_trips_through_bytes():
    index = TopKMipsIndex()
    index.build([[(0, 1.0)], [(1, 1.0)]], num_features=2)
    restored = TopKMipsIndex.deserialize(index.serialize())
    assert restored.search([(0, 1.0)], top_k=1) == [(0, 1.0)]
```

- [ ] **Step 2: Run the test and confirm persistence is absent**

Run: `uv run --project ../../packages/translate-manager-rag pytest ../../packages/translate-manager-rag/tests/test_persistence.py -q`

Expected: FAIL because the public methods do not exist.

- [ ] **Step 3: Implement a versioned, validated serialization envelope**

Serialize only public index state, include magic bytes and format version, reject malformed payloads, validate feature dimensions, and preserve existing in-memory build/search behavior. Do not pickle native objects.

- [ ] **Step 4: Run all SDK tests**

Run: `uv run --project ../../packages/translate-manager-rag pytest -q`

Expected: PASS for existing native/retriever tests and the new persistence tests.

### Task 4: Implement the backend vectorizer contract

**Files:**
- Create: `app/infrastructure/translation_memory/vectorizer.py`
- Create: `app/infrastructure/translation_memory/index_format.py`
- Test: `tests/test_translation_memory_vectorizer.py`

**Interfaces:**
- Produces `TranslationMemoryVectorizer(version: str)`, `fit(entries)`, `encode(text)`, and an envelope containing vocabulary/tokenization metadata.

- [ ] **Step 1: Write the failing determinism and version tests**

```python
def test_vectorizer_is_deterministic_and_versioned():
    vectorizer = TranslationMemoryVectorizer(version="word-ngram-v1")
    vectorizer.fit(["Hello world", "World gate"])
    first = vectorizer.encode("Hello world")
    second = vectorizer.encode("Hello world")
    assert first == second
    assert vectorizer.version == "word-ngram-v1"
```

- [ ] **Step 2: Run the test and verify the adapter is missing**

Run: `uv run pytest tests/test_translation_memory_vectorizer.py -q`

Expected: FAIL because no deterministic vectorizer exists.

- [ ] **Step 3: Implement bounded normalization, vocabulary metadata, and stable sparse vectors**

Use the same normalization for build and query, cap token/vocabulary sizes, record the vectorizer version, and reject an artifact when its version is unsupported.

- [ ] **Step 4: Run vectorizer tests**

Run: `uv run pytest tests/test_translation_memory_vectorizer.py -q`

Expected: PASS for determinism, multilingual text, size limits, and incompatible-version rejection.

## Phase 3: Artifact storage and worker

### Task 5: Add the artifact-store abstraction

**Files:**
- Create: `app/infrastructure/translation_memory/artifact_store.py`
- Modify: `app/core/config.py`
- Test: `tests/test_translation_memory_artifact_store.py`

**Interfaces:**
- Produces `IndexArtifactStore.put_atomic()`, `open()`, `delete()`, `exists()`, and `checksum()`.
- Produces `LocalIndexArtifactStore(root: Path)` and settings `tm_index_storage_dir`, `tm_index_max_artifact_bytes`, and `tm_index_retention_count`.

- [ ] **Step 1: Write the failing atomic-write and traversal tests**

```python
def test_local_store_writes_content_addressed_artifact_atomically(tmp_path):
    store = LocalIndexArtifactStore(tmp_path)
    location = store.put_atomic("library-id", 4, b"artifact")
    assert store.open(location) == b"artifact"
    assert ".." not in location
```

- [ ] **Step 2: Run the test and verify the storage interface is missing**

Run: `uv run pytest tests/test_translation_memory_artifact_store.py -q`

Expected: FAIL because no store exists.

- [ ] **Step 3: Implement temporary-file writes, fsync/flush, atomic rename, checksum validation, size limits, and safe generated locations**

No request parameter may become a path component. Storage failures must raise a typed error for the worker to retry.

- [ ] **Step 4: Run storage tests**

Run: `uv run pytest tests/test_translation_memory_artifact_store.py -q`

Expected: PASS for atomic writes, checksum mismatch, size limits, missing files, and path safety.

### Task 6: Implement versioned TM index build and publication

**Files:**
- Create: `app/application/translation_memory/index_service.py`
- Modify: `app/infrastructure/translation_memory/search_index.py`
- Modify: `app/application/translation_memory/service.py`
- Test: `tests/test_translation_memory_index_service.py`

**Interfaces:**
- Produces `TranslationMemoryIndexBackend.build(entries, vectorizer)`, `serialize()`, `deserialize(payload)`, and `search(query, top_k)` as the application-facing protocol over the SDK.
- Produces `TranslationMemoryIndexService.enqueue_rebuild(library_id, requested_version)`, `build_job(job_id, worker_id)`, `load_active(library_id)`, and `publish_if_current(artifact_id)`.

- [ ] **Step 1: Write the failing stale-build test**

```python
async def test_worker_does_not_publish_when_library_version_changes_during_build():
    library = await make_library(content_version=4)
    job = await TranslationMemoryIndexService().enqueue_rebuild(library.id, requested_version=4)
    await bump_library_version(library.id, 5)
    await TranslationMemoryIndexService().build_job(job.id, worker_id="worker-a")
    assert await TranslationMemoryIndexArtifact.filter(library_id=library.id, status="active").exists() is False
    assert (await BackgroundJob.get(id=job.id)).status == "superseded"
```

- [ ] **Step 2: Run the test and confirm the worker is missing**

Run: `uv run pytest tests/test_translation_memory_index_service.py::test_worker_does_not_publish_when_library_version_changes_during_build -q`

Expected: FAIL because no build service exists.

- [ ] **Step 3: Implement snapshot, vectorization, SDK build, envelope creation, store write, and guarded publication**

Read only active non-deleted entries, preserve entry IDs/language metadata, calculate checksum before publication, and keep the previous active artifact on any failure.

- [ ] **Step 4: Run the index-service tests**

Run: `uv run pytest tests/test_translation_memory_index_service.py -q`

Expected: PASS for successful build, stale version, duplicate job, checksum failure, and active-artifact replacement.

### Task 7: Wire Celery task claiming, retry, and recovery

**Files:**
- Modify: `app/tasks/translation_memory.py`
- Modify: `app/tasks/celery_app.py`
- Modify: `app/application/translation_memory/service.py`
- Test: `tests/test_translation_memory_worker.py`

**Interfaces:**
- Produces `rebuild_translation_memory_index_task(job_id)`, `TranslationMemoryTaskDispatcher.enqueue_rebuild(library_id, content_version)`, and `reclaim_expired_index_jobs()`.

- [ ] **Step 1: Write the failing retry and lease tests**

```python
def test_index_task_retries_transient_storage_failure(monkeypatch):
    result = run_eager_index_task_with_storage_failure(monkeypatch)
    assert result.status == "queued"
    assert result.retry_count == 1
```

- [ ] **Step 2: Run the test and confirm the placeholder task fails**

Run: `uv run pytest tests/test_translation_memory_worker.py -q`

Expected: FAIL because the current task raises `RuntimeError` and has no job lifecycle.

- [ ] **Step 3: Implement idempotent dispatch and bounded retries**

Use a deterministic Celery task ID derived from the job ID, claim leases transactionally, retry transient broker/storage failures with exponential backoff, mark permanent failures, and ensure repeated delivery is harmless.

- [ ] **Step 4: Run worker tests**

Run: `uv run pytest tests/test_translation_memory_worker.py -q`

Expected: PASS for eager success, retry, duplicate delivery, lease reclaim, stale build, and terminal failure.

## Phase 4: API integration and exact fallback

### Task 8: Expose job status and wire reindex responses

**Files:**
- Modify: `app/api/modules/project/project_content/translation_memory/routes.py`
- Create or modify: `app/api/modules/jobs/routes.py`
- Modify: `app/api/router.py`
- Modify: `app/application/translation_memory/schemas.py`
- Test: `tests/test_translation_memory_http.py`

**Interfaces:**
- Produces `POST /api/v1/projects/{project_id}/translation-memories/reindex` with `202` job references.
- Produces `GET /api/v1/jobs/{job_id}` with status, requested version, attempts, and redacted result/error.

- [ ] **Step 1: Write the failing HTTP tests**

```python
def test_reindex_returns_503_when_broker_or_store_unavailable(client):
    response = client.post("/api/v1/projects/project-id/translation-memories/reindex")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INDEX_NOT_AVAILABLE"
```

- [ ] **Step 2: Run the HTTP tests and verify the current route cannot expose job state**

Run: `uv run pytest tests/test_translation_memory_http.py -q`

Expected: FAIL because the current route has no persisted job status endpoint and no typed availability handling.

- [ ] **Step 3: Implement typed response schemas, permission checks, 202/503 behavior, and job status redaction**

Do not expose storage URIs, filesystem paths, source text dumps, or raw exception messages. Keep exact search available even when semantic artifacts are unavailable.

- [ ] **Step 4: Run HTTP tests**

Run: `uv run pytest tests/test_translation_memory_http.py -q`

Expected: PASS for member access, hidden projects, 202 queued responses, 503 failures, job status, and exact fallback.

### Task 9: Load active artifacts for future fuzzy/semantic modes

**Files:**
- Modify: `app/application/translation_memory/service.py`
- Modify: `app/infrastructure/translation_memory/search_index.py`
- Modify: `app/application/translation_memory/schemas.py`
- Test: `tests/test_translation_memory_search_modes.py`

**Interfaces:**
- Produces `match_mode="fuzzy"` and `match_mode="semantic"` only when the request schema enables them and a compatible active artifact exists.

- [ ] **Step 1: Write the failing mode tests**

```python
async def test_semantic_search_rejects_missing_active_artifact():
    request = TranslationMemorySearchRequest(
        source_text="Hello", source_language="en", target_language="zh", match_mode="semantic"
    )
    with pytest.raises(TranslationMemoryIndexUnavailableError):
        await service.search(user, project.id, request)
```

- [ ] **Step 2: Run the tests and confirm only exact mode exists**

Run: `uv run pytest tests/test_translation_memory_search_modes.py -q`

Expected: FAIL because the request schema and service only support exact search.

- [ ] **Step 3: Implement artifact compatibility checks before SDK loading**

Filter effective libraries and language pairs first, load only active artifacts with matching content/vectorizer/format versions, map row IDs back to TM responses, and return `503` for unavailable semantic search.

- [ ] **Step 4: Run search-mode tests**

Run: `uv run pytest tests/test_translation_memory_search_modes.py -q`

Expected: PASS for exact SQL, semantic success, stale artifact rejection, permission isolation, and Redis fallback.

## Phase 5: Retention, observability, and deployment

### Task 10: Add artifact cleanup and operational metrics

**Files:**
- Create: `app/tasks/translation_memory_maintenance.py`
- Modify: `app/tasks/__init__.py`
- Modify: `app/core/config.py`
- Modify: `README.md`
- Test: `tests/test_translation_memory_maintenance.py`

**Interfaces:**
- Produces `cleanup_superseded_artifacts()` and metrics/log fields for queue latency, build duration, retries, stale discards, artifact failures, and SQL fallback.

- [ ] **Step 1: Write the failing retention test**

```python
async def test_cleanup_keeps_active_and_running_referenced_artifacts():
    await create_artifacts_for_library(active=5, superseded=[1, 2, 3, 4])
    await cleanup_superseded_artifacts(retention_count=2)
    assert await artifact_exists(version=5)
    assert await artifact_exists(version=4)
    assert not await artifact_exists(version=1)
```

- [ ] **Step 2: Run the test and verify cleanup is absent**

Run: `uv run pytest tests/test_translation_memory_maintenance.py -q`

Expected: FAIL because no retention task exists.

- [ ] **Step 3: Implement retention, metrics, and documented settings**

Never delete active, building, or job-referenced artifacts. Add worker startup and readiness documentation, `TM_INDEX_STORAGE_DIR`, retry limits, retention count, and artifact size limits.

- [ ] **Step 4: Run maintenance tests**

Run: `uv run pytest tests/test_translation_memory_maintenance.py -q`

Expected: PASS for retention, restart recovery, and metric emission.

### Task 11: Add deployment and restart smoke tests

**Files:**
- Modify: `README.md`
- Modify: `docker-compose.yml` if present in the parent checkout
- Create: `tests/test_translation_memory_restart.py`
- Test fixture: `tests/fixtures/tm_index_artifact/`

**Interfaces:**
- Produces a documented worker process command and a repeatable restart/recovery test.

- [ ] **Step 1: Write the failing restart test**

```python
async def test_restart_loads_active_artifact_without_rebuild():
    artifact = await build_and_publish_fixture_artifact()
    restarted = make_search_service()
    assert await restarted.load_active(artifact.library_id)
```

- [ ] **Step 2: Run the test and verify active artifacts are not loadable after process restart**

Run: `uv run pytest tests/test_translation_memory_restart.py -q`

Expected: FAIL because the current SDK index is process-local.

- [ ] **Step 3: Implement startup validation and worker documentation**

Validate database connectivity, artifact-store readability, SDK format compatibility, and Celery broker connectivity separately. Keep API process startup independent from optional semantic-index readiness.

- [ ] **Step 4: Run restart and full tests**

Run: `uv run pytest -q`

Expected: PASS with the existing TM/auth/project tests plus all persistent-index tests.

## Phase 6: Shared object storage and scale-out

### Task 12: Add an S3-compatible artifact store

**Files:**
- Create: `app/infrastructure/translation_memory/object_store.py`
- Modify: `app/application/translation_memory/index_service.py`
- Modify: `app/core/config.py`
- Test: `tests/test_translation_memory_object_store.py`

**Interfaces:**
- Produces `S3IndexArtifactStore` implementing the same `IndexArtifactStore` protocol as local storage.

- [ ] **Step 1: Write the failing object-store contract test**

```python
def test_s3_store_matches_local_store_protocol(fake_s3):
    store = S3IndexArtifactStore(fake_s3, bucket="tm-index")
    location = store.put_atomic("library-id", 4, b"artifact")
    assert store.open(location) == b"artifact"
```

- [ ] **Step 2: Run the test and confirm only local storage exists**

Run: `uv run pytest tests/test_translation_memory_object_store.py -q`

Expected: FAIL because the object-store implementation is absent.

- [ ] **Step 3: Implement upload, checksum verification, bounded local read cache, and cleanup**

Do not change job publication semantics; only replace the artifact storage implementation through dependency injection.

- [ ] **Step 4: Run object-store tests**

Run: `uv run pytest tests/test_translation_memory_object_store.py -q`

Expected: PASS for upload/download, checksum failure, transient retry, and protocol parity.

### Task 13: Add scale safeguards

**Files:**
- Modify: `app/infrastructure/translation_memory/vectorizer.py`
- Modify: `app/application/translation_memory/index_service.py`
- Modify: `app/tasks/translation_memory_maintenance.py`
- Test: `tests/test_translation_memory_scale_limits.py`

**Interfaces:**
- Produces bounded batching, memory limits, per-library concurrency, language-pair partitioning hooks, and backpressure metrics.

- [ ] **Step 1: Write the failing limit tests**

```python
def test_index_build_rejects_artifact_over_memory_budget():
    with pytest.raises(IndexResourceLimitError):
        build_fixture_with_entries(count=10_000_000)
```

- [ ] **Step 2: Run the tests and verify no resource guard exists**

Run: `uv run pytest tests/test_translation_memory_scale_limits.py -q`

Expected: FAIL because the worker has no explicit resource budget.

- [ ] **Step 3: Implement limits and bounded batching**

Fail before exhausting worker memory, record a typed error, and preserve the previous active artifact. Add partitioning only behind explicit configuration; do not silently change result ordering.

- [ ] **Step 4: Run scale tests**

Run: `uv run pytest tests/test_translation_memory_scale_limits.py -q`

Expected: PASS for limits, backpressure, and deterministic partitioning.

## Final verification gate

- [ ] Run SDK tests: `uv run --project ../../packages/translate-manager-rag pytest -q`.
- [ ] Run backend tests: `uv run pytest -q`.
- [ ] Run compile check: `uv run python -m compileall -q app main.py`.
- [ ] Run formatting/diff check: `git diff --check`.
- [ ] Apply Aerich migrations against a disposable PostgreSQL database.
- [ ] Start API and one Celery worker, submit a rebuild, kill/restart the worker, and verify lease recovery.
- [ ] Mutate the library during a build and verify stale publication is rejected.
- [ ] Verify exact search works with no artifact and semantic search returns `503` until a compatible artifact is active.
- [ ] Verify artifact files contain no secrets and logs contain no raw source text or credentials.
- [ ] Verify the final API documentation matches the generated OpenAPI paths and response descriptions.
