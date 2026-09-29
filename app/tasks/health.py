from .celery_app import celery_app


@celery_app.task(name="translation_backend.app.tasks.health.ping")
def ping(value: str = "pong") -> str:
    """Return a value to verify that the Celery worker is responsive."""

    return value
