from __future__ import annotations

import hashlib

from agents_factory.modules.knowledge.ingestion.contracts import (
    ExtractedBlock,
    ExtractedDocument,
    FetchedSource,
    IngestionRejected,
    SourceDescriptor,
)


class ManualFetcher:
    async def fetch(self, source: SourceDescriptor) -> FetchedSource:
        content = source.configuration.get("content")
        title = source.configuration.get("title", "Manual entry")
        if not isinstance(content, str) or not content.strip():
            raise IngestionRejected("manual_content_required")
        if not isinstance(title, str) or not title.strip():
            raise IngestionRejected("manual_title_required")
        encoded = content.encode("utf-8")
        return FetchedSource(
            descriptor=source,
            content=encoded,
            media_type="text/plain",
            filename=f"{title.strip()[:240]}.txt",
            locator={"entry": "manual"},
            content_digest=hashlib.sha256(encoded).hexdigest(),
        )


class ManualExtractor:
    def extract(self, fetched: FetchedSource) -> ExtractedDocument:
        try:
            text = fetched.content.decode("utf-8", errors="strict").strip()
        except UnicodeDecodeError:
            raise IngestionRejected("manual_encoding_unsupported") from None
        if not text:
            raise IngestionRejected("source_has_no_extractable_text")
        return ExtractedDocument(
            title=fetched.filename.removesuffix(".txt"),
            blocks=(ExtractedBlock(kind="TEXT", text=text, locator=fetched.locator),),
            source_digest=fetched.content_digest,
        )
