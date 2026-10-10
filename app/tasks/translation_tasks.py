"""Celery worker boundary for project translation tasks."""

from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path
from typing import Awaitable, Callable
from uuid import UUID
from datetime import datetime, timezone

from tortoise import Tortoise, transactions

from ..core.database import TORTOISE_ORM
from ..core.config import app_settings
from ..infrastructure.document.storage import LocalDocumentStorage
from ..infrastructure.spreadsheet.csv_adapter import CsvSpreadsheetAdapter
from ..infrastructure.spreadsheet.contracts import CellAddress, SpreadsheetSpec
from ..infrastructure.spreadsheet.xlsx_adapter import XlsxSpreadsheetAdapter
from ..models import BackgroundJob, Document, TranslationTask, User
from .celery_app import celery_app


TranslationInvoker = Callable[[str, str, str, str, str], Awaitable[str]]


async def _run_translation_task(
    task_id: UUID,
    *,
    worker_id: str,
    invoker: TranslationInvoker | None = None,
    storage: LocalDocumentStorage | None = None,
) -> dict[str, object]:
    task = await TranslationTask.get_or_none(id=task_id)
    if task is None:
        return {"status": "not_found"}
    if task.job_id is not None:
        return await _run_spreadsheet_task(task, worker_id=worker_id, invoker=invoker, storage=storage)
    async with transactions.in_transaction() as connection:
        task = await TranslationTask.filter(id=task_id).using_db(connection).select_for_update().first()
        if task is None:
            return {"status": "not_found"}
        if task.status != "queued":
            return {"status": "not_claimed", "task_status": task.status}
        task.status = "translating"
        task.progress = 1
        await task.save(using_db=connection, update_fields=["status", "progress", "updated_at"])

    # Provider execution is deliberately an explicit boundary. Until a provider
    # adapter is configured, never claim that a task completed successfully.
    async with transactions.in_transaction() as connection:
        task = await TranslationTask.filter(id=task_id).using_db(connection).select_for_update().first()
        if task is None:
            return {"status": "not_found"}
        task.status = "failed"
        task.progress = 1
        task.error_code = "PROVIDER_NOT_CONFIGURED"
        task.error_message = "翻译 provider 尚未配置"
        await task.save(using_db=connection, update_fields=["status", "progress", "error_code", "error_message", "updated_at"])
    return {"status": "failed", "error_code": "PROVIDER_NOT_CONFIGURED"}


