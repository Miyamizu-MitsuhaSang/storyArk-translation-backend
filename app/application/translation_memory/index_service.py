"""Build, persist, validate, and conditionally publish TM search indexes."""

from __future__ import annotations

import base64
import hashlib
import json
from time import perf_counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID

from translate_manager_rag import SparseMipsRetriever
from tortoise import transactions

from ...core.config import app_settings
from ...infrastructure.translation_memory.artifact_store import (
    IndexArtifactStore,
    LocalIndexArtifactStore,
)
from ...infrastructure.translation_memory.index_format import TranslationMemoryIndexFormat
from ...infrastructure.translation_memory.sentence_processing import TranslationMemoryVectorizer, language_family
from ...models import (
    BackgroundJob,
    TranslationMemoryEntry,
    TranslationMemoryIndexArtifact,
    TranslationMemoryLibrary,
)

INDEX_FORMAT_VERSION = 1
VECTORIZER_VERSION = "tfidf-cosine-v1"


@dataclass
class _LanguagePartition:
    vectorizer: TranslationMemoryVectorizer
    retriever: SparseMipsRetriever


@dataclass
class TranslationMemoryIndex:
    partitions: dict[tuple[str, str], _LanguagePartition]
    row_count: int

    @property
    def feature_count(self) -> int:
        return sum(part.vectorizer.num_features for part in self.partitions.values())


