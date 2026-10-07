"""Retrieve real OpenAI-embedded documentation with source metadata."""

import argparse
import json
import sys

from pydantic import ValidationError

from app.config import EmbeddingSettings, KnowledgeReaderSettings
from app.rag.embeddings import OpenAIEmbedder
from app.rag.store import KnowledgeStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    args = parser.parse_args()
    embedder = None
    try:
        settings = EmbeddingSettings()
        embedder = OpenAIEmbedder(settings, max_input_bytes=2000)
        with KnowledgeStore(KnowledgeReaderSettings()) as store:
            result = store.search_documentation(
                args.query, embedder, index_name=settings.knowledge_index_name
            )
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 1 if result["status"] == "error" else 0
    except ValidationError, ValueError:
        print(
            "Search initialization failed. Check dedicated reader and embedding settings.",
            file=sys.stderr,
        )
        return 1
    finally:
        if embedder is not None:
            embedder.close()


if __name__ == "__main__":
    raise SystemExit(main())
