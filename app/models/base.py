from uuid import UUID, uuid4

from tortoise import fields
from tortoise.models import Model


class TimestampedModel(Model):
    id: UUID = fields.UUIDField(
        primary_key=True,
        default=uuid4,
        description="记录的全局唯一标识符。",
    )
    created_at = fields.DatetimeField(
        auto_now_add=True,
        description="记录创建时间，使用 UTC 时区。",
    )
    updated_at = fields.DatetimeField(
        auto_now=True,
        description="记录最后更新时间，更新记录时自动刷新。",
    )

    class Meta:
        abstract = True # 表示 TimestampedModel 是一个抽象模型：它只用于被其他模型继承，ORM 不会为它单独创建数据库表
