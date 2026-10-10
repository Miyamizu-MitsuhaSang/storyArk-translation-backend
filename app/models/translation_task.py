"""Project translation task persistence models."""

from typing import Any
from uuid import UUID

from tortoise import fields

from .base import TimestampedModel

TRANSLATION_TASK_STATUSES = ("queued", "translating", "review", "completed", "failed", "cancelled")


class TranslationTask(TimestampedModel):
    project = fields.ForeignKeyField("models.Project", related_name="translation_tasks", on_delete=fields.CASCADE)
    created_by = fields.ForeignKeyField("models.User", related_name="translation_tasks", null=True, on_delete=fields.SET_NULL)
    name = fields.CharField(max_length=160)
    source_language = fields.CharField(max_length=16)
    target_languages: list[str] = fields.JSONField(default=list)
    version_id: UUID | None = fields.UUIDField(null=True, description="ProjectVersion UUID snapshot.")
    api_key_id: UUID | None = fields.UUIDField(null=True, description="User-owned API key UUID snapshot.")
    api_key_provider: str | None = fields.CharField(max_length=32, null=True)
    api_key_label: str | None = fields.CharField(max_length=120, null=True)
    api_key_masked: str | None = fields.CharField(max_length=128, null=True)
    model_type: str | None = fields.CharField(max_length=64, null=True)
    model: str | None = fields.CharField(max_length=128, null=True)
    source_column: str | None = fields.CharField(max_length=128, null=True)
    target_columns: list[dict[str, str]] = fields.JSONField(default=list)
    sheet_names: list[str] | None = fields.JSONField(null=True)
    overwrite = fields.BooleanField(default=False)
    job_id: UUID | None = fields.UUIDField(null=True, description="BackgroundJob UUID snapshot.")
    output_storage_key: str | None = fields.CharField(max_length=1024, null=True)
    output_file_name: str | None = fields.CharField(max_length=255, null=True)
    output_size_bytes: int | None = fields.BigIntField(null=True)
    completed_cells = fields.IntField(default=0)
    total_cells = fields.IntField(default=0)
    status = fields.CharField(max_length=16, default="queued", choices=TRANSLATION_TASK_STATUSES)
    progress = fields.IntField(default=0)
    error_code: str | None = fields.CharField(max_length=64, null=True)
    error_message: str | None = fields.CharField(max_length=512, null=True)
    result: dict[str, Any] | None = fields.JSONField(null=True)

    class Meta:
        table = "translation_tasks"
        indexes = [
            ("project_id", "created_at"),
            ("project_id", "status"),
            ("api_key_id", "status"),
        ]


class TranslationTaskFile(TimestampedModel):
    task = fields.ForeignKeyField("models.TranslationTask", related_name="files", on_delete=fields.CASCADE)
    document = fields.ForeignKeyField("models.Document", related_name="translation_task_links", on_delete=fields.CASCADE)

    class Meta:
        table = "translation_task_files"
        unique_together = (("task", "document"),)
        indexes = [("task_id",), ("document_id",)]


__all__ = ["TRANSLATION_TASK_STATUSES", "TranslationTask", "TranslationTaskFile"]
