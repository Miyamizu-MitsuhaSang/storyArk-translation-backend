from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


SegmentSaveMode = Literal["draft", "translated"]
SuggestionSource = Literal["tm", "terminology", "worldview", "rag", "llm"]
QACheck = Literal["placeholders", "numbers", "tags", "terminology", "length", "style"]
BulkAction = Literal["submit_review", "qa", "approve", "reject", "confirm"]


class SegmentResponse(BaseModel):
    id: UUID = Field(description="片段 ID。")
    document_id: UUID = Field(description="所属文档 ID。")
    segment_no: int = Field(description="片段顺序编号。")
    source: str = Field(description="源文。")
    target: str | None = Field(description="当前译文。")
    source_language: str = Field(description="源语言标签。")
    target_language: str = Field(description="目标语言标签。")
    status: str = Field(description="片段翻译状态。")
    workflow_state: str = Field(description="片段工作流状态。")
    assigned_to: UUID | None = Field(description="当前分配用户。")
    translator_note: str | None = Field(description="译员备注。")
    qa_results: dict[str, Any] = Field(description="最近一次 QA 结果。")
    version: int = Field(description="片段编辑版本。")
    updated_at: datetime = Field(description="更新时间。")


class SegmentLockRequest(BaseModel):
    duration_seconds: int = Field(default=900, ge=60, le=1800, description="锁租约时长，单位为秒。")


class SegmentLockRenewRequest(BaseModel):
    lock_token: str = Field(min_length=1, max_length=128, description="当前锁令牌。")
    duration_seconds: int = Field(default=900, ge=60, le=1800, description="续租时长，单位为秒。")


class SegmentLockReleaseRequest(BaseModel):
    lock_token: str = Field(min_length=1, max_length=128, description="当前锁令牌。")


class SegmentLockResponse(BaseModel):
    segment_id: UUID = Field(description="片段 ID。")
    lock_token: str = Field(description="锁令牌。")
    locked_by: UUID = Field(description="锁持有用户 ID。")
    locked_until: datetime = Field(description="锁到期时间。")


class SegmentUpdateRequest(BaseModel):
    target: str | None = Field(default=None, description="要保存的译文；传 null 表示清空译文。")
    translator_note: str | None = Field(default=None, description="译员备注；传 null 可清空。")
    version: int = Field(ge=1, description="客户端读取到的片段版本。")
    lock_token: str = Field(min_length=1, max_length=128, description="当前编辑锁令牌。")
    save_as: SegmentSaveMode = Field(default="draft", description="保存为草稿或已翻译状态。")


class SegmentChangeSummary(BaseModel):
    version: int = Field(description="变更后版本。")
    action: str = Field(description="变更动作。")
    user_id: UUID | None = Field(description="操作用户 ID。")
    changed_at: datetime = Field(description="变更时间。")


class SegmentDetailResponse(BaseModel):
    segment: SegmentResponse = Field(description="片段当前内容。")
    previous: SegmentResponse | None = Field(description="前一个片段；没有时为空。")
    next: SegmentResponse | None = Field(description="后一个片段；没有时为空。")
    lock: SegmentLockResponse | None = Field(description="当前有效编辑锁。")
    terminology_matches: list[dict[str, Any]] = Field(description="术语命中摘要。")
    worldview_matches: list[dict[str, Any]] = Field(description="世界观命中摘要。")
    recent_changes: list[SegmentChangeSummary] = Field(description="最近片段变更摘要。")


class SuggestionRequest(BaseModel):
    providers: list[SuggestionSource] = Field(default_factory=lambda: ["tm", "terminology", "worldview"], description="建议来源。")
    include_explanation: bool = Field(default=False, description="是否返回证据说明。")
    temperature: float = Field(default=0.2, ge=0, le=2, description="预留的生成温度；本版本不调用外部 provider。")
    lock_token: str | None = Field(default=None, max_length=128, description="可选的当前编辑锁令牌。")


class SuggestionResponse(BaseModel):
    id: UUID = Field(description="建议 ID。")
    text: str = Field(description="建议译文。")
    source: SuggestionSource = Field(description="建议来源。")
    score: float = Field(description="建议排序分数。")
    evidence: list[dict[str, Any]] = Field(description="证据引用。")
    warnings: list[str] = Field(description="警告代码。")


class SuggestionsResponse(BaseModel):
    segment_id: UUID = Field(description="片段 ID。")
    suggestions: list[SuggestionResponse] = Field(description="建议列表。")
    warnings: list[str] = Field(default_factory=list, description="未启用或不可用的建议来源警告。")


class QARequest(BaseModel):
    checks: list[QACheck] = Field(default_factory=lambda: ["placeholders", "numbers", "tags", "terminology", "length", "style"], description="要执行的 QA 检查。")
    save_results: bool = Field(default=True, description="是否保存 QA 结果。")


class QAIssue(BaseModel):
    id: str = Field(description="QA 问题 ID。")
    rule: str = Field(description="QA 规则。")
    severity: Literal["error", "warning", "info"] = Field(description="问题严重级别。")
    message: str = Field(description="问题说明。")
    source_span: list[int] = Field(description="源文字符区间。")
    target_span: list[int] = Field(description="译文字符区间。")
    can_ignore: bool = Field(description="是否允许忽略。")


class QAResponse(BaseModel):
    segment_id: UUID = Field(description="片段 ID。")
    summary: dict[str, int] = Field(description="按严重级别汇总的问题数。")
    issues: list[QAIssue] = Field(description="QA 问题列表。")


class WorkflowSubmitReviewRequest(BaseModel):
    version: int = Field(ge=1, description="客户端读取到的片段版本。")
    lock_token: str = Field(min_length=1, max_length=128, description="当前编辑锁令牌。")
    comment: str | None = Field(default=None, description="提交审核说明。")


class WorkflowApproveRequest(BaseModel):
    version: int = Field(ge=1, description="客户端读取到的片段版本。")
    comment: str | None = Field(default=None, description="审核说明。")


class WorkflowRejectRequest(BaseModel):
    version: int = Field(ge=1, description="客户端读取到的片段版本。")
    reason: str = Field(min_length=1, description="退回原因。")
    issue_ids: list[str] = Field(default_factory=list, description="关联的 QA 问题 ID。")


class WorkflowConfirmRequest(BaseModel):
    version: int = Field(ge=1, description="客户端读取到的片段版本。")


class WorkflowUnconfirmRequest(BaseModel):
    version: int = Field(ge=1, description="客户端读取到的片段版本。")


class BulkActionRequest(BaseModel):
    segment_ids: list[UUID] = Field(min_length=1, max_length=1000, description="要操作的片段 ID 列表；超过 100 条时转为异步任务。")
    action: BulkAction = Field(description="批量动作。")
    expected_versions: dict[UUID, int] = Field(description="每个片段的期望版本。")
    confirm: bool = Field(default=False, description="破坏性动作的确认标志。")


class BulkActionResponse(BaseModel):
    affected: int = Field(description="受影响的片段数。")
    items: list[SegmentResponse] = Field(description="操作后的片段。")
    job_id: UUID | None = Field(default=None, description="异步任务 ID；当前同步阈值内为空。")
