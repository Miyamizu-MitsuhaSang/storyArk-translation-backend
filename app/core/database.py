from .config import database_settings

TORTOISE_ORM = {
    "connections": {"default": database_settings.database_url},
    "apps": {
        "models": {
            "models": ["app.models"],
            "default_connection": "default",
        }
    },
    "use_tz": True,
    "timezone": "UTC",
}
