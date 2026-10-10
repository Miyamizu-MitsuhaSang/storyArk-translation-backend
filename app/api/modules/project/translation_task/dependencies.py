from .....application.project.translation_task.service import TranslationTaskService

_translation_task_service = TranslationTaskService()


def get_translation_task_service() -> TranslationTaskService:
    return _translation_task_service
