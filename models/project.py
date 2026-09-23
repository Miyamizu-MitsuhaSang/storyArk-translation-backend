from datetime import datetime
from typing import Any

from tortoise import fields

from models.base import TimestampedModel

PROJECT_STATUSES = ("draft", "active", "archived")
PROJECT_MEMBER_ROLES = ("owner", "manager", "translator", "reviewer", "viewer")
WORLDVIEW_STATUSES = ("draft", "active", "archived")
WORLDVIEW_ENTRY_TYPES = (
    "character",
    "faction",
    "location",
    "item",
    "skill",
    "quest",
    "creature",
    "system",
    "lore",
    "rule",
    "style_guide",
)


class Project(TimestampedModel):
    key = fields.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        description="项目的唯一业务标识，用于 URL 和外部引用。",
    )
    name = fields.CharField(max_length=160, description="项目名称。")
    description: str | None = fields.TextField(null=True, description="项目用途和背景说明。")
    status = fields.CharField(
        max_length=24,
        default="draft",
        choices=PROJECT_STATUSES,
        description="项目状态：draft 草稿、active 启用、archived 归档。",
    )
    created_by = fields.ForeignKeyField(
        "models.User",
        related_name="created_projects",
        null=True,
        on_delete=fields.SET_NULL,
        description="项目创建者；用户删除后保留项目并清空此关联。",
    )

    class Meta:
        table = "projects"
        indexes = [("status",), ("name",)]


class ProjectMember(TimestampedModel):
    project = fields.ForeignKeyField(
        "models.Project",
        related_name="members",
        on_delete=fields.CASCADE,
        description="成员所属项目；项目删除时一并删除成员关系。",
    )
    user = fields.ForeignKeyField(
        "models.User",
        related_name="project_memberships",
        on_delete=fields.CASCADE,
        description="项目成员对应的用户；用户删除时一并删除成员关系。",
    )
    role = fields.CharField(
        max_length=24,
        default="translator",
        choices=PROJECT_MEMBER_ROLES,
        description="成员在项目中的角色：owner、manager、translator、reviewer 或 viewer。",
    )

    class Meta:
        table = "project_members"
        unique_together = (("project", "user"),)
        indexes = [("project_id", "role"), ("user_id",)]


class ProjectLanguagePair(TimestampedModel):
    project = fields.ForeignKeyField(
        "models.Project",
        related_name="language_pairs",
        on_delete=fields.CASCADE,
        description="语言对所属项目；项目删除时一并删除语言对。",
    )
    source_language = fields.CharField(
        max_length=16,
        description="源语言的 BCP 47 语言标签，例如 zh-CN。",
    )
    target_language = fields.CharField(
        max_length=16,
        description="目标语言的 BCP 47 语言标签，例如 en-US。",
    )
    is_default = fields.BooleanField(default=False, description="该语言对是否为项目默认语言对。")
    is_active = fields.BooleanField(default=True, description="该语言对当前是否启用。")

    class Meta:
        table = "project_language_pairs"
        unique_together = (("project", "source_language", "target_language"),)
        indexes = [("project_id", "is_active")]


class Worldview(TimestampedModel):
    project = fields.OneToOneField(
        "models.Project",
        related_name="worldview",
        on_delete=fields.CASCADE,
        description="世界观所属项目；每个项目最多一个世界观，项目删除时一并删除。",
    )
    name = fields.CharField(max_length=160, description="世界观文档名称。")
    style_guide: str | None = fields.TextField(null=True, description="项目级翻译风格指南和全局规则。")
    default_tone: str | None = fields.CharField(
        max_length=80,
        null=True,
        description="项目文本的默认语气或风格标签。",
    )
    version_note: str | None = fields.TextField(null=True, description="当前世界观版本的变更摘要。")
    status = fields.CharField(
        max_length=24,
        default="draft",
        choices=WORLDVIEW_STATUSES,
        description="世界观状态：draft 草稿、active 启用、archived 归档。",
    )
    version = fields.IntField(default=1, description="世界观当前版本号，从 1 开始递增。")

    class Meta:
        table = "worldviews"


class WorldviewEntry(TimestampedModel):
    worldview = fields.ForeignKeyField(
        "models.Worldview",
        related_name="entries",
        on_delete=fields.CASCADE,
        description="条目所属世界观；世界观删除时一并删除条目。",
    )
    entry_key = fields.CharField(max_length=128, description="世界观内稳定且唯一的条目业务键。")
    entry_type = fields.CharField(
        max_length=32,
        choices=WORLDVIEW_ENTRY_TYPES,
        description="条目类型，如角色、阵营、地点、物品、技能、设定或规则。",
    )
    name = fields.CharField(max_length=160, description="世界观条目的规范名称。")
    aliases = fields.JSONField(default=list, description="条目的别名列表，用于检索和匹配。")
    description: str | None = fields.TextField(null=True, description="条目的背景、定义或使用说明。")
    attributes: dict[str, Any] = fields.JSONField(
        default=dict,
        description="条目的结构化属性，例如性别、身份或语域。",
    )
    language_variants: dict[str, str] = fields.JSONField(
        default=dict,
        description="按语言标签记录的官方名称或表达，例如 en-US 对应译名。",
    )
    tags: list[str] = fields.JSONField(default=list, description="用于筛选和分类的标签列表。")
    status = fields.CharField(
        max_length=24,
        default="active",
        choices=WORLDVIEW_STATUSES,
        description="条目状态：draft 草稿、active 启用、archived 归档。",
    )
    version = fields.IntField(default=1, description="条目当前版本号，从 1 开始递增。")
    deleted_at: datetime | None = fields.DatetimeField(
        null=True,
        description="软删除时间；为空表示条目未删除。",
    )

    class Meta:
        table = "worldview_entries"
        unique_together = (("worldview", "entry_key"),)
        indexes = [("worldview_id", "entry_type"), ("worldview_id", "status")]
