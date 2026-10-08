from .....application.translation_memory.service import TranslationMemoryService


def get_translation_memory_service() -> TranslationMemoryService:
    """Return the user-scoped translation-memory application service."""
    return TranslationMemoryService()

__all__ = ["get_translation_memory_service"]
