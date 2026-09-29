from __future__ import annotations

from ...models import TranslationMemoryLibrary, User


def can_read_library(user: User, library: TranslationMemoryLibrary) -> bool:
    return library.scope == "user" and library.owner_user_id == user.id


def can_write_library(user: User, library: TranslationMemoryLibrary) -> bool:
    return can_read_library(user, library) and library.status != "archived"


def is_effective_for_user(user: User, library: TranslationMemoryLibrary) -> bool:
    return can_read_library(user, library) and library.status == "active"
