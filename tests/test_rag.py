import json
from time import monotonic

import httpx2
import pytest
from openai import OpenAI
from pydantic import ValidationError

from app.config import (
    EmbeddingSettings,
    KnowledgeReaderSettings,
    KnowledgeWriterSettings,
    Settings,
)
from app.rag.chunking import MAX_CHUNK_BYTES, chunk_document, load_corpus
from app.rag.embeddings import EmbeddingError, OpenAIEmbedder, validate_vectors
from app.rag.store import KnowledgeStore


def test_chunks_are_deterministic_heading_aware_unicode_bounded_and_source_addressable():
    raw = (
        "# Metrics\nIntroduction.\n## Revenue\n"
        + "EUR Привіт.\n" * 300
        + "## ARPU\nRevenue divided by active users.\n"
    ).encode()
    chunks = chunk_document("knowledge/metrics.md", raw)
    assert chunks == chunk_document("knowledge/metrics.md", raw)
    assert len({c.id for c in chunks}) == len(chunks)
    assert all(0 < len(c.content.encode()) <= MAX_CHUNK_BYTES for c in chunks)
    assert all(c.line_end >= c.line_start > 0 for c in chunks)
    assert chunks[-1].heading == "Metrics > ARPU"
    assert "active users" in chunks[-1].content
    assert all(c.document_hash == chunks[0].document_hash for c in chunks)


def test_heading_like_text_inside_fences_is_content():
    raw = b"# Rules\n```sql\n# not a heading\nSELECT 1;\n```\n## Revenue\nCompleted only.\n"
    chunks = chunk_document("knowledge/rules.md", raw)
    assert len(chunks) == 2
    assert "# not a heading" in chunks[0].content
    assert chunks[1].heading == "Rules > Revenue"


@pytest.mark.parametrize("raw", [b"", b"# Nothing\n", b"\xff", b"hello\0", b"x" * 65537])
def test_invalid_or_oversized_documents_fail_closed(raw):
    with pytest.raises(ValueError):
        chunk_document("knowledge/test.md", raw)


def test_corpus_fingerprint_tracks_deleted_and_changed_documents(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("# Revenue\nCompleted only.\n")
    b.write_text("# ARPU\nActive users.\n")
    initial, first = load_corpus(tmp_path)
    assert load_corpus(tmp_path) == (initial, first)
    b.unlink()
    remaining, second = load_corpus(tmp_path)
    assert first != second
    assert [c.source_path for c in remaining] == ["knowledge/a.md"]
    a.write_text("# Revenue\nCompleted EUR only.\n")
    assert load_corpus(tmp_path)[1] != second
    b.symlink_to(a)
    with pytest.raises(ValueError, match="symlink"):
        load_corpus(tmp_path)


@pytest.mark.parametrize(
    "cls,password_alias,role",
    [
        (KnowledgeReaderSettings, "KNOWLEDGE_READONLY_PASSWORD", "querylens_knowledge_ro"),
        (KnowledgeWriterSettings, "KNOWLEDGE_WRITER_PASSWORD", "querylens_knowledge_writer"),
    ],
)
def test_knowledge_credentials_never_fall_back_to_owner(monkeypatch, cls, password_alias, role):
    monkeypatch.setenv("POSTGRES_PASSWORD", "owner-secret")
    monkeypatch.setenv("POSTGRES_USER", "owner")
    monkeypatch.delenv(password_alias, raising=False)
    with pytest.raises(ValidationError):
        cls(_env_file=None)
    settings = cls(_env_file=None, **{password_alias: "dedicated-test-password"})
    assert settings.database_url.username == role
    assert settings.database_url.password == "dedicated-test-password"
    with pytest.raises(ValueError, match="Dedicated"):
        KnowledgeStore(Settings(_env_file=None, postgres_password="owner"))


@pytest.mark.parametrize(
    "values",
    [
        {"embedding_dimensions": 1537},
        {"embedding_model": "missing"},
        {"embedding_index_version": "../bad"},
        {"knowledge_index_name": "bad name"},
    ],
)
def test_incompatible_embedding_configuration_is_rejected(values):
    with pytest.raises(ValidationError):
        EmbeddingSettings(_env_file=None, **values)


@pytest.mark.parametrize(
    "vectors",
    [
        None,
        [[0, 0]],
        [[float("nan"), 1]],
        [[float("inf"), 1]],
        [[True, 1]],
        [[1]],
        [[1e-45, 0]],
        [[1e100, 1]],
    ],
)
def test_invalid_provider_vectors_are_rejected(vectors):
    with pytest.raises(EmbeddingError, match="invalid_embedding"):
        validate_vectors(vectors, 1, 2)


def make_embedder(handler, *, budget=250000):
    settings = EmbeddingSettings(
        _env_file=None, openai_api_key="offline-key", embedding_dimensions=2
    )
    client = OpenAI(
        api_key="offline-key",
        base_url="https://api.openai.com/v1",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    return OpenAIEmbedder(settings, client=client, max_input_bytes=budget)


def test_real_sdk_contract_ordering_usage_and_explicit_dimensions():
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.path == "/v1/embeddings"
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "model": "text-embedding-3-small",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [0.0, 1.0]},
                    {"object": "embedding", "index": 0, "embedding": [1.0, 0.0]},
                ],
                "usage": {"prompt_tokens": 4, "total_tokens": 4},
            },
        )

    embedder = make_embedder(handler)
    try:
        assert embedder.embed(["Revenue", "ARPU"], deadline=monotonic() + 2) == [[1, 0], [0, 1]]
        assert embedder.prompt_tokens == 4
        assert embedder.requests == 1
        assert requests[0]["dimensions"] == 2
        assert requests[0]["encoding_format"] == "float"
    finally:
        embedder.close()


