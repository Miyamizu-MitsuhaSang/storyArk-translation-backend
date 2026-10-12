from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class JobErrorResponse(BaseModel):
    code: str = Field(description="稳定的任务错误代码。")
    message: str = Field(description="已脱敏的任务错误说明。")


class JobStatusResponse(BaseModel):
    id: UUID = Field(description="后台任务 ID。")
    type: str = Field(description="后台任务类型。")
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] = Field(
        description="任务生命周期状态。"
    )
    resource_type: str = Field(description="任务所作用资源的类型。")
    resource_id: UUID = Field(description="任务所作用资源的 ID。")
    project_id: UUID | None = Field(default=None, description="任务资源所属项目 ID；平台级资源为空。")
    requested_version: int = Field(description="提交任务时捕获的资源版本。")
    attempts: int = Field(ge=0, description="任务已被 worker 领取的次数。")
    max_attempts: int = Field(ge=1, description="任务允许的最大领取次数。")
    progress: float = Field(ge=0.0, le=1.0, description="任务完成进度，范围为 0 到 1。")
    message: str | None = Field(default=None, description="任务当前阶段或结果说明。")
    result: dict[str, Any] | None = Field(default=None, description="脱敏后的任务结果。")
    error: JobErrorResponse | None = Field(default=None, description="任务错误；无错误时为空。")
    created_at: datetime = Field(description="任务创建时间。")
    started_at: datetime | None = Field(default=None, description="任务最近一次开始执行的时间。")
    updated_at: datetime = Field(description="任务最后更新时间。")
    finished_at: datetime | None = Field(default=None, description="任务完成或取消时间。")


class JobListQuery(BaseModel):
    page_size: int = Field(default=50, ge=1, le=100, description="单页返回的任务数量。")
    cursor: str | None = Field(default=None, description="服务端签发的不透明分页游标。")
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] | None = Field(
        default=None, description="按任务状态筛选。"
    )
    type: str | None = Field(default=None, max_length=64, description="按任务类型筛选。")
    project_id: UUID | None = Field(default=None, description="按项目 ID 筛选。")
    resource_type: str | None = Field(default=None, max_length=64, description="按资源类型筛选。")
    created_after: datetime | None = Field(default=None, description="仅返回此时间之后创建的任务。")
    created_before: datetime | None = Field(default=None, description="仅返回此时间之前创建的任务。")
    active_only: bool = Field(default=False, description="仅返回 queued 或 running 任务。")


class JobPage(BaseModel):
    items: list[JobStatusResponse] = Field(description="当前页任务。")
    next_cursor: str | None = Field(default=None, description="下一页不透明游标；没有下一页时为空。")
