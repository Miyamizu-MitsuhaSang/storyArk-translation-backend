from .celery_app import celery_app

# Import task modules so the registry is ready for producers and tests.
from . import health as _health  # noqa: F401,E402
from . import documents as _documents  # noqa: F401,E402
from . import cat as _cat  # noqa: F401,E402
from . import translation_memory as _translation_memory  # noqa: F401,E402
from . import translation_memory_maintenance as _translation_memory_maintenance  # noqa: F401,E402
from . import terminology as _terminology  # noqa: F401,E402
from . import translation_tasks as _translation_tasks  # noqa: F401,E402

__all__ = ["celery_app"]
