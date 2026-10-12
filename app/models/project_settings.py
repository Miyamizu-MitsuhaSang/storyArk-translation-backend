from __future__ import annotations

from decimal import Decimal

from tortoise import fields

from .base import TimestampedModel


class ProjectSettings(TimestampedModel):
    project = fields.OneToOneField(
        "models.Project",
        related_name="settings",
        on_delete=fields.CASCADE,
        description="项目设置所属项目；项目删除时级联删除。",
    )
    default_source_language = fields.CharField(
        max_length=16,
        null=True,
        description="项目默认源语言标签。",
    )
    default_target_language = fields.CharField(
        max_length=16,
        null=True,
        description="项目默认目标语言标签。",
    )
    terminology_enabled = fields.BooleanField(
        default=True,
        description="是否启用项目术语规则。",
    )
    translation_memory_enabled = fields.BooleanField(
        default=True,
        description="是否启用项目翻译记忆。",
    )
    default_model = fields.CharField(
        max_length=160,
        null=True,
        description="项目默认 AI 模型标识。",
    )
    quality_threshold = fields.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=Decimal("0.7"),
        description="项目质量阈值，范围为 0 到 1。",
    )
    revision = fields.IntField(
        default=1,
        description="项目设置的乐观并发版本。",
    )

    class Meta:
        table = "project_settings"
        indexes = [("project_id", "updated_at")]


__all__ = ["ProjectSettings"]
