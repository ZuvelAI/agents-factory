from __future__ import annotations

import hashlib

from agents_factory.modules.knowledge.ingestion.contracts import (
    DriveFileClient,
    FetchedSource,
    IngestionRejected,
    MAX_SOURCE_BYTES,
    SourceDescriptor,
)


class GoogleDriveFetcher:
    def __init__(
        self, client: DriveFileClient, *, max_bytes: int = MAX_SOURCE_BYTES
    ) -> None:
        self._client = client
        self._max_bytes = max_bytes

    async def fetch(self, source: SourceDescriptor) -> FetchedSource:
        file_id = source.configuration.get("file_id")
        if not isinstance(file_id, str) or not file_id:
            raise IngestionRejected("drive_file_id_required")
        content, metadata = await self._client.download(file_id)
        if len(content) > self._max_bytes:
            raise IngestionRejected("source_too_large")
        name = metadata.get("name")
        media_type = metadata.get("mime_type")
        modified_time = metadata.get("modified_time")
        if not isinstance(name, str) or not isinstance(media_type, str):
            raise IngestionRejected("drive_metadata_invalid")
        return FetchedSource(
            descriptor=source,
            content=content,
            media_type=media_type,
            filename=name,
            locator={
                "drive_file_id": file_id,
                "modified_time": modified_time,
            },
            content_digest=hashlib.sha256(content).hexdigest(),
        )
