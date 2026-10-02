from celery import Celery

from ..core.config import celery_settings


celery_app = Celery(
    "translation_platform",
    include=("translation_backend.app.tasks.health", "translation_backend.app.tasks.translation_memory"),
)
celery_app.conf.update(
    broker_url=celery_settings.broker_url,
    result_backend=celery_settings.result_backend,
    task_always_eager=celery_settings.task_always_eager,
    task_eager_propagates=celery_settings.task_eager_propagates,
    task_serializer=celery_settings.task_serializer,
    result_serializer=celery_settings.result_serializer,
    accept_content=celery_settings.accept_content,
    timezone=celery_settings.timezone,
    enable_utc=celery_settings.enable_utc,
    beat_schedule={
        "reclaim-expired-tm-index-jobs": {
            "task": "translation_memory.reclaim_expired_index_jobs",
            "schedule": 60.0,
        },
    },
)
celery_app.autodiscover_tasks(
    packages=("translation_backend.app.tasks",),
    related_name="health",
)
