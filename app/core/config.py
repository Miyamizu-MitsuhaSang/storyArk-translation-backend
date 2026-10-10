from pathlib import Path

from urllib.parse import quote

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE_DIR = BASE_DIR / "env"


class AppSettings(BaseSettings):
    app_name: str = "translation-platform"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    log_file_path: Path | None = None
    # Redis 总开关和连接地址统一由应用配置管理；具体功能仍由各自开关控制。
    redis_enabled: bool = False
    redis_url: str = "redis://127.0.0.1:6379/2"
    tm_cache_enabled: bool = False
    tm_cache_ttl_seconds: int = 60
    tm_cache_namespace: str = "tm"
    tm_index_tasks_enabled: bool = False
    tm_index_storage_dir: Path = BASE_DIR / "var" / "tm-indexes"
    tm_index_max_artifact_bytes: int = Field(default=536_870_912, gt=0)
    tm_index_retention_count: int = Field(default=3, ge=1)
    tm_search_max_text_length: int = 4096
    tm_search_max_page_size: int = 50
    document_storage_dir: Path = BASE_DIR / "var" / "documents"
    document_max_file_bytes: int = Field(default=52_428_800, gt=0)
    document_purge_grace_seconds: int = Field(default=86_400, ge=0)
    document_tasks_enabled: bool = False
    # Redis 幂等锁开关；关闭或 Redis 不可用时回退到数据库唯一约束。
    idempotency_redis_enabled: bool = False
    # 幂等处理中锁租约，必须覆盖最长预期请求时间并允许过期恢复。
    idempotency_lock_ttl_seconds: int = Field(default=300, ge=1, le=3600)
    idempotency_redis_namespace: str = "idempotency"
    cat_tasks_enabled: bool = False
    translation_tasks_enabled: bool = False
    ai_provider_enabled: bool = False
    analytics_cache_enabled: bool = False
    analytics_cache_ttl_seconds: int = Field(default=60, ge=30, le=120)
    analytics_cache_namespace: str = "analytics"
    tm_semantic_model_zh_enabled: bool = False
    tm_semantic_model_en_enabled: bool = False
    tm_semantic_model_ja_enabled: bool = False
    # TODO Confirm the path of models
    tm_semantic_model_zh_path: Path = BASE_DIR / "models" / "semantic" / "bge-small-zh-v1.5"
    tm_semantic_model_en_path: Path = BASE_DIR / "models" / "semantic" / "bge-small-en-v1.5"
    tm_semantic_model_ja_path: Path = BASE_DIR / "models" / "semantic" / "ruri-base"
    # RAG 稀疏 MIPS 候选阈值。0 保证非负权重下不因启发式阈值漏掉低权重累积匹配。
    rag_candidate_threshold: float = Field(
        default=0.0,
        ge=0.0,
        validation_alias=AliasChoices(
            "RAG_CANDIDATE_THRESHOLD",
            "CANDIDATE_THRESHOLD",
        ),
    )
    model_config = SettingsConfigDict(
        # env_prefix="TRANSLATION_",
        env_file=ENV_FILE_DIR / ".env.app",
        extra="ignore"
    )


class SecuritySettings(BaseSettings):
    """Secrets and token policy shared by authentication and provider-key flows."""

    # Development fallback only; production must override AUTH_JWT_SECRET.
    auth_jwt_secret: str = "development-only-change-this-secret-key"
    auth_access_token_ttl_seconds: int = 900
    auth_refresh_token_ttl_days: int = 30
    auth_api_key_encryption_key: str | None = None
    auth_api_key_encryption_key_version: str = "v1"
    # API key secrets must only be submitted over TLS when enabled.
    auth_api_key_require_https: bool = True
    # Only enable when TLS is terminated by a trusted reverse proxy.
    auth_api_key_trust_forwarded_proto: bool = False

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_DIR / ".env.security",
        env_prefix="",
        extra="ignore",
    )


class DatabaseSettings(BaseSettings):
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "translation_platform"

    model_config = SettingsConfigDict(
        # env_prefix="TRANSLATION_",
        env_file=ENV_FILE_DIR / ".env.db",
        extra="ignore"
    )

    @property
    def database_url(self) -> str:
        password = quote(self.db_password, safe="")
        return (
            f"postgres://{self.db_user}:{password}@{self.db_host}:"
            f"{self.db_port}/{self.db_name}"
        )


class CelerySettings(BaseSettings):
    """Celery transport and serialization settings."""

    broker_url: str = "redis://127.0.0.1:6379/0"
    result_backend: str = "redis://127.0.0.1:6379/1"
    task_always_eager: bool = False
    task_eager_propagates: bool = True
    task_serializer: str = "json"
    result_serializer: str = "json"
    accept_content: list[str] = ["json"]
    timezone: str = "UTC"
    enable_utc: bool = True

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_DIR / ".env.app",
        env_prefix="CELERY_",
        extra="ignore",
    )


app_settings = AppSettings()
security_settings = SecuritySettings()
database_settings = DatabaseSettings()
celery_settings = CelerySettings()

if __name__ == '__main__':
    print(ENV_FILE_DIR)
