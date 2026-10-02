from __future__ import annotations

import hashlib

import pytest

from translation_backend.app.infrastructure.translation_memory.artifact_store import (
    ArtifactTooLargeError,
    InvalidArtifactURIError,
    LocalIndexArtifactStore,
)


def test_local_store_addresses_content_and_verifies_checksum(tmp_path):
    store = LocalIndexArtifactStore(tmp_path)
    payload = b"persistent index payload"

    uri, checksum = store.put_atomic(payload)

    assert uri == f"sha256/{hashlib.sha256(payload).hexdigest()}"
    assert checksum == hashlib.sha256(payload).hexdigest()
    assert store.exists(uri)
    assert store.checksum(uri) == checksum
    with store.open(uri) as artifact:
        assert artifact.read() == payload
    assert store.put_atomic(payload) == (uri, checksum)


def test_local_store_rejects_oversized_artifacts(tmp_path):
    store = LocalIndexArtifactStore(tmp_path, max_artifact_bytes=3)

    with pytest.raises(ArtifactTooLargeError):
        store.put_atomic(b"four")

    assert list(tmp_path.rglob("*.artifact")) == []


@pytest.mark.parametrize("uri", ["../secret", "sha256/../../secret", "sha256/not-a-digest"])
def test_local_store_rejects_untrusted_artifact_paths(tmp_path, uri):
    store = LocalIndexArtifactStore(tmp_path)

    with pytest.raises(InvalidArtifactURIError):
        store.exists(uri)


def test_local_store_delete_is_idempotent(tmp_path):
    store = LocalIndexArtifactStore(tmp_path)
    uri, _ = store.put_atomic(b"payload")

    store.delete(uri)
    store.delete(uri)

    assert not store.exists(uri)
