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
    progress: float = Field(ge=0.0, le=1.0, description="任务完成进度，范围为 0 到 1。")
    message: str | None = Field(default=None, description="任务当前阶段或结果说明。")
    result: dict[str, Any] | None = Field(default=None, description="脱敏后的任务结果。")
    error: JobErrorResponse | None = Field(default=None, description="任务错误；无错误时为空。")
    created_at: datetime = Field(description="任务创建时间。")
    finished_at: datetime | None = Field(default=None, description="任务完成或取消时间。")
