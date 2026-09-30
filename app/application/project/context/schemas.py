from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from ..worldview.schemas import WorldviewEntryResponse, WorldviewResponse


ContextSource = Literal["worldview", "terms", "tm", "neighbors"]


class ContextQuery(BaseModel):
    segment_id: str | None = Field(default=None, description="当前 segment ID；文档/segment 模块接入后用于邻近上下文聚合。")
    q: str | None = Field(default=None, max_length=500, description="用于匹配世界观条目和上下文关键词的文本。")
    include: str = Field(
        default="worldview,terms,tm,neighbors",
        description="逗号分隔的上下文来源：worldview、terms、tm、neighbors。",
    )

    def requested_sources(self) -> list[ContextSource]:
        allowed = {"worldview", "terms", "tm", "neighbors"}
        values = [value.strip() for value in self.include.split(",") if value.strip()]
        invalid = [value for value in values if value not in allowed]
        if invalid:
            raise ValueError(f"不支持的上下文来源: {', '.join(invalid)}")
        return list(dict.fromkeys(values))  # type: ignore[return-value]


class ContextResponse(BaseModel):
    project_id: UUID = Field(description="项目 ID。")
    segment_id: str | None = Field(description="请求中的 segment ID。")
    query: str | None = Field(description="请求中的关键词。")
    included_sources: list[ContextSource] = Field(description="本次请求包含的上下文来源。")
    worldview: WorldviewResponse | None = Field(description="项目级世界观摘要；未请求或尚未创建时为 null。")
    worldview_entries: list[WorldviewEntryResponse] = Field(description="相关世界观条目。")
    terms: list[dict[str, Any]] = Field(description="术语命中；术语模块接入前为空列表。")
    tm_matches: list[dict[str, Any]] = Field(description="翻译记忆匹配；TM 模块接入前为空列表。")
    neighbors: list[dict[str, Any]] = Field(description="相邻 segment；segment 模块接入前为空列表。")
