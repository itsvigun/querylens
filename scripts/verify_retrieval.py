"""Explicit paid smoke check; offline tests never invoke this command."""

import argparse
import json
import sys

from pydantic import ValidationError

from app.config import EmbeddingSettings, KnowledgeReaderSettings, KnowledgeWriterSettings
from app.rag.embeddings import OpenAIEmbedder
from app.rag.store import KnowledgeStore
from scripts.ingest import KNOWLEDGE_ROOT

CASES = [
    ("What counts as revenue? Are refunded and cancelled orders included?", "Revenue", "completed"),
    ("How is ARPU calculated and which users are in the denominator?", "ARPU", "active users"),
    (
        "How do we calculate subscription churn and the cohort at the start of a period?",
        "Subscription churn rate",
        "immediately before",
    ),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        required=True,
        help="Allow real API calls with a 250000 UTF-8 input-byte budget",
    )
    parser.parse_args()
    embedder = None
    try:
        settings = EmbeddingSettings()
        embedder = OpenAIEmbedder(settings, max_input_bytes=250000)
        with KnowledgeStore(KnowledgeWriterSettings()) as store:
            first = store.ingest(KNOWLEDGE_ROOT, embedder, index_name=settings.knowledge_index_name)
            requests = embedder.requests
            repeated = store.ingest(
                KNOWLEDGE_ROOT, embedder, index_name=settings.knowledge_index_name
            )
            if repeated["status"] != "unchanged" or embedder.requests != requests:
                raise ValueError("repeated_ingestion")
        checks = []
        with KnowledgeStore(KnowledgeReaderSettings()) as store:
            for query, heading, phrase in CASES:
                result = store.search_documentation(
                    query, embedder, index_name=settings.knowledge_index_name
                )
                matches = [
                    s
                    for s in result["sources"]
                    if s["source_path"] == "knowledge/metrics.md"
                    and s["heading"].endswith(" > " + heading)
                    and phrase in s["content"]
                ]
                if result["status"] != "ok" or not matches:
                    raise ValueError("retrieval_definition")
                checks.append(
                    {
                        "metric": heading,
                        "source_id": matches[0]["source_id"],
                        "similarity": matches[0]["similarity"],
                    }
                )
        print(
            json.dumps(
                {
                    "status": "verified",
                    "output_kind": "live_openai_embeddings",
                    "model": embedder.space.model,
                    "dimensions": embedder.space.dimensions,
                    "ingestion": first,
                    "repeat": repeated["status"],
                    "checks": checks,
                    "requests": embedder.requests,
                    "input_bytes": embedder.input_bytes,
                    "prompt_tokens": embedder.prompt_tokens,
                },
                indent=2,
            )
        )
        return 0
    except ValidationError, ValueError, OSError:
        print(
            "Live retrieval verification failed. Check API access, migration, role settings, "
            "index compatibility, and retrieval definitions.",
            file=sys.stderr,
        )
        return 1
    finally:
        if embedder is not None:
            embedder.close()


if __name__ == "__main__":
    raise SystemExit(main())
