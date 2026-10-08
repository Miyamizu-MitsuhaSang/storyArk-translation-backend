"""Project-scoped translation-memory HTTP dependencies."""

from ......application.translation_memory.service import TranslationMemoryService


def get_translation_memory_service() -> TranslationMemoryService:
    return TranslationMemoryService()

__all__ = ["get_translation_memory_service"]
