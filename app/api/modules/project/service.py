"""Compatibility exports for the legacy project service import path."""

from translation_backend.app.application.project.service import (
    ProjectConflictError,
    ProjectError,
    ProjectForbiddenError,
    ProjectNotFoundError,
    ProjectService,
)

__all__ = [
    "ProjectConflictError",
    "ProjectError",
    "ProjectForbiddenError",
    "ProjectNotFoundError",
    "ProjectService",
]
