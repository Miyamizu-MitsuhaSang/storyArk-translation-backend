from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


DocumentStatus = Literal[
    "uploaded",
    "parsing",
    "ready",
    "failed",
    "archived",
    "deletion_pending",
    "purged",
]


class DocumentListQuery(BaseModel):
    page_size: int = Field(default=20, ge=1, le=100, description="每页返回的文档数量。")
    cursor: str | None = Field(default=None, description="不透明分页游标。")
    status: DocumentStatus | None = Field(default=None, description="按文档生命周期状态筛选。")
    file_name: str | None = Field(default=None, max_length=255, description="按原始文件名筛选。")
    created_by: UUID | None = Field(default=None, description="按上传用户筛选。")
    source_language: str | None = Field(default=None, max_length=16, description="按源语言筛选。")
    target_language: str | None = Field(default=None, max_length=16, description="按目标语言筛选。")
    sort: Literal["created_at", "updated_at", "name"] = Field(
        default="created_at", description="排序字段，默认按创建时间倒序。"
    )


class DocumentParseRequest(BaseModel):
    preserve_translations: bool = Field(
        default=False,
        description="文档已有译文时是否保留现有译文；存在译文时必须显式设置为 true。",
    )


class DocumentExportRequest(BaseModel):
    format: Literal["xliff", "csv", "json", "po", "txt"] = Field(description="导出格式。")
    include_untranslated: bool = Field(default=False, description="是否包含未翻译片段。")
    include_review_notes: bool = Field(default=False, description="是否包含审校备注。")


class DocumentResponse(BaseModel):
    id: UUID = Field(description="文档业务 ID。")
    project_id: UUID = Field(description="所属项目 ID。")
    name: str = Field(description="文档显示名称。")
    original_filename: str = Field(description="上传时的原始文件名。")
    format: str = Field(description="文档格式。")
    mime_type: str | None = Field(description="上传文件 MIME 类型。")
    source_language: str = Field(description="源语言 BCP 47 标签。")
    target_language: str = Field(description="目标语言 BCP 47 标签。")
    status: DocumentStatus = Field(description="文档生命周期状态。")
    version: int = Field(description="文档解析版本。")
    size_bytes: int = Field(description="文件大小，单位为字节。")
    checksum: str = Field(description="文件 SHA-256 校验和。")
    created_by: UUID | None = Field(description="上传用户 ID。")
    segment_count: int = Field(description="片段总数。")
    translated_segment_count: int = Field(description="已有译文的片段数量。")
    error_count: int = Field(description="最近一次导入或解析错误数。")
    import_errors: list[dict[str, object]] = Field(description="脱敏后的导入错误列表。")
    archived_at: datetime | None = Field(default=None, description="归档时间。")
    deleted_at: datetime | None = Field(default=None, description="软删除时间。")
    purge_after: datetime | None = Field(default=None, description="允许物理清理的时间。")
    purged_at: datetime | None = Field(default=None, description="文件实际清理完成时间。")
    created_at: datetime = Field(description="创建时间。")
    updated_at: datetime = Field(description="更新时间。")


class DocumentPage(BaseModel):
    items: list[DocumentResponse] = Field(description="文档列表。")
    next_cursor: str | None = Field(description="下一页游标。")
    total: int = Field(description="符合条件的文档总数。")


class DocumentSegmentResponse(BaseModel):
    id: UUID = Field(description="片段 ID。")
    document_id: UUID = Field(description="所属文档 ID。")
    segment_no: int = Field(description="片段顺序编号。")
    source: str = Field(description="源文。")
    target: str | None = Field(description="当前译文。")
    source_language: str = Field(description="源语言。")
    target_language: str = Field(description="目标语言。")
    status: str = Field(description="片段翻译状态。")
    workflow_state: str = Field(description="片段工作流状态。")
    assigned_to: UUID | None = Field(description="当前分配用户。")
    version: int = Field(description="片段编辑版本。")
    updated_at: datetime = Field(description="更新时间。")


class DocumentSegmentPage(BaseModel):
    items: list[DocumentSegmentResponse] = Field(description="片段列表。")
    next_cursor: str | None = Field(description="下一页游标。")
    total: int = Field(description="符合条件的片段总数。")


class DocumentTaskResponse(BaseModel):
    document: DocumentResponse = Field(description="关联文档。")
    job_id: UUID = Field(description="后台任务 ID。")


class DocumentEnvelopeResponse(BaseModel):
    document: DocumentResponse = Field(description="归档后的文档。")


class DocumentTaskStatusResponse(BaseModel):
    job_id: UUID = Field(description="后台任务 ID。")
    type: str = Field(description="文档后台任务类型。")
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] = Field(description="任务状态。")
    requested_version: int = Field(description="任务提交时捕获的文档版本。")
    attempts: int = Field(description="任务领取次数。")
    max_attempts: int = Field(description="最大领取次数。")
    result: dict[str, object] | None = Field(description="脱敏任务结果。")
    error_code: str | None = Field(description="失败代码。")
    error_message: str | None = Field(description="脱敏失败信息。")
    created_at: datetime = Field(description="任务创建时间。")
    updated_at: datetime = Field(description="任务更新时间。")
