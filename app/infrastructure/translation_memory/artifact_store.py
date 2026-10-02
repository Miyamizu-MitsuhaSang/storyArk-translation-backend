"""Atomic, content-addressed storage for immutable TM index artifacts."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import BinaryIO, Protocol


class IndexArtifactStoreError(OSError):
    """Base error for retryable index artifact storage failures."""


class ArtifactTooLargeError(IndexArtifactStoreError):
    """Raised when an artifact exceeds the configured size budget."""


class InvalidArtifactURIError(ValueError):
    """Raised when a storage URI is not a generated content address."""


class IndexArtifactStore(Protocol):
    def put_atomic(self, payload: bytes) -> tuple[str, str]: ...
    def open(self, storage_uri: str) -> BinaryIO: ...
    def delete(self, storage_uri: str) -> None: ...
    def exists(self, storage_uri: str) -> bool: ...
    def checksum(self, storage_uri: str) -> str: ...


class LocalIndexArtifactStore:
    """Persist immutable artifacts below a fixed root using SHA-256 names."""

    _URI_PATTERN = re.compile(r"sha256/([0-9a-f]{64})\Z")

    def __init__(self, root: Path, *, max_artifact_bytes: int = 536_870_912) -> None:
        if max_artifact_bytes < 1:
            raise ValueError("max_artifact_bytes must be positive")
        self.root = Path(root).expanduser().resolve()
        self.max_artifact_bytes = max_artifact_bytes
        self._content_root = self.root / "sha256"

    def _path_for(self, storage_uri: str) -> Path:
        match = self._URI_PATTERN.fullmatch(storage_uri) if isinstance(storage_uri, str) else None
        if match is None:
            raise InvalidArtifactURIError("invalid artifact URI")
        return self._content_root / match.group(1)

    def put_atomic(self, payload: bytes) -> tuple[str, str]:
        if not isinstance(payload, bytes):
            raise TypeError("artifact payload must be bytes")
        if len(payload) > self.max_artifact_bytes:
            raise ArtifactTooLargeError("index artifact exceeds configured size limit")

        checksum = hashlib.sha256(payload).hexdigest()
        storage_uri = f"sha256/{checksum}"
        destination = self._path_for(storage_uri)
        self._content_root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".tm-index-", dir=self._content_root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as artifact:
                artifact.write(payload)
                artifact.flush()
                os.fsync(artifact.fileno())
            if destination.exists():
                if self.checksum(storage_uri) != checksum:
                    raise IndexArtifactStoreError("content-addressed artifact checksum mismatch")
                temporary.unlink()
            else:
                os.replace(temporary, destination)
            directory_fd = os.open(self._content_root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return storage_uri, checksum

    def open(self, storage_uri: str) -> BinaryIO:
        return self._path_for(storage_uri).open("rb")

    def delete(self, storage_uri: str) -> None:
        self._path_for(storage_uri).unlink(missing_ok=True)

    def exists(self, storage_uri: str) -> bool:
        return self._path_for(storage_uri).is_file()

    def checksum(self, storage_uri: str) -> str:
        digest = hashlib.sha256()
        with self.open(storage_uri) as artifact:
            for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
