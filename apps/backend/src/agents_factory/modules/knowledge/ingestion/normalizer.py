from __future__ import annotations

import hashlib
import json
from typing import cast

from agents_factory.modules.knowledge.ingestion.contracts import (
    ExtractedDocument,
    IngestionRejected,
    NormalizedKnowledge,
    ProposedDocument,
    ProposedFact,
    SourceDescriptor,
)
from agents_factory.modules.knowledge.models import (
    CriticalFactKind,
    KnowledgeDocumentCategory,
)


_FACT_KINDS = frozenset(
    {
        "BUSINESS_HOURS",
        "LOCATION",
        "SERVICE",
        "PRICE",
        "CONTACT",
        "BOOKING_RULE",
        "APPROVAL_CONTACT",
    }
)
_DOCUMENT_CATEGORIES = frozenset(
    {
        "POLICY",
        "MANUAL",
        "FAQ",
        "CATALOG_DESCRIPTION",
        "PROCEDURE",
        "DOCUMENTATION",
    }
)


class KnowledgeNormalizer:
    """Creates reviewable Draft artifacts; it never publishes Knowledge."""

    def normalize(
        self, *, source: SourceDescriptor, document: ExtractedDocument
    ) -> NormalizedKnowledge:
        facts: list[ProposedFact] = []
        documents: list[ProposedDocument] = []
        configured_kind = source.configuration.get("fact_kind")
        configured_key = source.configuration.get("fact_key")
        category_value = source.configuration.get("document_category", "DOCUMENTATION")

        if configured_kind in _FACT_KINDS and isinstance(configured_key, str):
            explicit_value = source.configuration.get("fact_value")
            if isinstance(explicit_value, dict):
                return NormalizedKnowledge(
                    source_digest=document.source_digest,
                    facts=(
                        ProposedFact(
                            source_id=source.source_id,
                            authority=source.authority,
                            key=configured_key,
                            kind=cast(CriticalFactKind, configured_kind),
                            value=explicit_value,
                            locator=document.blocks[0].locator,
                            content_digest=_digest(explicit_value),
                        ),
                    ),
                )
            table = next(
                (block for block in document.blocks if block.kind == "TABLE"),
                None,
            )
            if table is None:
                raise IngestionRejected("structured_fact_value_required")
            value: dict[str, object] = {
                "headers": list(table.rows[0]) if table.rows else [],
                "rows": [list(row) for row in table.rows[1:]],
            }
            return NormalizedKnowledge(
                source_digest=document.source_digest,
                facts=(
                    ProposedFact(
                        source_id=source.source_id,
                        authority=source.authority,
                        key=configured_key,
                        kind=cast(CriticalFactKind, configured_kind),
                        value=value,
                        locator=table.locator,
                        content_digest=_digest(value),
                    ),
                ),
            )

        for index, block in enumerate(document.blocks):
            category = (
                category_value
                if category_value in _DOCUMENT_CATEGORIES
                else "DOCUMENTATION"
            )
            documents.append(
                ProposedDocument(
                    source_id=source.source_id,
                    authority=source.authority,
                    category=cast(KnowledgeDocumentCategory, category),
                    title=document.title
                    if index == 0
                    else f"{document.title} #{index + 1}",
                    text=block.text,
                    locator=block.locator,
                    content_digest=_digest(
                        {
                            "text": block.text,
                            "locator": block.locator,
                        }
                    ),
                )
            )
        return NormalizedKnowledge(
            source_digest=document.source_digest,
            facts=tuple(facts),
            documents=tuple(documents),
        )


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
