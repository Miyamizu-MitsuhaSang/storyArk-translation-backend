from translation_backend.app.core.config import database_settings

TORTOISE_ORM = {
    "connections": {"default": database_settings.database_url},
    "apps": {
        "models": {
            "models": ["translation_backend.models"],
            "default_connection": "default",
        }
    },
    "use_tz": True,
    "timezone": "UTC",
}
