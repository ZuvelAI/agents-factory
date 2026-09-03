from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
from pathlib import Path
from uuid import UUID

from agents_factory.modules.media.contracts import MediaError, MAX_BYTES
from agents_factory.modules.secrets.redaction import ResolvedSecret


class LocalPrivateMediaStore:
    """Private volume adapter, not a public directory or an HTTP file server."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, tenant_id: UUID, media_id: UUID, digest: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise MediaError("media_path_invalid")
        path = self.root / str(tenant_id) / str(media_id) / digest
        if any(
            parent.is_symlink()
            for parent in (path, *path.parents)
            if parent != self.root.parent
        ):
            raise MediaError("media_path_invalid")
        if not path.resolve().is_relative_to(self.root):
            raise MediaError("media_path_invalid")
        return path

    async def put(
        self, *, tenant_id: UUID, media_id: UUID, content: bytes
    ) -> tuple[str, str]:
        digest = hashlib.sha256(content).hexdigest()
        path = self._path(tenant_id, media_id, digest)
        if not content or len(content) > MAX_BYTES:
            raise MediaError("media_size_invalid")
        await asyncio.to_thread(self._write, path, content)
        return path.relative_to(self.root).as_posix(), digest

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
        except FileExistsError:
            if path.read_bytes() != content:
                raise MediaError("media_storage_conflict") from None
            return
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

    async def read(self, *, tenant_id: UUID, media_id: UUID, digest: str) -> bytes:
        path = self._path(tenant_id, media_id, digest)
        try:
            value = await asyncio.to_thread(path.read_bytes)
        except OSError:
            raise MediaError("media_unavailable") from None
        if len(value) > MAX_BYTES or hashlib.sha256(value).hexdigest() != digest:
            raise MediaError("media_integrity_failed")
        return value

    async def delete(self, *, tenant_id: UUID, media_id: UUID, digest: str) -> None:
        await asyncio.to_thread(
            self._path(tenant_id, media_id, digest).unlink, missing_ok=True
        )

    async def delete_object(self, *, tenant_id: UUID, media_id: UUID) -> None:
        # The exact tenant/object prefix also covers a crash after a file write
        # but before its digest was persisted. Never traverse arbitrary paths.
        directory = self._path(tenant_id, media_id, "0" * 64).parent
        if not directory.exists():
            return
        for item in directory.iterdir():
            path = self._path(tenant_id, media_id, item.name)
            if not path.is_file():
                raise MediaError("media_path_invalid")
            await asyncio.to_thread(path.unlink, missing_ok=True)


class MediaAccessSigner:
    """Short-lived grant; the authenticated backend must also recheck the row."""

    def __init__(self, signing_material: ResolvedSecret) -> None:
        if len(signing_material.reveal()) < 32:
            raise ValueError("media signing material must be at least 32 bytes")
        self._material = signing_material

    def sign(
        self, *, tenant_id: UUID, customer_ref: str, media_id: UUID, expires: int
    ) -> str:
        import json

        payload = json.dumps(
            [str(tenant_id), customer_ref, str(media_id), expires],
            separators=(",", ":"),
        )
        return hmac.new(
            self._material.reveal(), payload.encode(), hashlib.sha256
        ).hexdigest()

    def verify(
        self,
        *,
        tenant_id: UUID,
        customer_ref: str,
        media_id: UUID,
        expires: int,
        signature: str,
        now: int,
    ) -> None:
        if not now < expires <= now + 300 or not hmac.compare_digest(
            signature,
            self.sign(
                tenant_id=tenant_id,
                customer_ref=customer_ref,
                media_id=media_id,
                expires=expires,
            ),
        ):
            raise MediaError("media_access_denied")
