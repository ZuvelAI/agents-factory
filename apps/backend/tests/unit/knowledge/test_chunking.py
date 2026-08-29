from __future__ import annotations

from uuid import uuid4

from agents_factory.modules.knowledge.chunking import KnowledgeChunker


def test_chunks_are_stable_bounded_and_keep_document_provenance() -> None:
    document_id = uuid4()
    text = (
        "Política de cambios\n\n"
        "Los cambios requieren comprobante y deben solicitarse en la tienda. " * 12
    )
    chunker = KnowledgeChunker(max_characters=260, overlap=40)

    first = chunker.chunk(
        document_id=document_id,
        text=text,
        locator={"page": 4},
    )
    second = chunker.chunk(
        document_id=document_id,
        text=text,
        locator={"page": 4},
    )

    assert first == second
    assert len(first) > 1
    assert all(chunk.document_id == document_id for chunk in first)
    assert all(len(chunk.text) <= 260 for chunk in first)
    assert [chunk.chunk_index for chunk in first] == list(range(len(first)))
    assert all(chunk.locator["page"] == 4 for chunk in first)
    assert all(chunk.locale == "es-CO" for chunk in first)


def test_overlap_never_crosses_document_boundaries() -> None:
    chunker = KnowledgeChunker(max_characters=200, overlap=30)
    first_id = uuid4()
    second_id = uuid4()

    first = chunker.chunk(
        document_id=first_id,
        text="A" * 420,
        locator={"document": "first"},
    )
    second = chunker.chunk(
        document_id=second_id,
        text="B" * 420,
        locator={"document": "second"},
    )

    assert all(set(chunk.text) == {"A"} for chunk in first)
    assert all(set(chunk.text) == {"B"} for chunk in second)
    assert {chunk.document_id for chunk in first} == {first_id}
    assert {chunk.document_id for chunk in second} == {second_id}
