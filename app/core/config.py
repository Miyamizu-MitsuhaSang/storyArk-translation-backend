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
    auth_jwt_secret: str = "development-only-change-this-secret-key"
    auth_access_token_ttl_seconds: int = 900
    auth_refresh_token_ttl_days: int = 30
    model_config = SettingsConfigDict(
        # env_prefix="TRANSLATION_",
        env_file=ENV_FILE_DIR / ".env.app",
        extra="ignore"
    )


class DatabaseSettings(BaseSettings):
    redis_launch: bool = False

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


app_settings = AppSettings()
database_settings = DatabaseSettings()

if __name__ == '__main__':
    print(ENV_FILE_DIR)
