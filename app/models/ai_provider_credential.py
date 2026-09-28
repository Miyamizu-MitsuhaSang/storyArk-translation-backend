from datetime import datetime

from tortoise import fields

from .base import TimestampedModel

AI_PROVIDER_TYPES = (
    "openai",
    "anthropic",
    "google",
    "qwen",
    "deepseek",
    "kimi",
    "doubao",
    "zhipu",
    "minimax",
    "mistral",
    "groq",
    "custom",
)


class AIProviderCredential(TimestampedModel):
    user = fields.ForeignKeyField(
        "models.User",
        related_name="ai_provider_credentials",
        on_delete=fields.CASCADE,
        description="凭据所属用户；用户删除时一并删除凭据。",
    )
    provider = fields.CharField(
        max_length=32,
        choices=AI_PROVIDER_TYPES,
        description="AI 服务提供方，例如 OpenAI（ChatGPT）、Anthropic（Claude）、Qwen 或自定义服务。",
    )
    label: str | None = fields.CharField(
        max_length=120,
        null=True,
        description="用户自定义的凭据名称，便于区分同一提供方的多把 key。",
    )
    api_key_ciphertext = fields.TextField(
        description="经应用层加密后的 API key 密文，建议以 Base64 编码保存；不得写入明文。",
    )
    encryption_nonce = fields.CharField(
        max_length=64,
        description="加密 API key 使用的唯一 nonce/IV，建议以 Base64 编码保存。",
    )
    encryption_key_version = fields.CharField(
        max_length=64,
        description="数据库外部加密密钥的版本标识，用于密钥轮换和解密路由。",
    )
    key_hint: str | None = fields.CharField(
        max_length=8,
        null=True,
        description="API key 末尾少量字符的脱敏提示；不得保存完整 key。",
    )
    key_prefix: str | None = fields.CharField(
        max_length=32,
        null=True,
        description="API key 开头的非敏感短前缀，用于展示脱敏标识；不得保存完整 key。",
    )
    is_active = fields.BooleanField(default=True, description="该凭据是否可供后端模型调用使用。")
    last_used_at: datetime | None = fields.DatetimeField(
        null=True,
        description="该凭据最近一次被后端调用的时间。",
    )

    class Meta:
        table = "ai_provider_credentials"
        indexes = [("user_id", "provider"), ("user_id", "is_active")]
