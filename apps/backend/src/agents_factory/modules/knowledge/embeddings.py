from __future__ import annotations

import hashlib
import math
from typing import Protocol

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field


EMBEDDING_DIMENSIONS = 1_536


class EmbeddingBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    vectors: tuple[tuple[float, ...], ...]


class EmbeddingProvider(Protocol):
    async def embed(self, texts: tuple[str, ...]) -> EmbeddingBatch: ...


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        *,
        client: AsyncOpenAI | None = None,
        model: str = "text-embedding-3-small",
        version: str = "1",
    ) -> None:
        self._client = client or AsyncOpenAI()
        self._model = model
        self._version = version

    async def embed(self, texts: tuple[str, ...]) -> EmbeddingBatch:
        if not texts or len(texts) > 100:
            raise ValueError("embedding batches must contain between 1 and 100 texts")
        response = await self._client.embeddings.create(
            model=self._model,
            input=list(texts),
            dimensions=EMBEDDING_DIMENSIONS,
            encoding_format="float",
        )
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors = tuple(
            tuple(float(value) for value in item.embedding) for item in ordered
        )
        _validate_vectors(vectors, expected_count=len(texts))
        return EmbeddingBatch(
            model=self._model,
            version=self._version,
            vectors=vectors,
        )


class DeterministicEmbeddingProvider:
    """Offline deterministic provider for repeatable tests and local evals."""

    model = "deterministic-sha256"
    version = "1"

    async def embed(self, texts: tuple[str, ...]) -> EmbeddingBatch:
        vectors = tuple(_deterministic_vector(text) for text in texts)
        return EmbeddingBatch(
            model=self.model,
            version=self.version,
            vectors=vectors,
        )


def embedding_literal(vector: tuple[float, ...]) -> str:
    _validate_vectors((vector,), expected_count=1)
    return "[" + ",".join(format(value, ".9g") for value in vector) + "]"


def _validate_vectors(
    vectors: tuple[tuple[float, ...], ...], *, expected_count: int
) -> None:
    if len(vectors) != expected_count:
        raise ValueError("embedding provider returned the wrong vector count")
    for vector in vectors:
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise ValueError("embedding provider returned the wrong dimensions")
        if any(not math.isfinite(value) for value in vector):
            raise ValueError("embedding vectors must contain finite values")


def _deterministic_vector(text: str) -> tuple[float, ...]:
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    values = [
        ((seed[index % len(seed)] / 255.0) * 2.0) - 1.0
        for index in range(EMBEDDING_DIMENSIONS)
    ]
    magnitude = math.sqrt(sum(value * value for value in values)) or 1.0
    return tuple(value / magnitude for value in values)
