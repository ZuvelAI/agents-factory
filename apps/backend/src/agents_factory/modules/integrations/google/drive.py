from __future__ import annotations

import base64
import binascii
import json
import hashlib
from typing import ClassVar
from urllib.parse import quote
from uuid import uuid4

from pydantic import Field

from agents_factory.modules.integrations.contracts import ConnectorRequest
from agents_factory.modules.integrations.google.auth import DRIVE_FILE
from agents_factory.modules.integrations.google.base import (
    GoogleConnector,
    GoogleFailure,
    InputModel,
    ResourceId,
    manifest,
    response_string,
)


ALLOWED_MIMES = frozenset(
    {
        "application/pdf",
        "text/plain",
        "text/csv",
        "image/jpeg",
        "image/png",
        "image/webp",
        "video/mp4",
    }
)
EXPORT_MIMES = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
}


class ReadFile(InputModel):
    file_id: ResourceId


class StoreFile(InputModel):
    name: str = Field(min_length=1, max_length=200, pattern=r"^[^/\\\r\n]+$")
    mime_type: str
    content_base64: str = Field(min_length=1, max_length=28_000_000)


class DriveResource(InputModel):
    evidence_folder_id: ResourceId
    readable_file_ids: frozenset[ResourceId] = frozenset()
    max_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=20 * 1024 * 1024)


class GoogleDriveConnector(GoogleConnector[DriveResource]):
    manifest = manifest(
        "google_drive",
        "Google Drive",
        ("drive.read_file", "drive.store_evidence"),
        "drive.GoogleDriveConnector",
    )
    operation_scopes: ClassVar[dict[str, frozenset[str]]] = {
        "drive.read_file": frozenset({DRIVE_FILE}),
        "drive.store_evidence": frozenset({DRIVE_FILE}),
    }
    write_operations = frozenset({"drive.store_evidence"})

    async def _execute(self, request: ConnectorRequest) -> dict[str, object]:
        if request.operation == "drive.read_file":
            args = ReadFile.model_validate(request.arguments)
            if args.file_id not in self.resource.readable_file_ids:
                raise GoogleFailure("resource_not_allowed")
            root = "https://www.googleapis.com/drive/v3/files/" + quote(
                args.file_id, safe=""
            )
            metadata = await self.http.json(
                "GET",
                root,
                access=self.access,
                params={"fields": "id,name,mimeType,size,modifiedTime,trashed"},
            )
            if metadata.get("trashed") is not False:
                raise GoogleFailure("not_found")
            mime = response_string(metadata, "mimeType")
            export = EXPORT_MIMES.get(mime)
            if export is None and mime not in ALLOWED_MIMES:
                raise GoogleFailure("mime_not_allowed")
            try:
                size = int(str(metadata.get("size", "0")))
            except ValueError:
                raise GoogleFailure("invalid_response") from None
            if size < 0 or size > self.resource.max_bytes:
                raise GoogleFailure("file_too_large")
            raw = await self.http.request(
                "GET",
                root + ("/export" if export else ""),
                access=self.access,
                params={"mimeType": export} if export else {"alt": "media"},
                limit=self.resource.max_bytes,
            )
            return {
                "file_id": args.file_id,
                "name": response_string(metadata, "name"),
                "mime_type": export or mime,
                "modified_time": metadata.get("modifiedTime"),
                "content_base64": base64.b64encode(raw).decode(),
                "size": len(raw),
            }
        upload = StoreFile.model_validate(request.arguments)
        if upload.mime_type not in ALLOWED_MIMES:
            raise GoogleFailure("mime_not_allowed")
        try:
            raw = base64.b64decode(upload.content_base64, validate=True)
        except (ValueError, binascii.Error):
            raise GoogleFailure("invalid_arguments") from None
        if not raw or len(raw) > self.resource.max_bytes:
            raise GoogleFailure("file_too_large")
        boundary = "af_" + uuid4().hex
        action_id = hashlib.sha256(
            f"{request.tenant_id}:{request.binding_id}:{request.idempotency_key}".encode()
        ).hexdigest()
        metadata_bytes = json.dumps(
            {
                "name": upload.name,
                "parents": [self.resource.evidence_folder_id],
                "appProperties": {"action_id": action_id},
            }
        ).encode()
        content = (
            b"--"
            + boundary.encode()
            + b"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            + metadata_bytes
            + b"\r\n--"
            + boundary.encode()
            + b"\r\nContent-Type: "
            + upload.mime_type.encode()
            + b"\r\n\r\n"
            + raw
            + b"\r\n--"
            + boundary.encode()
            + b"--\r\n"
        )
        payload = await self.http.json(
            "POST",
            "https://www.googleapis.com/upload/drive/v3/files",
            access=self.access,
            params={"uploadType": "multipart", "fields": "id,name,mimeType"},
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            content=content,
            write=True,
        )
        return {
            "file_id": response_string(payload, "id", write=True),
            "name": upload.name,
            "mime_type": upload.mime_type,
        }
