from .....application.project.settings.service import ProjectSettingsService


_project_settings_service = ProjectSettingsService()


def get_project_settings_service() -> ProjectSettingsService:
    return _project_settings_service


__all__ = ["get_project_settings_service"]
