from __future__ import annotations

import hashlib
import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


_PARAGRAPH_BREAK = re.compile(r"\n\s*\n+")
_SPANISH_MARKERS = frozenset(
    {"el", "la", "los", "las", "de", "para", "con", "servicio", "política"}
)


class KnowledgeChunkDraft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: UUID
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=4_000)
    content_digest: str = Field(pattern=r"[0-9a-f]{64}")
    locale: str = Field(pattern=r"[a-z]{2}(?:-[A-Z]{2})?")
    locator: dict[str, object]


class KnowledgeChunker:
    def __init__(self, *, max_characters: int = 1_600, overlap: int = 160) -> None:
        if not 200 <= max_characters <= 4_000:
            raise ValueError("chunk size must be between 200 and 4000 characters")
        if not 0 <= overlap < max_characters // 2:
            raise ValueError("chunk overlap must be less than half the chunk size")
        self._max_characters = max_characters
        self._overlap = overlap

    def chunk(
        self,
        *,
        document_id: UUID,
        text: str,
        locator: dict[str, object],
    ) -> tuple[KnowledgeChunkDraft, ...]:
        normalized = _normalize_text(text)
        if not normalized:
            return ()
        segments = self._segments(normalized)
        return tuple(
            KnowledgeChunkDraft(
                document_id=document_id,
                chunk_index=index,
                text=segment,
                content_digest=_chunk_digest(document_id, index, segment),
                locale=_detect_locale(segment),
                locator={**locator, "chunk": index},
            )
            for index, segment in enumerate(segments)
        )

    def _segments(self, text: str) -> tuple[str, ...]:
        paragraphs = [value.strip() for value in _PARAGRAPH_BREAK.split(text)]
        segments: list[str] = []
        current = ""
        for paragraph in paragraphs:
            if not paragraph:
                continue
            if len(paragraph) > self._max_characters:
                if current:
                    segments.append(current)
                    current = ""
                segments.extend(self._window(paragraph))
                continue
            candidate = paragraph if not current else f"{current}\n\n{paragraph}"
            if len(candidate) <= self._max_characters:
                current = candidate
                continue
            segments.append(current)
            prefix = current[-self._overlap :].lstrip() if self._overlap else ""
            current = f"{prefix}\n\n{paragraph}" if prefix else paragraph
        if current:
            segments.append(current)
        return tuple(segment.strip() for segment in segments if segment.strip())

    def _window(self, paragraph: str) -> list[str]:
        stride = self._max_characters - self._overlap
        return [
            paragraph[start : start + self._max_characters].strip()
            for start in range(0, len(paragraph), stride)
            if paragraph[start : start + self._max_characters].strip()
        ]


def _normalize_text(value: str) -> str:
    normalized: list[str] = []
    pending_break = False
    for raw_line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = " ".join(raw_line.split())
        if line:
            if pending_break and normalized:
                normalized.append("")
            normalized.append(line)
            pending_break = False
        elif normalized:
            pending_break = True
    return "\n".join(normalized).strip()


def _chunk_digest(document_id: UUID, index: int, text: str) -> str:
    payload = f"v1\n{document_id}\n{index}\n{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _detect_locale(text: str) -> str:
    words = set(re.findall(r"[a-záéíóúñü]+", text.lower()))
    return "es-CO" if len(words & _SPANISH_MARKERS) >= 2 else "en-US"
