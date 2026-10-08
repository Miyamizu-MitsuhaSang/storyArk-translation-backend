from pathlib import Path

from translation_backend.app.core.config import AppSettings, DatabaseSettings


def test_auth_http_dependencies_are_owned_by_api_layer() -> None:
    from translation_backend.app.api import shared
    from translation_backend.app.api.shared import dependencies
    from translation_backend.app.core import security

    assert dependencies.get_current_user.__module__ == dependencies.__name__
    assert dependencies.get_auth_service.__module__ == dependencies.__name__
    assert dependencies.oauth2_scheme is not None
    assert not hasattr(security, "get_current_user")
    assert not hasattr(security, "get_auth_service")
    assert not hasattr(security, "oauth2_scheme")


def test_user_api_key_service_factory_is_owned_by_api_key_module() -> None:
    from translation_backend.app.api.modules.auth.api_key import dependencies
    from translation_backend.app.core import security

    service = dependencies.get_api_key_service()

    assert service.__class__.__name__ == "ApiKeyService"
    assert dependencies.get_api_key_service.__module__ == dependencies.__name__
    assert not hasattr(security, "get_api_key_service")


def test_app_settings_reads_shared_redis_configuration_from_env_app(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.app"
    env_file.write_text(
        "REDIS_ENABLED=true\n"
        "REDIS_URL=redis://redis.internal:6379/7\n",
        encoding="utf-8",
    )

    settings = AppSettings(_env_file=env_file)

    assert settings.redis_enabled is True
    assert settings.redis_url == "redis://redis.internal:6379/7"


def test_database_settings_does_not_expose_redis_configuration(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.db"
    env_file.write_text(
        "DB_USER=postgres\n"
        "REDIS_ENABLED=true\n"
        "REDIS_URL=redis://redis.internal:6379/7\n",
        encoding="utf-8",
    )

    settings = DatabaseSettings(_env_file=env_file)

    assert not hasattr(settings, "redis_enabled")
    assert not hasattr(settings, "redis_url")


def test_app_settings_reads_candidate_threshold_from_env_app(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.app"
    env_file.write_text("CANDIDATE_THRESHOLD=0.6\n", encoding="utf-8")

    settings = AppSettings(_env_file=env_file)

    assert settings.rag_candidate_threshold == 0.6


def test_app_settings_prefers_rag_candidate_threshold_name(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.app"
    env_file.write_text(
        "CANDIDATE_THRESHOLD=0.6\nRAG_CANDIDATE_THRESHOLD=0.2\n",
        encoding="utf-8",
    )

    settings = AppSettings(_env_file=env_file)

    assert settings.rag_candidate_threshold == 0.2


def test_app_settings_configures_translation_memory_index_storage(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.app"
    env_file.write_text(
        "TM_INDEX_STORAGE_DIR=/var/lib/translation-platform/tm-indexes\n"
        "TM_INDEX_MAX_ARTIFACT_BYTES=2097152\n"
        "TM_INDEX_RETENTION_COUNT=7\n",
        encoding="utf-8",
    )

    settings = AppSettings(_env_file=env_file)

    assert settings.tm_index_storage_dir == Path("/var/lib/translation-platform/tm-indexes")
    assert settings.tm_index_max_artifact_bytes == 2097152
    assert settings.tm_index_retention_count == 7


def test_semantic_model_switches_default_off(monkeypatch) -> None:
    for language in ("ZH", "EN", "JA"):
        monkeypatch.delenv(f"TM_SEMANTIC_MODEL_{language}_ENABLED", raising=False)

    settings = AppSettings(_env_file=None)

    assert settings.tm_semantic_model_zh_enabled is False
    assert settings.tm_semantic_model_en_enabled is False
    assert settings.tm_semantic_model_ja_enabled is False


def test_semantic_model_switches_and_local_paths_are_independent(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.app"
    env_file.write_text(
        "TM_SEMANTIC_MODEL_ZH_ENABLED=true\n"
        "TM_SEMANTIC_MODEL_ZH_PATH=/models/zh\n"
        "TM_SEMANTIC_MODEL_EN_ENABLED=false\n"
        "TM_SEMANTIC_MODEL_EN_PATH=/models/en\n"
        "TM_SEMANTIC_MODEL_JA_ENABLED=true\n"
        "TM_SEMANTIC_MODEL_JA_PATH=/models/ja\n",
        encoding="utf-8",
    )

    settings = AppSettings(_env_file=env_file)

    assert settings.tm_semantic_model_zh_enabled is True
    assert settings.tm_semantic_model_en_enabled is False
    assert settings.tm_semantic_model_ja_enabled is True
    assert settings.tm_semantic_model_zh_path == Path("/models/zh")
    assert settings.tm_semantic_model_en_path == Path("/models/en")
    assert settings.tm_semantic_model_ja_path == Path("/models/ja")
