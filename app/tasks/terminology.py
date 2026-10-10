"""Workers for terminology import/export and candidate mining workflows."""

from __future__ import annotations

import asyncio
import base64
import os
import re
import socket
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from tortoise import Tortoise, transactions

from ..core.database import TORTOISE_ORM
from ..models import (
    BackgroundJob,
    DocumentSegment,
    Project,
    TerminologyBase,
    TerminologyTerm,
    TerminologyTermRevision,
    TranslationMemoryEntry,
    TranslationMemoryEntrySource,
    User,
)
from ..application.project.terminology.schemas import TerminologyExportRequest
from ..application.project.terminology.workflows import TerminologyWorkflowService
from .celery_app import celery_app


def _tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[A-Za-z0-9_\-]+|[\u4e00-\u9fff]{2,}", text) if len(token.strip()) >= 2]


async def _extract_candidates(payload: dict[str, Any]) -> dict[str, object]:
    file_ids = [UUID(value) for value in payload.get("file_ids", [])]
    segments = await DocumentSegment.filter(document_id__in=file_ids, deleted_at=None).order_by("document_id", "segment_no")
    occurrences: dict[str, list[DocumentSegment]] = defaultdict(list)
    for segment in segments:
        for token in set(_tokens(segment.source_text)):
            occurrences[token].append(segment)
    min_occurrences = int(payload.get("min_occurrences", 1))
    candidates = []
    for source, rows in sorted(occurrences.items()):
        if len(rows) < min_occurrences:
            continue
        translations = {}
        for row in rows:
            if row.target_text:
                translations[row.target_language] = row.target_text
        candidates.append(
            {
                "source": source,
                "translations": translations,
                "category": "general",
                "confidence": min(1.0, 0.5 + min(0.5, len(rows) / 10)),
                "source_file_id": str(rows[0].document_id),
                "segment_ids": [str(row.id) for row in rows],
            }
        )
    return {"candidates": candidates}


async def _mine_candidates(payload: dict[str, Any]) -> dict[str, object]:
    library_ids = [UUID(value) for value in payload.get("tm_base_ids", [])]
    query = TranslationMemoryEntry.filter(
        library_id__in=library_ids,
        source_language=payload.get("source_language"),
        target_language__in=payload.get("target_languages", []),
        status="active",
        deleted_at=None,
    )
    rows = await query.order_by("source_text")
    grouped: dict[str, list[TranslationMemoryEntry]] = defaultdict(list)
    for row in rows:
        grouped[row.source_text].append(row)
    candidates = []
    min_occurrences = int(payload.get("min_occurrences", 2))
    for source, entries in sorted(grouped.items()):
        if len(entries) < min_occurrences:
            continue
        translations = {entry.target_language: entry.target_text for entry in entries}
        sources = await TranslationMemoryEntrySource.filter(entry_id__in=[entry.id for entry in entries], invalidated_at=None)
        candidates.append(
            {
                "source": source,
                "translations": translations,
                "occurrences": len(entries),
                "category": "general",
                "confidence": min(1.0, 0.5 + min(0.5, len(entries) / 10)),
                "source_segment_ids": [str(source.segment_id) for source in sources if source.segment_id],
            }
        )
    return {"candidates": candidates}


async def _process_large_import(payload: dict[str, Any]) -> dict[str, object]:
    base = await TerminologyBase.get(id=UUID(payload["base_id"]))
    project = await Project.get(id=base.project_id)
    user = await User.get(id=UUID(payload["user_id"]))
    service = TerminologyWorkflowService()
    result = await service._import_rows(user, project, base, payload.get("rows", []), str(payload.get("on_conflict", "update")))
    return result.model_dump(mode="json")


async def _process_large_export(payload: dict[str, Any]) -> dict[str, object]:
    base = await TerminologyBase.get(id=UUID(payload["base_id"]))
    service = TerminologyWorkflowService()
    request = TerminologyExportRequest.model_validate(payload["request"])
    terms = await service._filtered_terms(base, request)
    response = service._serialize_export(base, terms, request)
    return {
        "content_base64": base64.b64encode(response.content).decode("ascii"),
        "filename": response.filename,
        "media_type": response.media_type,
        "count": len(terms),
    }


async def _process_large_clear(payload: dict[str, Any]) -> dict[str, object]:
    base = await TerminologyBase.get(id=UUID(payload["base_id"]))
    actor_id = UUID(payload["user_id"])
    deleted = 0
    async with transactions.in_transaction():
        terms = await TerminologyTerm.filter(base_id=base.id, deleted_at=None)
        for term in terms:
            term.status = "archived"
            term.deleted_at = datetime.now(timezone.utc)
            term.version += 1
            await term.save(update_fields=["status", "deleted_at", "version", "updated_at"])
            await TerminologyTermRevision.create(
                term=term,
                version=term.version,
                snapshot={"source_term": term.source_term, "target_terms": term.target_terms, "status": term.status, "source": term.source},
                changed_by_id=actor_id,
                change_note="异步清空术语库",
            )
            deleted += 1
        if deleted:
            base.version += 1
            await base.save(update_fields=["version", "updated_at"])
    return {"deleted": deleted}


async def process_terminology_job(job_id: UUID, *, worker_id: str | None = None) -> dict[str, object]:
    worker_id = worker_id or f"terminology:{socket.gethostname()}:{os.getpid()}"
    job = await BackgroundJob.claim(worker_id, job_id=job_id, job_type=None, lease_seconds=300)
    if job is None:
        return {"status": "not_claimed"}
    try:
        payload = job.result.get("workflow_payload", {}) if isinstance(job.result, dict) else {}
        if job.type == "terminology_extract":
            result = await _extract_candidates(payload)
        elif job.type == "terminology_mine":
            result = await _mine_candidates(payload)
        elif job.type == "terminology_import":
            result = await _process_large_import(payload)
        elif job.type == "terminology_export":
            result = await _process_large_export(payload)
        elif job.type == "terminology_clear":
            result = await _process_large_clear(payload)
        else:
            raise ValueError("unsupported terminology job")
        await job.complete(worker_id=worker_id, result=result)
        return {"status": "succeeded", **result}
    except Exception as exc:
        await job.fail("TERMINOLOGY_JOB_FAILED", str(exc), worker_id=worker_id, retry_delay_seconds=30)
        return {"status": "retry" if job.attempts < job.max_attempts else "failed"}


@celery_app.task(bind=True, name="terminology.process", max_retries=None)
def process_terminology_job_task(task, job_id: str) -> dict[str, object]:
    async def run() -> dict[str, object]:
        await Tortoise.init(config=TORTOISE_ORM)
        try:
            return await process_terminology_job(UUID(job_id))
        finally:
            await Tortoise.close_connections()

    result = asyncio.run(run())
    if result.get("status") == "retry":
        raise task.retry(countdown=30)
    return result


__all__ = ["process_terminology_job", "process_terminology_job_task"]
