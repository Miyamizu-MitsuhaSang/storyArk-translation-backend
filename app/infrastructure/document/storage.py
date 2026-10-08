from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import BinaryIO


class DocumentStorageError(Exception):
    """Raised when a document cannot be safely stored or removed."""


class LocalDocumentStorage:
    """Store documents below a configured root using server-generated relative keys."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, *, storage_key: str, content: bytes) -> tuple[int, str]:
        path = self._path_for(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise DocumentStorageError("文档文件写入失败") from exc
        return len(content), hashlib.sha256(content).hexdigest()

    def delete(self, *, storage_key: str) -> None:
        try:
            self._path_for(storage_key).unlink(missing_ok=True)
        except OSError as exc:
            raise DocumentStorageError("文档文件删除失败") from exc

    def exists(self, *, storage_key: str) -> bool:
        return self._path_for(storage_key).is_file()

    def open(self, *, storage_key: str) -> BinaryIO:
        try:
            return self._path_for(storage_key).open("rb")
        except OSError as exc:
            raise DocumentStorageError("文档文件读取失败") from exc

    def _path_for(self, storage_key: str) -> Path:
        if not storage_key or "\\" in storage_key:
            raise DocumentStorageError("无效的文档存储标识")
        candidate = (self.root / storage_key).resolve()
        root = self.root.resolve()
        if candidate != root and root not in candidate.parents:
            raise DocumentStorageError("无效的文档存储标识")
        return candidate
