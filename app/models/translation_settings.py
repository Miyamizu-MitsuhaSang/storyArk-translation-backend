from __future__ import annotations

from datetime import datetime

from tortoise import fields

from .base import TimestampedModel


TRANSLATION_RULE_TYPES = ("general", "category")


class TranslationRole(TimestampedModel):
    project = fields.ForeignKeyField(
        "models.Project",
        related_name="translation_roles",
        on_delete=fields.CASCADE,
    )
    name = fields.CharField(max_length=160)
    description: str | None = fields.TextField(null=True)
    detailed_injection: str | None = fields.TextField(null=True)
    sort_order = fields.IntField(default=0)
    revision = fields.IntField(default=1)
    deleted_at: datetime | None = fields.DatetimeField(null=True)

    class Meta:
        table = "translation_roles"
        unique_together = (("project", "name"),)
        indexes = [("project_id", "sort_order"), ("project_id", "deleted_at")]


class TranslationRule(TimestampedModel):
    project = fields.ForeignKeyField(
        "models.Project",
        related_name="translation_rules",
        on_delete=fields.CASCADE,
    )
    type = fields.CharField(max_length=16, choices=TRANSLATION_RULE_TYPES)
    name = fields.CharField(max_length=160)
    text = fields.TextField()
    category: str | None = fields.CharField(max_length=80, null=True)
    enabled = fields.BooleanField(default=True)
    revision = fields.IntField(default=1)
    deleted_at: datetime | None = fields.DatetimeField(null=True)

    class Meta:
        table = "translation_rules"
        unique_together = (("project", "type", "name", "category"),)
        indexes = [("project_id", "type"), ("project_id", "category"), ("project_id", "deleted_at")]


class CultureRule(TimestampedModel):
    project = fields.ForeignKeyField(
        "models.Project",
        related_name="culture_rules",
        on_delete=fields.CASCADE,
    )
    language = fields.CharField(max_length=16)
    name = fields.CharField(max_length=160)
    text = fields.TextField()
    category: str | None = fields.CharField(max_length=80, null=True)
    revision = fields.IntField(default=1)
    deleted_at: datetime | None = fields.DatetimeField(null=True)

    class Meta:
        table = "culture_rules"
        unique_together = (("project", "language", "name", "category"),)
        indexes = [("project_id", "language"), ("project_id", "deleted_at")]


__all__ = ["CultureRule", "TranslationRole", "TranslationRule"]
