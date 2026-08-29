from __future__ import annotations

import hashlib

from agents_factory.modules.knowledge.ingestion.contracts import (
    FetchedSource,
    IngestionRejected,
    MAX_SOURCE_BYTES,
    SourceDescriptor,
    UploadedSourceReader,
)


class UploadedFileFetcher:
    def __init__(
        self, reader: UploadedSourceReader, *, max_bytes: int = MAX_SOURCE_BYTES
    ) -> None:
        self._reader = reader
        self._max_bytes = max_bytes

    async def fetch(self, source: SourceDescriptor) -> FetchedSource:
        upload_key = source.configuration.get("upload_key")
        if not isinstance(upload_key, str) or not upload_key:
            raise IngestionRejected("upload_key_required")
        content, metadata = await self._reader.read_upload(
            tenant_id=source.tenant_id,
            source_id=source.source_id,
            upload_key=upload_key,
        )
        if len(content) > self._max_bytes:
            raise IngestionRejected("source_too_large")
        filename = metadata.get("filename")
        media_type = metadata.get("media_type")
        if not isinstance(filename, str) or not isinstance(media_type, str):
            raise IngestionRejected("upload_metadata_invalid")
        return FetchedSource(
            descriptor=source,
            content=content,
            media_type=media_type,
            filename=filename,
            locator={"upload_key": upload_key},
            content_digest=hashlib.sha256(content).hexdigest(),
        )
