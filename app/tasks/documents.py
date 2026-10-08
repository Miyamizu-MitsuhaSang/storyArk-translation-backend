"""Celery workers for document import, parsing, export and purge jobs."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import socket
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from tortoise import Tortoise, transactions

from ..application.project.document.service import DOCUMENT_JOB_TYPES
from ..core.config import app_settings
from ..core.database import TORTOISE_ORM
from ..infrastructure.document.storage import LocalDocumentStorage
from ..models import BackgroundJob, Document, DocumentSegment
from .celery_app import celery_app


def _local_storage() -> LocalDocumentStorage:
    return LocalDocumentStorage(app_settings.document_storage_dir)


def _parse_text(payload: bytes, file_format: str) -> list[tuple[str, str | None]]:
    text = payload.decode("utf-8-sig")
    if file_format == "txt":
        return [(line.strip(), None) for line in text.splitlines() if line.strip()]
    if file_format == "csv":
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            return []
        header = [item.strip().casefold() for item in rows[0]]
        has_header = "source" in header or "source_text" in header
        data = rows[1:] if has_header else rows
        source_index = header.index("source") if "source" in header else header.index("source_text") if "source_text" in header else 0
        target_index = header.index("target") if "target" in header else header.index("target_text") if "target_text" in header else 1
        return [
            (row[source_index].strip(), row[target_index].strip() or None if len(row) > target_index else None)
            for row in data
            if len(row) > source_index and row[source_index].strip()
        ]
    if file_format == "json":
        value = json.loads(text)
        rows = value.get("segments", []) if isinstance(value, dict) else value
        result: list[tuple[str, str | None]] = []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, str) and row.strip():
                result.append((row.strip(), None))
            elif isinstance(row, dict):
                source = row.get("source", row.get("source_text"))
                target = row.get("target", row.get("target_text"))
                if isinstance(source, str) and source.strip():
                    result.append((source.strip(), target.strip() if isinstance(target, str) and target.strip() else None))
        return result
    if file_format == "xliff":
        root = ET.fromstring(text)
        result = []
        for unit in root.findall(".//{*}trans-unit"):
            source = unit.findtext("./{*}source")
            target = unit.findtext("./{*}target")
            if source and source.strip():
                result.append((source.strip(), target.strip() if target and target.strip() else None))
        return result
    if file_format == "po":
        pairs: list[tuple[str, str | None]] = []
        current_source: str | None = None
        for line in text.splitlines():
            if line.startswith("msgid "):
                current_source = _po_string(line[6:])
            elif line.startswith("msgstr ") and current_source:
                target = _po_string(line[7:])
                if current_source:
                    pairs.append((current_source, target or None))
                current_source = None
        return pairs
    raise ValueError("unsupported document format")


def _po_string(value: str) -> str:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value.strip().strip('"')


async def _run_document_job(job_id: UUID) -> dict[str, object]:
    worker_id = f"document:{socket.gethostname()}:{os.getpid()}"
    job = await BackgroundJob.claim(worker_id, job_type=None, job_id=job_id, lease_seconds=300)
    if job is None:
        return {"status": "not_claimed"}
    document = await Document.get_or_none(id=job.resource_id)
    if document is None:
        await job.fail("DOCUMENT_NOT_FOUND", "文档不存在", worker_id=worker_id)
        return {"status": "failed"}
    try:
        if job.type == DOCUMENT_JOB_TYPES["purge"] and document.purge_after:
            now = datetime.now(timezone.utc)
            if document.purge_after > now:
                job.status = "queued"
                job.available_at = document.purge_after
                job.worker_id = None
                job.lease_expires_at = None
                await job.save(update_fields=["status", "available_at", "worker_id", "lease_expires_at", "updated_at"])
                return {"status": "deferred", "available_at": document.purge_after.isoformat()}
        if job.type in {DOCUMENT_JOB_TYPES["import"], DOCUMENT_JOB_TYPES["parse"]}:
            result = await _process_parse_job(document, job)
        elif job.type == DOCUMENT_JOB_TYPES["export"]:
            result = await _process_export_job(document, job)
        elif job.type == DOCUMENT_JOB_TYPES["purge"]:
            result = await _process_purge_job(document, job)
        else:
            raise ValueError("unsupported document job")
        await job.complete(worker_id=worker_id, result=result)
        return result
    except Exception as exc:
        await job.fail("DOCUMENT_JOB_FAILED", str(exc), worker_id=worker_id, retry_delay_seconds=30)
        return {"status": "retry" if job.attempts < job.max_attempts else "failed"}


async def cleanup_due_documents(*, now: datetime | None = None) -> dict[str, int]:
    """Purge due soft-deleted documents while respecting active job references."""
    now = now or datetime.now(timezone.utc)
    due_documents = await Document.filter(
        status="deletion_pending",
        purge_after__not_isnull=True,
        purge_after__lte=now,
    ).order_by("purge_after", "created_at")
    summary = {"scanned": len(due_documents), "purged": 0, "skipped": 0, "failed": 0}
    for document in due_documents:
        active_processing = await BackgroundJob.filter(
            resource_type="document",
            resource_id=document.id,
            type__in=[DOCUMENT_JOB_TYPES["import"], DOCUMENT_JOB_TYPES["parse"], DOCUMENT_JOB_TYPES["export"]],
            status__in=["queued", "running"],
        ).exists()
        if active_processing:
            summary["skipped"] += 1
            continue
        purge_job = await BackgroundJob.filter(
            resource_type="document",
            resource_id=document.id,
            type=DOCUMENT_JOB_TYPES["purge"],
        ).order_by("-created_at").first()
        if purge_job is None:
            purge_job = await BackgroundJob.create(
                type=DOCUMENT_JOB_TYPES["purge"],
                status="queued",
                resource_type="document",
                resource_id=document.id,
                requested_version=document.version,
            )
        elif purge_job.status in {"failed", "cancelled"}:
            # Keep terminal failures observable; do not bypass max_attempts.
            summary["failed"] += 1
            continue
        elif purge_job.status == "succeeded":
            # A successful purge should already have transitioned the record.
            if document.status == "purged":
                continue
            summary["failed"] += 1
            continue
        result = await _run_document_job(purge_job.id)
        if result.get("status") == "purged":
            summary["purged"] += 1
        elif result.get("status") in {"not_claimed", "deferred"}:
            summary["skipped"] += 1
        else:
            summary["failed"] += 1
    return summary


async def _process_parse_job(document: Document, job: BackgroundJob) -> dict[str, object]:
    if not document.storage_uri:
        raise ValueError("document storage is unavailable")
    with _local_storage().open(storage_key=document.storage_uri) as stream:
        payload = stream.read()
    rows = _parse_text(payload, document.file_format)
    previous = {}
    if job.type == DOCUMENT_JOB_TYPES["parse"] and isinstance(job.result, dict) and job.result.get("preserve_translations"):
        previous = {
            row.segment_no: row.target_text
            for row in await DocumentSegment.filter(document_id=document.id).all()
            if row.target_text
        }
    async with transactions.in_transaction():
        await DocumentSegment.filter(document_id=document.id).delete()
        await DocumentSegment.bulk_create(
            [
                DocumentSegment(
                    document=document,
                    segment_no=index,
                    source_text=source,
                    target_text=previous.get(index, target),
                    source_language=document.source_language,
                    target_language=document.target_language,
                    status="translated" if previous.get(index, target) else "untranslated",
                )
                for index, (source, target) in enumerate(rows, start=1)
            ]
        )
        document.status = "ready"
        document.segment_count = len(rows)
        document.translated_segment_count = sum(1 for index, (_, target) in enumerate(rows, start=1) if previous.get(index, target))
        document.error_count = 0
        document.import_errors = []
        document.parsed_at = datetime.now(timezone.utc)
        await document.save(update_fields=["status", "segment_count", "translated_segment_count", "error_count", "import_errors", "parsed_at", "updated_at"])
    return {"status": "ready", "segment_count": len(rows)}


async def _process_export_job(document: Document, job: BackgroundJob) -> dict[str, object]:
    if not document.storage_uri or document.status in {"deletion_pending", "purged"}:
        raise ValueError("document is not exportable")
    options = job.result if isinstance(job.result, dict) else {}
    export_format = str(options.get("format", "txt"))
    rows = await DocumentSegment.filter(document_id=document.id, deleted_at=None).order_by("segment_no")
    if not options.get("include_untranslated"):
        rows = [row for row in rows if row.target_text]
    if export_format == "json":
        payload = json.dumps([{"source": row.source_text, "target": row.target_text} for row in rows], ensure_ascii=False).encode()
    elif export_format == "csv":
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["source", "target"])
        writer.writerows((row.source_text, row.target_text or "") for row in rows)
        payload = stream.getvalue().encode()
    else:
        payload = "\n".join((row.target_text or row.source_text) for row in rows).encode()
    key = f"projects/{document.project_id}/documents/{document.id}/exports/{job.id}.{export_format}"
    _local_storage().put(storage_key=key, content=payload)
    return {"status": "succeeded", "format": export_format, "storage_key": key, "size_bytes": len(payload)}


async def _process_purge_job(document: Document, job: BackgroundJob) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    if document.purge_after and document.purge_after > now:
        raise ValueError("document purge grace period has not elapsed")
    if document.storage_uri:
        _local_storage().delete(storage_key=document.storage_uri)
    document.status = "purged"
    document.purged_at = now
    await document.save(update_fields=["status", "purged_at", "updated_at"])
    return {"status": "purged"}


@celery_app.task(name="documents.process")
def process_document_job_task(job_id: str) -> dict[str, object]:
    async def run() -> dict[str, object]:
        await Tortoise.init(config=TORTOISE_ORM)
        try:
            return await _run_document_job(UUID(job_id))
        finally:
            await Tortoise.close_connections()

    return asyncio.run(run())


@celery_app.task(name="documents.cleanup_due")
def cleanup_due_documents_task() -> dict[str, int]:
    async def run() -> dict[str, int]:
        await Tortoise.init(config=TORTOISE_ORM)
        try:
            return await cleanup_due_documents()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(run())


__all__ = ["cleanup_due_documents", "cleanup_due_documents_task", "process_document_job_task"]
