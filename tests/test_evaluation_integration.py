"""Twenty scripted cases over real PostgreSQL and disposable stub-vector indexes."""

import os

import pytest
from sqlalchemy import select

from app.config import KnowledgeReaderSettings
from app.rag.schema import indexes
from app.rag.store import KnowledgeStore
from evals.runner import load_cases, run_evaluation

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("QUERYLENS_INTEGRATION") != "1",
        reason="Requires the migrated, provisioned and seeded demo database",
    ),
]


def index_snapshot():
    with KnowledgeStore(KnowledgeReaderSettings()) as store:
        with store.engine.connect() as connection:
            return list(connection.execute(select(indexes).order_by(indexes.c.name)))


def test_twenty_cases_pass_and_preserve_existing_indexes(monkeypatch):
    # Even a local real API key must never be used by this command.
    monkeypatch.setattr("evals.runner.OpenAIProvider", lambda *a, **k: pytest.fail("paid provider"))
    monkeypatch.setattr(
        "evals.runner.OpenAIEmbedder", lambda *a, **k: pytest.fail("paid embeddings")
    )
    before = index_snapshot()
    report = run_evaluation(load_cases()["cases"])
    assert report["output_kind"] == "offline_scripted_postgres_evaluation"
    assert (report["case_count"], report["passed"], report["failed"]) == (20, 20, 0)
    assert report["metric_cases"] == report["correct_metric_cases"] == 15
    assert report["definition_recall"] == 1
    assert 0 < report["definition_mrr"] <= 1
    cases = {c["id"]: c for c in report["cases"]}
    assert cases["sql_repair"]["sql_repairs"] == 1
    assert cases["exhausted_repairs"]["sql_attempts"] == 3
    assert cases["deadline"]["sql_attempts"] == 0
    assert cases["prompt_injection"]["dangerous_queries_rejected"] == 5
    assert index_snapshot() == before