class TranslationMemoryIndexBackend:
    """SDK-backed sparse indexes isolated by exact source/target language pair."""

    def __init__(self, *, vectorizer_version: str = VECTORIZER_VERSION) -> None:
        self.vectorizer_version = vectorizer_version

    @staticmethod
    def _language_tag(language: str) -> str:
        tag = language.strip().replace("_", "-").lower()
        language_family(tag)
        return tag

    def build(self, entries: Iterable[TranslationMemoryEntry]) -> TranslationMemoryIndex:
        grouped: dict[tuple[str, str], list[TranslationMemoryEntry]] = {}
        for entry in entries:
            pair = (self._language_tag(entry.source_language), self._language_tag(entry.target_language))
            grouped.setdefault(pair, []).append(entry)

        partitions: dict[tuple[str, str], _LanguagePartition] = {}
        row_count = 0
        for pair, rows in grouped.items():
            vectorizer = TranslationMemoryVectorizer(version=self.vectorizer_version)
            vectorizer.fit((row.source_text, pair[0]) for row in rows)
            documents: list[dict[str, Any]] = []
            vectors = []
            for row in rows:
                documents.append({
                    "entry_id": str(row.id),
                    "source_language": row.source_language,
                    "target_language": row.target_language,
                    "source_text": row.source_text,
                    "target_text": row.target_text,
                    "updated_at": row.updated_at.isoformat(),
                    "metadata": row.metadata or {},
                })
                vectors.append(vectorizer.encode(row.source_text, pair[0]))
            retriever = SparseMipsRetriever(candidate_threshold=0.0)
            retriever.build(documents=documents, vectors=vectors, num_features=vectorizer.num_features)
            partitions[pair] = _LanguagePartition(vectorizer, retriever)
            row_count += len(rows)
        return TranslationMemoryIndex(partitions, row_count)

    def serialize(self, index: TranslationMemoryIndex) -> bytes:
        partitions = []
        for (source_language, target_language), partition in sorted(index.partitions.items()):
            payload = TranslationMemoryIndexFormat.serialize(partition.vectorizer, partition.retriever)
            partitions.append({
                "source_language": source_language,
                "target_language": target_language,
                "payload": base64.b64encode(payload).decode("ascii"),
            })
        value = {
            "format_version": INDEX_FORMAT_VERSION,
            "vectorizer_version": self.vectorizer_version,
            "row_count": index.row_count,
            "partitions": partitions,
        }
        return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def deserialize(self, payload: bytes) -> TranslationMemoryIndex:
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid TM index envelope") from exc
        if not isinstance(value, dict) or value.get("format_version") != INDEX_FORMAT_VERSION:
            raise ValueError("unsupported TM index format version")
        if value.get("vectorizer_version") != self.vectorizer_version:
            raise ValueError("incompatible vectorizer version")
        rows = value.get("row_count")
        records = value.get("partitions")
        if type(rows) is not int or rows < 0 or not isinstance(records, list):
            raise ValueError("invalid TM index dimensions")
        partitions: dict[tuple[str, str], _LanguagePartition] = {}
        actual_rows = 0
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("invalid language partition")
            source_language = record.get("source_language")
            target_language = record.get("target_language")
            encoded = record.get("payload")
            pair = (source_language, target_language)
            if (
                not isinstance(source_language, str)
                or not isinstance(target_language, str)
                or self._language_tag(source_language) != source_language
                or self._language_tag(target_language) != target_language
                or pair in partitions
                or not isinstance(encoded, str)
            ):
                raise ValueError("invalid language partition metadata")
            try:
                partition_payload = base64.b64decode(encoded, validate=True)
            except (ValueError, base64.binascii.Error) as exc:
                raise ValueError("invalid language partition payload") from exc
            vectorizer, retriever = TranslationMemoryIndexFormat.deserialize(
                partition_payload,
                expected_vectorizer_version=self.vectorizer_version,
            )
            actual_rows += retriever.row_count
            partitions[pair] = _LanguagePartition(vectorizer, retriever)
        if actual_rows != rows:
            raise ValueError("TM index row count does not match partitions")
        return TranslationMemoryIndex(partitions, rows)

    def search(
        self,
        index: TranslationMemoryIndex,
        source_text: str,
        source_language: str,
        target_language: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        pair = (self._language_tag(source_language), self._language_tag(target_language))
        partition = index.partitions.get(pair)
        if partition is None:
            return []
        return partition.retriever.search(partition.vectorizer.encode(source_text, pair[0]), top_k=top_k)


class TranslationMemoryIndexService:
    def __init__(
        self,
        *,
        store: IndexArtifactStore | None = None,
        backend: TranslationMemoryIndexBackend | None = None,
    ) -> None:
        self.store = store or LocalIndexArtifactStore(
            app_settings.tm_index_storage_dir,
            max_artifact_bytes=app_settings.tm_index_max_artifact_bytes,
        )
        self.backend = backend or TranslationMemoryIndexBackend()

    async def enqueue_rebuild(self, library_id: UUID, content_version: int):
        from ...tasks.translation_memory import TranslationMemoryTaskDispatcher

        return await TranslationMemoryTaskDispatcher().enqueue_rebuild(library_id, content_version)

    async def build_job(self, job_id: UUID, *, worker_id: str) -> dict[str, Any]:
        from ...tasks.translation_memory_maintenance import increment_metric, observe_duration_ms

        started_at = perf_counter()
        job = await BackgroundJob.get(id=job_id)
        observe_duration_ms(
            "tm_index_queue_latency_ms",
            max(0.0, (datetime.now(timezone.utc) - job.created_at).total_seconds() * 1000),
        )
        if job.type != "tm_index_rebuild" or job.resource_type != "translation_memory_library":
            raise ValueError("job is not a TM index rebuild")
        job._assert_lease_owner(worker_id, datetime.now(timezone.utc))
        async with transactions.in_transaction() as connection:
            library = await TranslationMemoryLibrary.filter(id=job.resource_id).using_db(connection).select_for_update().first()
            rows = []
            if library is not None and library.content_version == job.requested_version:
                rows = await TranslationMemoryEntry.filter(
                    library_id=library.id,
                    status="active",
                    deleted_at=None,
                ).using_db(connection).order_by("source_language", "target_language", "id")
        if library is None or library.content_version != job.requested_version:
            await job.complete(worker_id=worker_id, result={"status": "superseded"})
            return {"status": "superseded"}

        artifact, _ = await TranslationMemoryIndexArtifact.get_or_create(
            library_id=library.id,
            content_version=job.requested_version,
            format_version=INDEX_FORMAT_VERSION,
            defaults={
                "status": "building",
                "vectorizer_version": self.backend.vectorizer_version,
                "build_job_id": job.id,
            },
        )
        if artifact.status == "active":
            await job.complete(worker_id=worker_id, result={"status": "active", "artifact_id": str(artifact.id)})
            return {"status": "active", "artifact_id": str(artifact.id)}
        if artifact.status in {"failed", "superseded"}:
            artifact.status = "building"
            artifact.failure_reason = None
            artifact.build_job_id = job.id
            await artifact.save(update_fields=["status", "failure_reason", "build_job_id"])

        index = self.backend.build(rows)
        payload = self.backend.serialize(index)
        checksum = hashlib.sha256(payload).hexdigest()
        storage_uri, stored_checksum = self.store.put_atomic(payload)
        if checksum != stored_checksum:
            raise ValueError("stored index checksum does not match serialized payload")

        artifact.status = "ready"
        artifact.storage_uri = storage_uri
        artifact.checksum = checksum
        artifact.vectorizer_version = self.backend.vectorizer_version
        artifact.row_count = index.row_count
        artifact.feature_count = index.feature_count
        artifact.built_at = datetime.now(timezone.utc)
        await artifact.save(update_fields=[
            "status", "storage_uri", "checksum", "vectorizer_version", "row_count", "feature_count", "built_at",
        ])
        published = await self.publish_if_current(artifact)
        if published:
            result = {"status": "active", "artifact_id": str(artifact.id), "row_count": index.row_count}
        else:
            increment_metric("tm_index_stale_builds_discarded_total")
            result = {"status": "superseded", "artifact_id": str(artifact.id), "row_count": index.row_count}
        await job.complete(worker_id=worker_id, result=result)
        observe_duration_ms("tm_index_build_duration_ms", (perf_counter() - started_at) * 1000)
        increment_metric("tm_index_builds_total")
        return result

    async def publish_if_current(self, artifact: TranslationMemoryIndexArtifact) -> bool:
        return await artifact.activate_if_current()

    async def load_active(self, library_id: UUID) -> TranslationMemoryIndex:
        from ...tasks.translation_memory_maintenance import increment_metric

        def unavailable(message: str) -> ValueError:
            increment_metric("tm_index_load_failures_total")
            return ValueError(message)

        artifact = await TranslationMemoryIndexArtifact.filter(
            library_id=library_id,
            status="active",
        ).first()
        library = await TranslationMemoryLibrary.filter(id=library_id).first()
        if (
            artifact is None
            or library is None
            or artifact.content_version != library.content_version
            or artifact.storage_uri is None
            or artifact.checksum is None
            or artifact.vectorizer_version != self.backend.vectorizer_version
        ):
            raise unavailable("active TM index is unavailable or incompatible")
        if not self.store.exists(artifact.storage_uri):
            raise unavailable("active TM index artifact is missing")
        actual_checksum = self.store.checksum(artifact.storage_uri)
        if actual_checksum != artifact.checksum:
            raise unavailable("active TM index checksum mismatch")
        with self.store.open(artifact.storage_uri) as stored:
            payload = stored.read(app_settings.tm_index_max_artifact_bytes + 1)
        if len(payload) > app_settings.tm_index_max_artifact_bytes:
            raise unavailable("active TM index exceeds configured size limit")
        index = self.backend.deserialize(payload)
        if index.row_count != artifact.row_count or index.feature_count != artifact.feature_count:
            raise unavailable("active TM index metadata mismatch")
        return index
