"""Dependencies for project version routes."""

from .....application.project.version.service import VersionService


_version_service = VersionService()


def get_version_service() -> VersionService:
    return _version_service


__all__ = ["get_version_service"]
