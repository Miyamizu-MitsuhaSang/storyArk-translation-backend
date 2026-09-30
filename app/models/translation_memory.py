from datetime import datetime
from typing import Any
from uuid import UUID

from tortoise import fields
from tortoise.exceptions import IntegrityError

from .base import TimestampedModel

TM_LIBRARY_SCOPES = ("platform", "user")
TM_LIBRARY_STATUSES = ("draft", "active", "archived")
TM_ENTRY_STATUSES = ("active", "deprecated", "archived")
TM_ENTRY_ORIGINS = ("platform_seed", "confirmed_segment", "manual", "import", "imported", "machine_translated")


class TranslationMemoryLibrary(TimestampedModel):
    scope = fields.CharField(
        max_length=16,
        choices=TM_LIBRARY_SCOPES,
        description="翻译记忆库作用域：platform 公共库或 user 用户库。",
    )
    owner_user = fields.ForeignKeyField(
        "models.User",
        related_name="translation_memory_libraries",
        null=True,
        on_delete=fields.CASCADE,
        description="用户库所属用户；公共库为空，用户删除时一并删除用户库。",
    )
    name = fields.CharField(max_length=160, description="翻译记忆库名称。")
    description: str | None = fields.TextField(null=True, description="翻译记忆库用途和领域说明。")
    status = fields.CharField(
        max_length=24,
        default="active",
        choices=TM_LIBRARY_STATUSES,
        description="翻译记忆库状态：draft、active 或 archived。",
    )
    priority = fields.IntField(default=0, description="项目检索时的库优先级，数值越大越优先。")
    content_version = fields.IntField(default=1, description="库内容版本，每次条目变更递增。")

    async def save(self, *args: Any, **kwargs: Any) -> None:
        if (self.scope == "platform") != (self.owner_user_id is None):
            raise IntegrityError("platform libraries cannot have an owner and user libraries require one")
        await super().save(*args, **kwargs)

    class Meta:
        table = "translation_memory_libraries"
        indexes = [("scope", "status"), ("owner_user_id", "status")]


class TranslationMemoryEntry(TimestampedModel):
    library = fields.ForeignKeyField(
        "models.TranslationMemoryLibrary",
        related_name="entries",
        on_delete=fields.CASCADE,
        description="条目所属翻译记忆库；库删除时一并删除条目。",
    )
    source_language = fields.CharField(max_length=16, description="源语言 BCP 47 标签。")
    target_language = fields.CharField(max_length=16, description="目标语言 BCP 47 标签。")
    source_text = fields.TextField(description="翻译记忆条目的源文文本。")
    target_text = fields.TextField(description="翻译记忆条目的目标文文本。")
    source_hash = fields.CharField(max_length=128, description="源文规范化内容的去重哈希。")
    target_hash = fields.CharField(max_length=128, description="译文规范化内容的去重哈希。")
    status = fields.CharField(
        max_length=24,
        default="active",
        choices=TM_ENTRY_STATUSES,
        description="条目状态：active 可检索或 archived 已归档。",
    )
    origin = fields.CharField(
        max_length=32,
        choices=TM_ENTRY_ORIGINS,
        description="条目来源：已确认片段、导入、机器翻译或手工录入。",
    )
    revision = fields.IntField(default=1, description="当前条目修订号，从 1 开始递增。")
    deleted_at: datetime | None = fields.DatetimeField(null=True, description="软删除时间；为空表示条目未删除。")
    metadata: dict[str, Any] = fields.JSONField(
        default=dict,
        description="受控条目元数据；仅保存非敏感业务属性，不保存密钥或凭据。",
    )

    class Meta:
        table = "translation_memory_entries"
        unique_together = (("library", "source_language", "target_language", "source_hash", "target_hash"),)
        indexes = [
            ("library_id", "source_language", "target_language", "source_hash"),
            ("library_id", "status", "updated_at"),
        ]


class TranslationMemoryEntryRevision(TimestampedModel):
    entry = fields.ForeignKeyField(
        "models.TranslationMemoryEntry",
        related_name="revisions",
        on_delete=fields.CASCADE,
        description="版本快照所属翻译记忆条目；条目删除时一并删除历史快照。",
    )
    version = fields.IntField(description="该条目的修订版本号。")
    snapshot: dict[str, Any] = fields.JSONField(description="该版本源文、译文及受控字段的完整快照。")
    changed_by_id: UUID | None = fields.UUIDField(null=True, description="产生该版本的用户 ID 快照。")
    project_id: UUID | None = fields.UUIDField(null=True, description="产生该版本的项目 ID 快照。")
    document_id: UUID | None = fields.UUIDField(null=True, description="产生该版本的文档 ID 快照。")
    segment_id: UUID | None = fields.UUIDField(null=True, description="产生该版本的片段 ID 快照。")
    change_note: str | None = fields.TextField(null=True, description="该版本的变更说明。")

    class Meta:
        table = "translation_memory_entry_revisions"
        unique_together = (("entry", "version"),)
        indexes = [("entry_id", "version"), ("changed_by_id",)]


class TranslationMemoryEntrySource(TimestampedModel):
    entry = fields.ForeignKeyField(
        "models.TranslationMemoryEntry",
        related_name="sources",
        on_delete=fields.CASCADE,
        description="来源记录所属翻译记忆条目；条目删除时一并删除来源记录。",
    )
    provider = fields.CharField(max_length=64, null=True, description="可选的来源提供方标识。")
    user_id: UUID | None = fields.UUIDField(null=True, description="来源用户 ID 快照。")
    project_id: UUID | None = fields.UUIDField(null=True, description="来源项目 ID 快照。")
    document_id: UUID | None = fields.UUIDField(null=True, description="来源文档 ID 快照。")
    segment_id: UUID | None = fields.UUIDField(null=True, description="来源片段 ID 快照。")
    metadata: dict[str, Any] = fields.JSONField(
        default=dict,
        description="受控来源元数据；不得存储 API key、令牌或其他秘密。",
    )

    class Meta:
        table = "translation_memory_entry_sources"
        unique_together = (("entry", "user_id", "project_id", "document_id", "segment_id"),)
        indexes = [("entry_id", "project_id"), ("project_id",), ("user_id",)]


class TranslationMemoryImport(TimestampedModel):
    """持久化用户导入的幂等结果，避免重复提交再次写入条目。"""

    library = fields.ForeignKeyField(
        "models.TranslationMemoryLibrary",
        related_name="imports",
        on_delete=fields.CASCADE, description="导入目标用户翻译记忆库。",
    )
    user = fields.ForeignKeyField(
        "models.User",
        related_name="translation_memory_imports",
        on_delete=fields.CASCADE, description="发起导入的用户。",
    )
    idempotency_key = fields.CharField(max_length=160, description="客户端导入幂等键。")
    imported = fields.IntField(default=0, description="成功写入的条目数。")
    skipped = fields.IntField(default=0, description="已存在而跳过的条目数。")
    invalid_rows: list[dict[str, Any]] = fields.JSONField(default=list, description="带行号的校验错误。")
    rows: list[dict[str, Any]] = fields.JSONField(default=list, description="待处理的原始导入行。")
    payload_hash = fields.CharField(max_length=64, default="", description="导入请求内容的稳定哈希，用于幂等键参数一致性校验。")
    status = fields.CharField(max_length=16, default="queued", description="导入状态。")

    class Meta:
        table = "translation_memory_imports"
        unique_together = (("library", "user", "idempotency_key"),)
        indexes = [("library_id", "created_at")]
