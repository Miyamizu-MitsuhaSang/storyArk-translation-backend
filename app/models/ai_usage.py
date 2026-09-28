from tortoise import fields

from app.models import TimestampedModel

AI_USAGE_STATUSES = ("succeeded", "failed", "timeout")


class AIUsageRecord(TimestampedModel):
    """Immutable provider-call usage snapshot used as the analytics source of truth."""

    user_id = fields.UUIDField(
        null=True,
        db_index=True,
        description="调用所属用户的快照 ID；用户删除后仍保留历史统计记录。",
    )
    project_id = fields.UUIDField(
        null=True,
        db_index=True,
        description="调用所属项目的快照 ID；为空表示用户级调用。",
    )
    api_key_id = fields.UUIDField(
        null=True,
        db_index=True,
        description="使用的用户级 API key 快照 ID；不建立会级联删除历史的外键。",
    )
    project_api_key_binding_id = fields.UUIDField(
        null=True,
        description="使用的项目 API key 绑定快照 ID；不建立会级联删除历史的外键。",
    )
    provider = fields.CharField(max_length=32, description="调用时的 AI provider 快照。")
    model = fields.CharField(max_length=120, description="调用时的模型标识。")
    provider_request_id: str | None = fields.CharField(
        max_length=255,
        null=True,
        description="provider 返回或适配器生成的请求唯一 ID，用于幂等去重。",
    )
    status = fields.CharField(
        max_length=16,
        choices=AI_USAGE_STATUSES,
        description="调用结果：succeeded 成功、failed 失败、timeout 超时。",
    )
    input_tokens = fields.BigIntField(default=0, description="本次调用的输入 token 数。")
    output_tokens = fields.BigIntField(default=0, description="本次调用的输出 token 数。")
    cached_input_tokens = fields.BigIntField(default=0, description="命中缓存的输入 token 数。")
    reasoning_tokens = fields.BigIntField(default=0, description="推理 token 数；provider 未提供时为 0。")
    total_tokens = fields.BigIntField(default=0, description="本次调用总 token 数。")
    cost = fields.DecimalField(
        max_digits=20,
        decimal_places=8,
        default=0,
        description="本次调用成本，使用定点十进制金额，不能为负数。",
    )
    currency = fields.CharField(max_length=3, default="USD", description="成本货币 ISO 4217 代码。")
    started_at = fields.DatetimeField(null=True, description="调用开始时间，使用 UTC。")
    completed_at = fields.DatetimeField(description="调用完成或失败时间，使用 UTC。")
    latency_ms = fields.IntField(null=True, description="调用耗时毫秒数。")
    error_code: str | None = fields.CharField(
        max_length=80,
        null=True,
        description="失败或超时的稳定错误码；成功时为空。",
    )

    class Meta:
        table = "ai_usage_records"
        indexes = [
            ("user_id", "completed_at"),
            ("project_id", "completed_at"),
            ("api_key_id", "completed_at"),
            ("project_api_key_binding_id", "completed_at"),
            ("provider", "model", "completed_at"),
            ("completed_at",),
        ]
        unique_together = (("provider", "provider_request_id"),)
