from __future__ import annotations

from uuid import UUID

from ....models import TranslationTask, TranslationTaskFile


class TranslationTaskRepository:
    async def create(self, **values) -> TranslationTask:
        return await TranslationTask.create(**values)

    async def files(self, task_id: UUID) -> list[TranslationTaskFile]:
        return await TranslationTaskFile.filter(task_id=task_id).order_by("created_at")

    async def active_for_api_key(self, api_key_id: UUID) -> bool:
        return await TranslationTask.filter(api_key_id=api_key_id, status__in=["queued", "translating"]).exists()
