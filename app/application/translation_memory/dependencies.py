from .service import TranslationMemoryService

_service = TranslationMemoryService()


def get_translation_memory_service() -> TranslationMemoryService:
    return _service
