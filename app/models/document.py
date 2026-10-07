"""文档、文档片段和片段编辑锁的持久化模型。"""

from datetime import datetime
from typing import Any

from tortoise import fields

from .base import TimestampedModel


DOCUMENT_STATUSES = ("uploaded", "parsing", "ready", "failed", "archived")
DOCUMENT_FORMATS = ("xliff", "csv", "json", "po", "txt", "unknown")
DOCUMENT_SEGMENT_STATUSES = (
    "untranslated",
    "translated",
    "reviewed",
    "approved",
    "rejected",
    "archived",
)
DOCUMENT_WORKFLOW_STATES = ("draft", "in_review", "approved", "rejected")


class Document(TimestampedModel):
    """项目中的可导入、解析、编辑和导出的翻译文档。"""

    project = fields.ForeignKeyField(
        "models.Project",
        related_name="documents",
        on_delete=fields.CASCADE,
        description="文档所属项目；项目删除时一并删除文档及其片段。",
    )
    created_by = fields.ForeignKeyField(
        "models.User",
        related_name="created_documents",
        null=True,
        on_delete=fields.SET_NULL,
        description="文档上传或创建人；用户删除后保留文档并清空此关联。",
    )
    name = fields.CharField(max_length=160, description="文档在项目中的显示名称。")
    file_name = fields.CharField(max_length=255, description="上传时的原始文件名。")
    file_format = fields.CharField(
        max_length=16,
        choices=DOCUMENT_FORMATS,
        default="unknown",
        description="文档格式：xliff、csv、json、po、txt 或 unknown。",
    )
    mime_type: str | None = fields.CharField(
        max_length=128,
        null=True,
        description="上传文件的 MIME 类型；无法识别时为空。",
    )
    storage_uri: str | None = fields.CharField(
        max_length=1024,
        null=True,
        description="原始文件在对象存储中的不透明地址；清理文件后可置空。",
    )
    file_size = fields.BigIntField(default=0, description="原始文件大小，单位为字节。")
    checksum_sha256 = fields.CharField(max_length=64, description="原始文件内容的 SHA-256 校验值。")
    source_language = fields.CharField(max_length=16, description="文档源语言的 BCP 47 标签。")
    target_language = fields.CharField(max_length=16, description="文档目标语言的 BCP 47 标签。")
    translation_memory_ids: list[str] = fields.JSONField(
        default=list,
        description="上传或解析时选用的翻译记忆库 ID 列表，以字符串形式保存。",
    )
    status = fields.CharField(
        max_length=24,
        choices=DOCUMENT_STATUSES,
        default="uploaded",
        description="文档状态：uploaded、parsing、ready、failed 或 archived。",
    )
    version = fields.IntField(default=1, description="文档解析版本，从 1 开始递增。")
    segment_count = fields.IntField(default=0, description="文档当前片段总数，用于列表统计。")
    translated_segment_count = fields.IntField(
        default=0,
        description="当前已有译文的片段数量，用于列表统计。",
    )
    error_count = fields.IntField(default=0, description="最近一次解析或导入错误数量。")
    import_errors: list[dict[str, Any]] = fields.JSONField(
        default=list,
        description="最近一次导入或解析的脱敏错误列表，包含行号和错误码。",
    )
    last_parse_job_id = fields.UUIDField(
        null=True,
        description="最近一次解析后台任务 ID 快照；任务删除后仍可保留该标识。",
    )
    parsed_at: datetime | None = fields.DatetimeField(
        null=True,
        description="最近一次成功解析完成的时间。",
    )
    deleted_at: datetime | None = fields.DatetimeField(
        null=True,
        description="文档软删除时间；为空表示文档未标记删除。",
    )
    purge_after: datetime | None = fields.DatetimeField(
        null=True,
        description="文档允许被定期物理清除的时间；为空表示暂不自动清除。",
    )

    class Meta:
        table = "documents"
        indexes = [
            ("project_id", "status"),
            ("project_id", "source_language", "target_language"),
            ("project_id", "created_at"),
            ("project_id", "deleted_at"),
            ("purge_after",),
        ]


