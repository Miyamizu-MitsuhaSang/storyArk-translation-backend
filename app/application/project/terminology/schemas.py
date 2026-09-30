from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


TerminologyBaseStatus = Literal["draft", "active", "archived"]
TerminologyTermStatus = Literal["draft", "suggested", "approved", "deprecated", "archived"]
TerminologyTermType = Literal["character", "faction", "location", "item", "skill", "ui", "general"]


def _unique_languages(value: list[str]) -> list[str]:
    normalized = [item.strip() for item in value]
    if not normalized or any(not item for item in normalized):
        raise ValueError("语言列表不能为空且不能包含空值")
    if len(set(normalized)) != len(normalized):
        raise ValueError("语言列表不能重复")
    return normalized


class TerminologyBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160, description="术语库名称。")
    description: str | None = Field(default=None, description="术语库用途和领域说明。")
    source_language: str = Field(min_length=1, max_length=16, description="术语库源语言 BCP 47 标签。")
    target_languages: list[str] = Field(min_length=1, description="术语库支持的目标语言标签列表。")
    priority: int = Field(default=0, ge=0, le=10000, description="术语库匹配优先级。")
    status: TerminologyBaseStatus = Field(default="active", description="术语库状态。")

    _target_languages_unique = field_validator("target_languages")(_unique_languages)


class TerminologyBaseResponse(BaseModel):
    id: UUID = Field(description="术语库 ID。")
    project_id: UUID = Field(description="所属项目 ID。")
    name: str = Field(description="术语库名称。")
    description: str | None = Field(description="术语库说明。")
    source_language: str = Field(description="源语言标签。")
    target_languages: list[str] = Field(description="目标语言标签列表。")
    priority: int = Field(description="术语库匹配优先级。")
    status: TerminologyBaseStatus = Field(description="术语库状态。")
    version: int = Field(description="术语库版本号。")
    term_count: int = Field(description="当前未删除术语数量。")
    created_at: datetime = Field(description="术语库创建时间。")
    updated_at: datetime = Field(description="术语库最后更新时间。")


class TerminologyBasePage(BaseModel):
    items: list[TerminologyBaseResponse] = Field(description="术语库列表。")
    next_cursor: str | None = Field(description="下一页游标；没有下一页时为 null。")
    total: int = Field(description="术语库总数。")


class TerminologyTermCreateRequest(BaseModel):
    source_term: str = Field(min_length=1, max_length=512, description="源语言术语。")
    target_terms: dict[str, str] = Field(min_length=1, description="按目标语言记录的官方译文。")
    term_type: TerminologyTermType = Field(description="术语类型。")
    status: TerminologyTermStatus = Field(default="suggested", description="术语状态。")
    forbidden_translations: list[str] = Field(default_factory=list, description="禁止使用的译法列表。")
    case_sensitive: bool = Field(default=False, description="匹配时是否区分大小写。")
    notes: str | None = Field(default=None, description="术语说明和使用备注。")
    worldview_entry_id: UUID | None = Field(default=None, description="关联的世界观条目 ID。")


class TerminologyTermUpdateRequest(BaseModel):
    source_term: str | None = Field(default=None, min_length=1, max_length=512, description="新的源语言术语。")
    target_terms: dict[str, str] | None = Field(default=None, min_length=1, description="新的官方译文。")
    term_type: TerminologyTermType | None = Field(default=None, description="新的术语类型。")
    status: TerminologyTermStatus | None = Field(default=None, description="新的术语状态。")
    forbidden_translations: list[str] | None = Field(default=None, description="新的禁止译法列表。")
    case_sensitive: bool | None = Field(default=None, description="新的大小写匹配设置。")
    notes: str | None = Field(default=None, description="新的术语备注；传 null 可清空。")
    worldview_entry_id: UUID | None = Field(default=None, description="新的世界观条目 ID；传 null 可解除关联。")
    change_note: str | None = Field(default=None, description="本次版本变更说明。")


class TerminologyTermQuery(BaseModel):
    q: str | None = Field(default=None, max_length=512, description="匹配源术语、译文或备注的关键词。")
    term_type: TerminologyTermType | None = Field(default=None, description="按术语类型筛选。")
    status: TerminologyTermStatus | None = Field(default=None, description="按术语状态筛选。")
    language: str | None = Field(default=None, max_length=16, description="按目标语言标签筛选。")
    page_size: int = Field(default=20, ge=1, le=100, description="每页返回数量。")
    cursor: str | None = Field(default=None, description="不透明分页游标。")


class TerminologyTermRevisionSummary(BaseModel):
    id: UUID = Field(description="版本快照 ID。")
    version: int = Field(description="术语版本号。")
    changed_by_id: UUID | None = Field(description="产生该版本的用户 ID。")
    change_note: str | None = Field(description="版本变更说明。")
    changed_at: datetime = Field(description="版本生成时间。")


class TerminologyTermResponse(BaseModel):
    id: UUID = Field(description="术语 ID。")
    base_id: UUID = Field(description="所属术语库 ID。")
    source_term: str = Field(description="源语言术语。")
    target_terms: dict[str, str] = Field(description="按目标语言记录的官方译文。")
    term_type: TerminologyTermType = Field(description="术语类型。")
    status: TerminologyTermStatus = Field(description="术语状态。")
    forbidden_translations: list[str] = Field(description="禁止使用的译法列表。")
    case_sensitive: bool = Field(description="匹配时是否区分大小写。")
    notes: str | None = Field(description="术语说明和使用备注。")
    worldview_entry_id: UUID | None = Field(description="关联的世界观条目 ID。")
    source: str = Field(description="术语来源。")
    version: int = Field(description="术语当前版本号。")
    deleted_at: datetime | None = Field(description="软删除时间；未删除时为 null。")
    created_by_id: UUID | None = Field(description="创建术语的用户 ID。")
    created_at: datetime = Field(description="术语创建时间。")
    updated_at: datetime = Field(description="术语最后更新时间。")
    history: list[TerminologyTermRevisionSummary] = Field(default_factory=list, description="版本历史摘要。")


class TerminologyTermPage(BaseModel):
    items: list[TerminologyTermResponse] = Field(description="术语列表。")
    next_cursor: str | None = Field(description="下一页游标；没有下一页时为 null。")
    total: int = Field(description="符合筛选条件的术语总数。")


class TerminologySearchRequest(BaseModel):
    text: str = Field(min_length=1, description="待查询的源语言文本。")
    source_language: str = Field(min_length=1, max_length=16, description="文本源语言标签。")
    target_language: str = Field(min_length=1, max_length=16, description="目标语言标签。")
    include_forbidden: bool = Field(default=False, description="是否返回禁止译法命中。")


class TerminologyMatchResponse(BaseModel):
    term_id: UUID = Field(description="命中的术语 ID。")
    base_id: UUID = Field(description="术语库 ID。")
    source_term: str = Field(description="规范源语言术语。")
    matched_text: str = Field(description="文本中实际命中的内容。")
    target_language: str = Field(description="返回译文对应的目标语言。")
    target_term: str = Field(description="推荐译文或禁止译文。")
    status: Literal["approved", "forbidden", "suggested", "draft", "deprecated"] = Field(description="命中状态。")
    start: int = Field(ge=0, description="命中区间起始位置，按 Python 字符索引。")
    end: int = Field(ge=0, description="命中区间结束位置，不包含该位置。")
    case_sensitive: bool = Field(description="该术语匹配是否区分大小写。")


class TerminologySearchResponse(BaseModel):
    items: list[TerminologyMatchResponse] = Field(description="术语命中列表。")
    total: int = Field(description="命中总数。")
