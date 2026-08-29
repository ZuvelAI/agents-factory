from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from agents_factory.modules.knowledge.ingestion.contracts import (
    ExtractedBlock,
    ExtractedDocument,
    FetchedSource,
    IngestionRejected,
)


class PdfExtractor:
    def __init__(self, *, max_pages: int = 500) -> None:
        self._max_pages = max_pages

    def extract(self, fetched: FetchedSource) -> ExtractedDocument:
        try:
            reader = PdfReader(BytesIO(fetched.content), strict=True)
        except (PdfReadError, ValueError):
            raise IngestionRejected("pdf_malformed") from None
        if reader.is_encrypted:
            raise IngestionRejected("pdf_encrypted")
        if len(reader.pages) > self._max_pages:
            raise IngestionRejected("pdf_page_limit_exceeded")
        blocks = tuple(
            ExtractedBlock(
                kind="TEXT",
                text=text,
                locator={**fetched.locator, "page": page_number},
            )
            for page_number, page in enumerate(reader.pages, start=1)
            if (text := (page.extract_text() or "").strip())
        )
        if not blocks:
            raise IngestionRejected("source_has_no_extractable_text")
        return ExtractedDocument(
            title=fetched.filename,
            blocks=blocks,
            source_digest=fetched.content_digest,
        )
