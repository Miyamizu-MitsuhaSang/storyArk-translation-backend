from .celery_app import celery_app

# Import task modules so the registry is ready for producers and tests.
from . import health as _health  # noqa: F401,E402
from . import translation_memory as _translation_memory  # noqa: F401,E402

__all__ = ["celery_app"]
