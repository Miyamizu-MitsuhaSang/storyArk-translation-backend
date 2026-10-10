from .....application.project.translation_settings.service import TranslationSettingsService


_translation_settings_service = TranslationSettingsService()


def get_translation_settings_service() -> TranslationSettingsService:
    return _translation_settings_service


__all__ = ["get_translation_settings_service"]
