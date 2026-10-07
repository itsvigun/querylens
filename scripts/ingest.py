"""Explicit OpenAI knowledge ingestion; never runs during API startup."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from app.config import EmbeddingSettings, KnowledgeWriterSettings
from app.rag.chunking import load_corpus
from app.rag.embeddings import OpenAIEmbedder
from app.rag.store import KnowledgeStore

KNOWLEDGE_ROOT = Path(__file__).resolve().parents[1] / "knowledge"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Inspect chunks without DB/API access"
    )
    parser.add_argument(
        "--reindex", action="store_true", help="Atomically rebuild the configured index"
    )
    args = parser.parse_args()
    embedder = None
    try:
        if args.dry_run:
            corpus, fingerprint = load_corpus(KNOWLEDGE_ROOT)
            print(
                json.dumps(
                    {
                        "status": "dry_run",
                        "chunks": len(corpus),
                        "input_bytes": sum(len(c.content.encode()) for c in corpus),
                        "corpus_hash": fingerprint,
                        "sources": sorted({c.source_path for c in corpus}),
                    }
                )
            )
            return 0
        settings = EmbeddingSettings()
        embedder = OpenAIEmbedder(settings)
        with KnowledgeStore(KnowledgeWriterSettings()) as store:
            result = store.ingest(
                KNOWLEDGE_ROOT,
                embedder,
                index_name=settings.knowledge_index_name,
                reindex=args.reindex,
            )
        print(
            json.dumps(
                {
                    **result,
                    "provider": embedder.space.provider,
                    "model": embedder.space.model,
                    "dimensions": embedder.space.dimensions,
                    "requests": embedder.requests,
                    "prompt_tokens": embedder.prompt_tokens,
                }
            )
        )
        return 0
    except ValidationError, ValueError, OSError:
        print(
            "Ingestion failed. Check knowledge files, dedicated writer settings, migrations, "
            "embedding API access, and index compatibility (explicit --reindex after a change).",
            file=sys.stderr,
        )
        return 1
    finally:
        if embedder is not None:
            embedder.close()


if __name__ == "__main__":
    raise SystemExit(main())
