from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from uuid import UUID

from agents_factory.modules.knowledge.ingestion.contracts import IngestionRejected


_UPLOAD_KEY = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,199}")


class LocalPrivateSourceStore:
    """Local/private adapter; production object storage can replace this port."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def put(
        self,
        *,
        tenant_id: UUID,
        source_id: UUID,
        digest: str,
        content: bytes,
        media_type: str,
    ) -> str:
        _ = media_type
        relative = Path(str(tenant_id), str(source_id), "originals", digest)
        destination = self._resolve(relative)
        await asyncio.to_thread(self._write_once, destination, content)
        return relative.as_posix()

    async def read_upload(
        self, *, tenant_id: UUID, source_id: UUID, upload_key: str
    ) -> tuple[bytes, dict[str, object]]:
        if not _UPLOAD_KEY.fullmatch(upload_key):
            raise IngestionRejected("upload_key_invalid")
        relative = Path(str(tenant_id), str(source_id), "uploads", upload_key)
        path = self._resolve(relative)
        try:
            content = await asyncio.to_thread(path.read_bytes)
        except OSError:
            raise IngestionRejected("upload_unavailable") from None
        media_type_path = path.with_suffix(f"{path.suffix}.media-type")
        try:
            media_type = (
                await asyncio.to_thread(media_type_path.read_text, encoding="utf-8")
            ).strip()
        except OSError:
            raise IngestionRejected("upload_metadata_invalid") from None
        return content, {"filename": path.name, "media_type": media_type}

    async def put_upload(
        self,
        *,
        tenant_id: UUID,
        source_id: UUID,
        upload_key: str,
        content: bytes,
        media_type: str,
    ) -> None:
        if not _UPLOAD_KEY.fullmatch(upload_key):
            raise IngestionRejected("upload_key_invalid")
        relative = Path(str(tenant_id), str(source_id), "uploads", upload_key)
        path = self._resolve(relative)
        await asyncio.to_thread(self._write_once, path, content)
        await asyncio.to_thread(
            self._write_once,
            path.with_suffix(f"{path.suffix}.media-type"),
            media_type.encode("utf-8"),
        )

    def _resolve(self, relative: Path) -> Path:
        candidate = (self._root / relative).resolve()
        if not candidate.is_relative_to(self._root):
            raise IngestionRejected("storage_path_invalid")
        return candidate

    @staticmethod
    def _write_once(path: Path, content: bytes) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(content)