async def _run_spreadsheet_task(
    task: TranslationTask,
    *,
    worker_id: str,
    invoker: TranslationInvoker | None,
    storage: LocalDocumentStorage | None,
) -> dict[str, object]:
    job = await BackgroundJob.claim(worker_id, job_type="translation_task", job_id=task.job_id, lease_seconds=900)
    if job is None:
        await task.refresh_from_db()
        return {"status": "not_claimed", "task_status": task.status}
    if invoker is None and app_settings.ai_provider_enabled:
        try:
            invoker = await _configured_invoker(task)
        except Exception:
            invoker = None
    if invoker is None:
        task.status = "failed"
        task.progress = 0
        task.error_code = "PROVIDER_NOT_CONFIGURED"
        task.error_message = "翻译 provider 尚未配置"
        await task.save(update_fields=["status", "progress", "error_code", "error_message", "updated_at"])
        await job.fail(
            "PROVIDER_NOT_CONFIGURED",
            "翻译 provider 尚未配置",
            worker_id=worker_id,
            retry_delay_seconds=0,
            terminal=True,
        )
        return {"status": "failed", "error_code": "PROVIDER_NOT_CONFIGURED"}
    document = await Document.get_or_none(id=await _task_document_id(task))
    if document is None or not document.storage_uri or task.source_column is None or not task.target_columns:
        await task.save(update_fields=["status", "error_code", "error_message", "updated_at"])
        task.status = "failed"
        task.error_code = "TRANSLATION_INPUT_INVALID"
        task.error_message = "翻译任务输入文件或列配置不可用"
        await task.save(update_fields=["status", "error_code", "error_message", "updated_at"])
        await job.fail(
            "TRANSLATION_INPUT_INVALID",
            "翻译任务输入文件或列配置不可用",
            worker_id=worker_id,
            retry_delay_seconds=0,
            terminal=True,
        )
        return {"status": "failed", "error_code": "TRANSLATION_INPUT_INVALID"}
    storage = storage or LocalDocumentStorage(app_settings.document_storage_dir)
    with storage.open(storage_key=document.storage_uri) as stream:
        content = stream.read()
    spec = SpreadsheetSpec(
        source_column=task.source_column,
        target_columns=task.target_columns,
        sheet_names=task.sheet_names,
        overwrite=task.overwrite,
    )
    adapter = CsvSpreadsheetAdapter() if document.file_format == "csv" else XlsxSpreadsheetAdapter()
    cells = adapter.read(content, spec)
    task.status = "translating"
    task.progress = 0
    task.total_cells = len(cells)
    task.completed_cells = 0
    await task.save(update_fields=["status", "progress", "total_cells", "completed_cells", "updated_at"])
    translations: dict[CellAddress, str] = {}
    for index, cell in enumerate(cells, start=1):
        current = await TranslationTask.get_or_none(id=task.id)
        if current is None or current.status == "cancelled":
            await job.cancel(reason="翻译任务已取消")
            return {"status": "cancelled"}
        if cell.target_text and not task.overwrite:
            continue
        try:
            translated = await invoker(cell.source_text, task.source_language, cell.target_language, task.model_type or "", task.model or "")
        except Exception as exc:
            task.status = "failed"
            task.error_code = getattr(exc, "code", "PROVIDER_CALL_FAILED")
            task.error_message = "翻译 provider 调用失败"
            await task.save(update_fields=["status", "error_code", "error_message", "updated_at"])
            await job.fail(
                task.error_code,
                "翻译 provider 调用失败",
                worker_id=worker_id,
                retry_delay_seconds=0,
                terminal=True,
            )
            return {"status": "failed", "error_code": "PROVIDER_CALL_FAILED"}
        translations[cell.address] = translated
        task.completed_cells = index
        task.progress = int(index * 100 / max(1, len(cells)))
        await task.save(update_fields=["completed_cells", "progress", "updated_at"])
    output = adapter.write(content, spec, translations)
    suffix = "csv" if document.file_format == "csv" else "xlsx"
    output_key = f"projects/{task.project_id}/translation-tasks/{task.id}/output.{suffix}"
    size, _ = storage.put(storage_key=output_key, content=output)
    task.status = "review"
    task.progress = 100
    task.output_storage_key = output_key
    task.output_file_name = f"{Path(document.file_name).stem}-translated.{suffix}"
    task.output_size_bytes = size
    from ..models import DocumentSegment

    for segment_no, cell in enumerate(cells, start=1):
        translated = translations.get(cell.address)
        if not translated:
            continue
        segment = await DocumentSegment.filter(document_id=document.id, segment_no=segment_no).first()
        if segment is None:
            segment = await DocumentSegment.create(
                document_id=document.id,
                segment_no=segment_no,
                source_text=cell.source_text,
                target_text=translated,
                source_language=task.source_language,
                target_language=cell.target_language,
                status="translated",
                workflow_state="draft",
            )
        else:
            segment.target_text = translated
            segment.target_language = cell.target_language
            segment.status = "translated"
            segment.workflow_state = "draft"
            segment.version += 1
            segment.translated_at = datetime.now(timezone.utc)
            await segment.save(update_fields=["target_text", "target_language", "status", "workflow_state", "version", "translated_at", "updated_at"])
    task.result = {"status": "review", "translated_cells": len(translations), "segment_workflow": "unchanged"}
    await task.save(update_fields=["status", "progress", "output_storage_key", "output_file_name", "output_size_bytes", "result", "updated_at"])
    await job.complete(worker_id=worker_id, result={"task_id": str(task.id), "status": "review", "translated_cells": len(translations)})
    return {"status": "review", "translated_cells": len(translations)}


async def _task_document_id(task: TranslationTask) -> UUID | None:
    link = await task.files.order_by("created_at").first()
    return link.document_id if link else None


async def _configured_invoker(task: TranslationTask) -> TranslationInvoker | None:
    """Build the allowlisted provider bridge only when explicitly enabled."""
    if task.api_key_id is None or task.created_by_id is None:
        return None
    from ..application.ai_translation.service import AiTranslationService
    from ..application.auth.api_key.service import ApiKeyService
    from ..domain.ai_translation.contracts import TranslationRequest
    from ..infrastructure.ai_provider.registry import default_registry

    user = await User.get_or_none(id=task.created_by_id)
    if user is None:
        return None
    service = AiTranslationService(registry=default_registry(), api_key_service=ApiKeyService())

    async def invoke(text: str, source: str, target: str, model_type: str, model: str) -> str:
        result = await service.translate(
            user,
            task.project_id,
            task.api_key_id,
            TranslationRequest(
                text=text,
                source_language=source,
                target_language=target,
                model_type=model_type,
                model=model,
            ),
        )
        return result.text

    return invoke


def run_translation_task(task_id: UUID) -> dict[str, object]:
    async def runner():
        await Tortoise.init(config=TORTOISE_ORM, _enable_global_fallback=True)
        try:
            return await _run_translation_task(task_id, worker_id=f"translation:{socket.gethostname()}:{os.getpid()}")
        finally:
            await Tortoise.close_connections()

    return asyncio.run(runner())


@celery_app.task(name="translation_tasks.run")
def run_translation_task_job(task_id: str) -> dict[str, object]:
    return run_translation_task(UUID(task_id))


__all__ = ["run_translation_task", "run_translation_task_job"]
