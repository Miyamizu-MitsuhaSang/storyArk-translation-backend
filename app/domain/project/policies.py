"""Pure project authorization and invariant policies."""

from __future__ import annotations

from ..shared.errors import DomainError


MANAGER_ROLES = frozenset({"owner", "manager"})
PROJECT_ROLES = frozenset({"owner", "manager", "translator", "reviewer", "viewer"})


class ProjectPolicy:
    @staticmethod
    def can_view(role: str) -> bool:
        return role in PROJECT_ROLES

    @staticmethod
    def can_manage(role: str) -> bool:
        return role in MANAGER_ROLES

    @staticmethod
    def ensure_manager(role: str) -> None:
        if not ProjectPolicy.can_manage(role):
            raise DomainError(
                "当前角色没有项目管理权限",
                code="PROJECT_FORBIDDEN",
            )


class OwnerPolicy:
    @staticmethod
    def ensure_not_last_owner(
        current_role: str,
        requested_role: str | None,
        owner_count: int,
    ) -> None:
        is_demoting = current_role == "owner" and requested_role != "owner"
        if is_demoting and owner_count <= 1:
            raise DomainError(
                "不能移除项目最后一个 owner",
                code="PROJECT_LAST_OWNER",
            )


class LanguagePairPolicy:
    @staticmethod
    def ensure_default_pair_exists(pair_exists: bool) -> None:
        if not pair_exists:
            raise DomainError(
                "默认语言对必须先添加到项目",
                code="PROJECT_DEFAULT_LANGUAGE_PAIR",
            )