class DocumentSegment(TimestampedModel):
    """文档中可独立编辑、锁定、审核和写入 TM 的翻译片段。"""

    document = fields.ForeignKeyField(
        "models.Document",
        related_name="segments",
        on_delete=fields.CASCADE,
        description="片段所属文档；文档删除时一并删除片段。",
    )
    segment_no = fields.IntField(description="片段在文档中的稳定顺序编号，从 1 开始。")
    source_text = fields.TextField(description="片段源文。")
    target_text: str | None = fields.TextField(null=True, description="片段当前译文；未翻译时为空。")
    source_language = fields.CharField(max_length=16, description="片段源语言的 BCP 47 标签。")
    target_language = fields.CharField(max_length=16, description="片段目标语言的 BCP 47 标签。")
    status = fields.CharField(
        max_length=24,
        choices=DOCUMENT_SEGMENT_STATUSES,
        default="untranslated",
        description="片段翻译状态：untranslated、translated、reviewed、approved、rejected 或 archived。",
    )
    workflow_state = fields.CharField(
        max_length=24,
        choices=DOCUMENT_WORKFLOW_STATES,
        default="draft",
        description="片段工作流状态：draft、in_review、approved 或 rejected。",
    )
    assigned_to = fields.ForeignKeyField(
        "models.User",
        related_name="assigned_document_segments",
        null=True,
        on_delete=fields.SET_NULL,
        description="当前分配的译员或审校者；用户删除后清空分配。",
    )
    context: dict[str, Any] = fields.JSONField(
        default=dict,
        description="片段前后文和导入上下文等受控结构化信息。",
    )
    review_notes: list[dict[str, Any]] = fields.JSONField(
        default=list,
        description="片段审校备注列表；不得存储密钥或其他敏感凭据。",
    )
    version = fields.IntField(default=1, description="片段当前编辑版本，用于乐观锁。")
    translated_at: datetime | None = fields.DatetimeField(
        null=True,
        description="片段首次或最近一次保存译文的时间。",
    )
    deleted_at: datetime | None = fields.DatetimeField(
        null=True,
        description="片段软删除时间；为空表示片段未标记删除。",
    )
    purge_after: datetime | None = fields.DatetimeField(
        null=True,
        description="片段允许被定期物理清除的时间；为空表示暂不自动清除。",
    )

    class Meta:
        table = "document_segments"
        unique_together = (("document", "segment_no"),)
        indexes = [
            ("document_id", "status"),
            ("document_id", "workflow_state"),
            ("document_id", "assigned_to_id"),
            ("document_id", "deleted_at"),
            ("purge_after",),
        ]


class SegmentLock(TimestampedModel):
    """文档片段的短期编辑租约，过期后可由定时任务清除。"""

    segment = fields.OneToOneField(
        "models.DocumentSegment",
        related_name="lock",
        on_delete=fields.CASCADE,
        description="被锁定的文档片段；片段删除时一并删除锁。",
    )
    user = fields.ForeignKeyField(
        "models.User",
        related_name="segment_locks",
        on_delete=fields.CASCADE,
        description="当前锁持有者；用户删除时一并删除其锁。",
    )
    lock_token = fields.CharField(
        max_length=128,
        unique=True,
        description="释放或续租锁时使用的不透明锁令牌。",
    )
    locked_until = fields.DatetimeField(description="锁租约过期时间；定时任务可清除早于当前时间的锁。")
    released_at: datetime | None = fields.DatetimeField(
        null=True,
        description="主动释放锁的时间；为空表示锁尚未主动释放。",
    )

    class Meta:
        table = "segment_locks"
        indexes = [("locked_until",), ("user_id", "locked_until")]
