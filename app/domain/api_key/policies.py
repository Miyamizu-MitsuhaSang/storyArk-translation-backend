"""Pure API-key ownership, status, and role policies."""

from __future__ import annotations

from ..project.policies import ProjectPolicy
from ..shared.errors import DomainError


class ApiKeyPolicy:
    @staticmethod
    def ensure_bindable(*, is_owned: bool, is_active: bool) -> None:
        if not is_owned or not is_active:
            raise DomainError(
                "API key 不存在或不可用",
                code="API_KEY_NOT_BINDABLE",
            )

    @staticmethod
    def ensure_manager(role: str) -> None:
        try:
            ProjectPolicy.ensure_manager(role)
        except DomainError as exc:
            raise DomainError(
                "当前角色没有项目 API key 管理权限",
                code="PROJECT_API_KEY_FORBIDDEN",
            ) from exc
