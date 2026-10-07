"""OpenAI embeddings with explicit request/budget limits and sanitized failures."""

import math
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

import openai
from openai import OpenAI

from app.config import EmbeddingSettings


class EmbeddingError(ValueError):
    """Safe machine-readable category; provider text is never propagated."""


@dataclass(frozen=True)
class VectorSpace:
    provider: str
    model: str
    dimensions: int
    index_version: str

    @classmethod
    def from_settings(cls, settings: EmbeddingSettings):
        return cls(
            settings.embedding_provider,
            settings.embedding_model,
            settings.embedding_dimensions,
            settings.embedding_index_version,
        )


class Embedder(Protocol):
    space: VectorSpace

    def embed(self, texts: list[str], *, deadline: float) -> list[list[float]]: ...


def validate_vectors(vectors, count: int, dimensions: int) -> list[list[float]]:
    if not isinstance(vectors, list | tuple) or len(vectors) != count:
        raise EmbeddingError("invalid_embedding")
    result = []
    for vector in vectors:
        if (
            not isinstance(vector, list | tuple)
            or len(vector) != dimensions
            or any(
                isinstance(v, bool)
                or not isinstance(v, int | float)
                or not math.isfinite(v)
                or abs(v) > 1_000_000
                for v in vector
            )
        ):
            raise EmbeddingError("invalid_embedding")
        values = [float(v) for v in vector]
        # Values must survive pgvector's float32 storage without becoming zero.
        if math.hypot(*values) < 1e-30:
            raise EmbeddingError("invalid_embedding")
        result.append(values)
    return result


class OpenAIEmbedder:
    def __init__(
        self,
        settings: EmbeddingSettings,
        *,
        max_input_bytes: int = 250000,
        client: OpenAI | None = None,
    ):
        if not settings.openai_api_key or not settings.openai_api_key.get_secret_value().strip():
            raise EmbeddingError("missing_api_key")
        self.space = VectorSpace.from_settings(settings)
        self.timeout = settings.embedding_timeout_seconds
        self.input_bytes = 0
        self.prompt_tokens = 0
        self.requests = 0
        self.max_input_bytes = max_input_bytes
        self.client = (
            client
            if client is not None
            else OpenAI(
                api_key=settings.openai_api_key.get_secret_value(),
                base_url="https://api.openai.com/v1",
                timeout=self.timeout,
                max_retries=0,
            )
        )

    def close(self):
        self.client.close()

    def embed(self, texts: list[str], *, deadline: float) -> list[list[float]]:
        if not 1 <= len(texts) <= 16 or any(
            not isinstance(text, str)
            or not text.strip()
            or "\0" in text
            or len(text.encode()) > 2000
            for text in texts
        ):
            raise EmbeddingError("embedding_input_limit")
        input_bytes = sum(len(text.encode()) for text in texts)
        # Byte-level BPE has at most one token per UTF-8 byte. This conservative
        # bound needs no tokenizer downloads and counts attempted requests too.
        if self.input_bytes + input_bytes > self.max_input_bytes:
            raise EmbeddingError("embedding_budget")
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise EmbeddingError("deadline_exceeded")
        self.input_bytes += input_bytes
        self.requests += 1
        try:
            response = self.client.with_options(
                timeout=min(self.timeout, remaining),
                max_retries=0,
            ).embeddings.create(
                model=self.space.model,
                input=texts,
                dimensions=self.space.dimensions,
                encoding_format="float",
            )
            if response.model != self.space.model:
                raise EmbeddingError("invalid_embedding")
            ordered = sorted(response.data, key=lambda item: item.index)
            if [item.index for item in ordered] != list(range(len(texts))):
                raise EmbeddingError("invalid_embedding")
            self.prompt_tokens += response.usage.prompt_tokens
            vectors = validate_vectors(
                [item.embedding for item in ordered], len(texts), self.space.dimensions
            )
            if monotonic() >= deadline:
                raise EmbeddingError("deadline_exceeded")
            return vectors
        except openai.APITimeoutError:
            raise EmbeddingError("embedding_timeout") from None
        except openai.AuthenticationError:
            raise EmbeddingError("embedding_authentication") from None
        except openai.RateLimitError:
            raise EmbeddingError("embedding_rate_limit") from None
        except openai.APIError:
            raise EmbeddingError("embedding_unavailable") from None
        except EmbeddingError:
            raise
        except ValueError, TypeError, AttributeError:
            raise EmbeddingError("invalid_embedding") from None