@pytest.mark.parametrize(
    "status,category",
    [
        (401, "embedding_authentication"),
        (429, "embedding_rate_limit"),
        (500, "embedding_unavailable"),
    ],
)
def test_provider_errors_are_sanitized_and_not_retried(status, category, caplog):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(status, json={"error": {"message": "private-provider-marker"}})

    embedder = make_embedder(handler)
    try:
        with pytest.raises(EmbeddingError) as caught:
            embedder.embed(["Revenue"], deadline=monotonic() + 2)
        assert str(caught.value) == category
        assert "private-provider-marker" not in str(caught.value) + caplog.text
        assert len(calls) == 1
    finally:
        embedder.close()


def test_budget_expired_deadline_and_missing_key_make_no_requests():
    def forbidden(request):
        raise AssertionError("No network request expected")

    embedder = make_embedder(forbidden, budget=3)
    try:
        with pytest.raises(EmbeddingError, match="embedding_budget"):
            embedder.embed(["Revenue"], deadline=monotonic() + 2)
        with pytest.raises(EmbeddingError, match="deadline_exceeded"):
            embedder.embed(["a"], deadline=monotonic() - 1)
        assert embedder.requests == 0
    finally:
        embedder.close()
    with pytest.raises(EmbeddingError, match="missing_api_key"):
        OpenAIEmbedder(EmbeddingSettings(_env_file=None, openai_api_key=None))


def test_sdk_timeout_and_duplicate_response_indexes_are_rejected():
    def timeout(request):
        raise httpx2.ReadTimeout("private-network-marker", request=request)

    embedder = make_embedder(timeout)
    try:
        with pytest.raises(EmbeddingError, match="embedding_timeout"):
            embedder.embed(["Revenue"], deadline=monotonic() + 2)
    finally:
        embedder.close()

    def duplicate(request):
        return httpx2.Response(
            200,
            json={
                "model": "text-embedding-3-small",
                "object": "list",
                "data": [{"index": 1, "embedding": [1, 0], "object": "embedding"}],
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        )

    embedder = make_embedder(duplicate)
    try:
        with pytest.raises(EmbeddingError, match="invalid_embedding"):
            embedder.embed(["Revenue"], deadline=monotonic() + 2)
    finally:
        embedder.close()
