from __future__ import annotations

from ....application.jobs.service import JobsService


_jobs_service = JobsService()


def get_jobs_service() -> JobsService:
    """Return the shared jobs application service for request handlers."""
    return _jobs_service


__all__ = ["get_jobs_service"]
