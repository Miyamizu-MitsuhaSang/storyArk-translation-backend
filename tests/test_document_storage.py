from pathlib import Path

import pytest

from translation_backend.app.infrastructure.document.storage import DocumentStorageError, LocalDocumentStorage


def test_local_document_storage_writes_atomically_and_rejects_traversal(tmp_path: Path) -> None:
    storage = LocalDocumentStorage(tmp_path)

    size, checksum = storage.put(storage_key="projects/p1/documents/d1/source.txt", content=b"hello")

    assert size == 5
    assert len(checksum) == 64
    assert storage.exists(storage_key="projects/p1/documents/d1/source.txt")
    with pytest.raises(DocumentStorageError):
        storage.exists(storage_key="../outside.txt")
