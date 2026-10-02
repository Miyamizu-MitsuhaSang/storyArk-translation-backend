from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from tortoise import Tortoise
from tortoise.exceptions import IntegrityError

from translation_backend.app import models as model_module
from translation_backend.app.models import TranslationMemoryLibrary, User


def test_outdated_artifact_cannot_replace_current_active_artifact():
    async def scenario():
        assert hasattr(model_module, "TranslationMemoryIndexArtifact"), "TM index artifact model is not implemented"
        TranslationMemoryIndexArtifact = model_module.TranslationMemoryIndexArtifact
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(
                username="artifact-test",
                email="artifact-test@example.com",
                password_hash="hash",
                display_name="Artifact Test",
            )
            library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM")
            current = await TranslationMemoryIndexArtifact.create(
                library=library,
                content_version=1,
                format_version=1,
                status="active",
                storage_uri="sha256/current",
                checksum="a" * 64,
                vectorizer_version="v1",
            )
            stale = await TranslationMemoryIndexArtifact.create(
                library=library,
                content_version=1,
                format_version=2,
                status="ready",
                storage_uri="sha256/stale",
                checksum="b" * 64,
                vectorizer_version="v1",
            )
            await TranslationMemoryLibrary.filter(id=library.id).update(content_version=2)

            published = await stale.activate_if_current()
            await current.refresh_from_db()
            await stale.refresh_from_db()
            assert published is False
            assert current.status == "active"
            assert stale.status == "superseded"
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())


def test_current_artifact_replaces_previous_active_artifact_atomically():
    async def scenario():
        assert hasattr(model_module, "TranslationMemoryIndexArtifact"), "TM index artifact model is not implemented"
        TranslationMemoryIndexArtifact = model_module.TranslationMemoryIndexArtifact
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["translation_backend.app.models"]})
        await Tortoise.generate_schemas()
        try:
            user = await User.create(
                username="artifact-publish",
                email="artifact-publish@example.com",
                password_hash="hash",
                display_name="Artifact Publish",
            )
            library = await TranslationMemoryLibrary.create(scope="user", owner_user=user, name="TM")
            old = await TranslationMemoryIndexArtifact.create(
                library=library,
                content_version=1,
                format_version=1,
                status="active",
                storage_uri="sha256/old",
                checksum="a" * 64,
                vectorizer_version="v1",
            )
            with pytest.raises(IntegrityError):
                await TranslationMemoryIndexArtifact.create(
                    library=library,
                    content_version=1,
                    format_version=1,
                    status="ready",
                    storage_uri="sha256/duplicate",
                    checksum="c" * 64,
                    vectorizer_version="v1",
                )
            new = await TranslationMemoryIndexArtifact.create(
                library=library,
                content_version=1,
                format_version=2,
                status="ready",
                storage_uri="sha256/new",
                checksum="b" * 64,
                vectorizer_version="v2",
            )

            assert await new.activate_if_current() is True
            await old.refresh_from_db()
            await new.refresh_from_db()
            assert old.status == "superseded"
            assert new.status == "active"
            assert new.activated_at is not None
            assert await TranslationMemoryIndexArtifact.filter(library=library, status="active").count() == 1
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())
