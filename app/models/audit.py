from __future__ import annotations

from typing import Any
from uuid import UUID

from tortoise import fields

from .base import TimestampedModel


class ProjectAuditEvent(TimestampedModel):
    """Append-only, secret-free audit event scoped to a project."""

    project_id: UUID = fields.UUIDField(description="项目 ID 快照。")
    actor_user_id: UUID | None = fields.UUIDField(null=True, description="操作者用户 ID 快照。")
    resource_type = fields.CharField(max_length=64, description="受影响资源类型。")
    resource_id: UUID | None = fields.UUIDField(null=True, description="受影响资源 ID 快照。")
    action = fields.CharField(max_length=96, description="稳定的业务动作标识。")
    details: dict[str, Any] = fields.JSONField(default=dict, description="脱敏后的业务摘要，不得包含凭据或模型原文。")

    class Meta:
        table = "project_audit_events"
        indexes = [
            ("project_id", "created_at"),
            ("project_id", "actor_user_id", "created_at"),
            ("project_id", "resource_type", "created_at"),
            ("project_id", "action", "created_at"),
        ]


class IdempotencyRecord(TimestampedModel):
    """Stores the first result of retryable HTTP operations."""

    user_id: UUID = fields.UUIDField(description="请求用户 ID 快照。")
    operation = fields.CharField(max_length=96, description="稳定的 API 操作标识。")
    scope = fields.CharField(max_length=160, description="操作资源范围。")
    idempotency_key = fields.CharField(max_length=160, description="客户端幂等键。")
    request_hash = fields.CharField(max_length=64, description="请求体及业务参数的 SHA-256。")
    response_json: dict[str, Any] | None = fields.JSONField(null=True, description="首次成功响应快照。")

    class Meta:
        table = "api_idempotency_records"
        unique_together = (("user_id", "idempotency_key"),)
        indexes = [("scope", "created_at")]
