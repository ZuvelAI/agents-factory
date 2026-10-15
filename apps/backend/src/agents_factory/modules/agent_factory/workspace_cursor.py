"""Opaque UUID cursors shared by bounded workspace reads."""

from base64 import b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from uuid import UUID
from datetime import datetime
import json
from .publication_service import publication_problem


def decode_cursor(cursor: str | None) -> UUID | None:
    if cursor is None:
        return None
    try:
        if len(cursor) > 64:
            raise ValueError()
        return UUID(b64decode(cursor, altchars=b"-_", validate=True).decode("ascii"))
    except (ValueError, UnicodeError, Base64Error):
        raise publication_problem(
            "invalid_workspace_cursor", "Cursor de lectura inválido.", 422
        ) from None


def encode_cursor(value: UUID) -> str:
    return urlsafe_b64encode(str(value).encode()).decode()


def encode_activity_cursor(at: datetime, id: UUID) -> str:
    return urlsafe_b64encode(
        json.dumps(
            {"at": at.isoformat(), "id": str(id)}, separators=(",", ":")
        ).encode()
    ).decode()


def decode_activity_cursor(cursor: str | None) -> tuple[datetime | None, UUID | None]:
    if cursor is None:
        return None, None
    try:
        if len(cursor) > 256:
            raise ValueError()
        value = json.loads(b64decode(cursor, altchars=b"-_", validate=True))
        if not isinstance(value, dict) or set(value) != {"at", "id"}:
            raise ValueError()
        if not isinstance(value["at"], str) or not isinstance(value["id"], str):
            raise ValueError()
        at = datetime.fromisoformat(value["at"])
        if at.tzinfo is None:
            raise ValueError()
        return at, UUID(value["id"])
    except (ValueError, TypeError, UnicodeError, Base64Error):
        raise publication_problem(
            "invalid_workspace_cursor", "Cursor de actividad inválido.", 422
        ) from None
