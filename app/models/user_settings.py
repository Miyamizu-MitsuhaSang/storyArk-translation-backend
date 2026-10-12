from __future__ import annotations

from tortoise import fields

from .base import TimestampedModel


class AppearanceSettings(TimestampedModel):
    user = fields.OneToOneField(
        "models.User",
        related_name="appearance_settings",
        on_delete=fields.CASCADE,
        description="外观设置所属用户；用户删除时级联删除。",
    )
    theme = fields.CharField(
        max_length=16,
        choices=("light", "dark", "system"),
        default="system",
        description="界面主题：light、dark 或 system。",
    )
    revision = fields.IntField(default=1, description="外观设置的乐观并发版本。")

    class Meta:
        table = "auth_appearance_settings"
        indexes = [("user_id", "updated_at")]


class UserPreferences(TimestampedModel):
    user = fields.OneToOneField(
        "models.User",
        related_name="user_preferences",
        on_delete=fields.CASCADE,
        description="用户偏好所属用户；用户删除时级联删除。",
    )
    locale = fields.CharField(
        max_length=35,
        default="zh-CN",
        description="网站界面语言代码，不表示翻译任务的源语言或目标语言。",
    )
    allow_member_search = fields.BooleanField(
        default=False,
        description="是否允许项目管理员通过用户名、邮箱或显示名称搜索到当前用户。",
    )
    revision = fields.IntField(default=1, description="用户偏好的乐观并发版本。")

    class Meta:
        table = "auth_user_preferences"
        indexes = [("user_id", "updated_at")]


__all__ = ["AppearanceSettings", "UserPreferences"]
