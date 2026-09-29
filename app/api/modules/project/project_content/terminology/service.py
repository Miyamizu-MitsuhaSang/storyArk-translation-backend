"""Compatibility exports for the terminology application service."""

from ......application.project.terminology.service import (
    TerminologyBaseNotFoundError,
    TerminologyConflictError,
    TerminologyError,
    TerminologyForbiddenError,
    TerminologyService,
    TerminologyTermNotFoundError,
)

__all__ = [
    "TerminologyBaseNotFoundError",
    "TerminologyConflictError",
    "TerminologyError",
    "TerminologyForbiddenError",
    "TerminologyService",
    "TerminologyTermNotFoundError",
]
