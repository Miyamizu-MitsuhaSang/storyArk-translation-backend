from pathlib import Path

from urllib.parse import quote
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE_DIR = BASE_DIR / "env"


class AppSettings(BaseSettings):
    app_name: str = "translation-platform"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"
    log_file_path: Path | None = None
    tm_cache_enabled: bool = False
    tm_cache_ttl_seconds: int = 60
    tm_cache_namespace: str = "tm"
    tm_index_tasks_enabled: bool = False
    tm_search_max_text_length: int = 4096
    tm_search_max_page_size: int = 50
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

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_DIR / ".env.security",
        env_prefix="",
        extra="ignore",
    )


class DatabaseSettings(BaseSettings):
    redis_launch: bool = False
    redis_url: str = "redis://127.0.0.1:6379/2"

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
