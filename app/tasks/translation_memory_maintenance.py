"""Maintenance jobs and lightweight metrics for persistent TM indexes."""

from __future__ import annotations

import logging
import asyncio
from collections import Counter

from ..core.config import app_settings
from ..infrastructure.translation_memory.artifact_store import IndexArtifactStore, LocalIndexArtifactStore
from ..models import BackgroundJob, TranslationMemoryIndexArtifact
from .celery_app import celery_app
from ..core.database import TORTOISE_ORM

logger = logging.getLogger("translation_backend.translation_memory.maintenance")
_METRICS: Counter[str] = Counter()


def increment_metric(name: str, value: int = 1) -> None:
    if value < 0:
        raise ValueError("metric increments must be non-negative")
    _METRICS[name] += value


def observe_duration_ms(name: str, duration_ms: float) -> None:
    if duration_ms < 0:
        raise ValueError("metric durations must be non-negative")
    increment_metric(f"{name}_count")
    increment_metric(f"{name}_total_ms", int(duration_ms))


def snapshot_metrics() -> dict[str, int]:
    return dict(_METRICS)


def reset_metrics() -> None:
    _METRICS.clear()


async def cleanup_superseded_artifacts(
    *,
    store: IndexArtifactStore | None = None,
    retention_count: int | None = None,
) -> int:
    """Delete only unreferenced historical artifacts beyond the retention budget."""
    if retention_count is None:
        retention_count = app_settings.tm_index_retention_count
    if retention_count < 1:
        raise ValueError("retention_count must be positive")
    artifact_store = store or LocalIndexArtifactStore(
        app_settings.tm_index_storage_dir,
        max_artifact_bytes=app_settings.tm_index_max_artifact_bytes,
    )

    deleted = 0
    library_ids = await TranslationMemoryIndexArtifact.all().distinct().values_list("library_id", flat=True)
    for library_id in library_ids:
        artifacts = await TranslationMemoryIndexArtifact.filter(library_id=library_id).order_by("-built_at", "-created_at")
        protected: set[str] = {"active", "building", "ready"}
        candidates = []
        historical_seen = 0
        for artifact in artifacts:
            if artifact.status in protected:
                continue
            referenced = False
            if artifact.build_job_id is not None:
                job = await BackgroundJob.filter(id=artifact.build_job_id).first()
                referenced = job is not None and job.status in {"queued", "running"}
            if referenced:
                continue
            if artifact.status not in {"superseded", "failed"}:
                continue
            if historical_seen < retention_count:
                historical_seen += 1
                continue
            candidates.append(artifact)

        for artifact in candidates:
            if artifact.storage_uri:
                try:
                    artifact_store.delete(artifact.storage_uri)
                except (OSError, ValueError):
                    logger.warning("tm_index_artifact_delete_failed artifact_id=%s", artifact.id)
                    continue
            await artifact.delete()
            deleted += 1

    if deleted:
        increment_metric("tm_index_artifacts_deleted_total", deleted)
    logger.info("tm_index_cleanup deleted=%d retention_count=%d", deleted, retention_count)
    return deleted


@celery_app.task(name="translation_memory.cleanup_superseded_artifacts")
def cleanup_superseded_artifacts_task() -> int:
    from tortoise import Tortoise

    async def run() -> int:
        await Tortoise.init(config=TORTOISE_ORM)
        try:
            return await cleanup_superseded_artifacts()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(run())
