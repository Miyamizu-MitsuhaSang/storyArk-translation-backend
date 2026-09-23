from datetime import datetime

from tortoise import fields

from models.base import TimestampedModel


class User(TimestampedModel):
    username = fields.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        description="用户唯一登录名。",
    )
    email = fields.CharField(
        max_length=320,
        unique=True,
        db_index=True,
        description="用户唯一邮箱地址，可用于登录和通知。",
    )
    phone = fields.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        null=True,
        description="用户联系电话；为空表示用户未提供手机号。",
    )
    password_hash = fields.CharField(
        max_length=255,
        description="用户密码的安全哈希值，不得存储明文密码。",
    )
    display_name = fields.CharField(max_length=120, description="用户在平台中显示的名称。")
    is_active = fields.BooleanField(default=True, description="账号是否启用；停用账号不可登录。")
    is_superuser = fields.BooleanField(default=False, description="是否拥有平台级超级管理员权限。")
    last_login_at: datetime | None = fields.DatetimeField(
        null=True,
        description="用户最近一次成功登录的时间。",
    )

    class Meta:
        table = "auth_users"
        indexes = [("is_active",)]


class RefreshToken(TimestampedModel):
    """定时清理任务定期删除记录"""
    user = fields.ForeignKeyField(
        "models.User",
        related_name="refresh_tokens",
        on_delete=fields.CASCADE,
        description="令牌所属用户；用户删除时一并删除其令牌。",
    )
    token_hash = fields.CharField(
        max_length=128,
        unique=True,
        db_index=True,
        description="刷新令牌的哈希值，用于校验且不保存令牌明文。",
    )
    expires_at = fields.DatetimeField(description="刷新令牌失效时间。")
    revoked_at: datetime | None = fields.DatetimeField(
        null=True,
        description="令牌撤销时间；为空表示尚未主动撤销。",
    )
    user_agent: str | None = fields.TextField(
        null=True,
        description="签发令牌时客户端提供的 User-Agent 信息。",
    )
    ip_address: str | None = fields.CharField(
        max_length=45,
        null=True,
        description="签发令牌时客户端的 IP 地址，兼容 IPv4 和 IPv6。",
    )

    class Meta:
        table = "auth_refresh_tokens"
        indexes = [("user_id", "revoked_at"), ("expires_at",)]
