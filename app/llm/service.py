"""Per-request resources, with no migration or ingestion credentials in tools."""

from contextlib import ExitStack

from pydantic import ValidationError

from app.config import (
    AnalyticsSettings,
    EmbeddingSettings,
    KnowledgeReaderSettings,
    LLMSettings,
    SQLToolLimits,
)
from app.llm.contracts import SafeError
from app.llm.openai_provider import OpenAIProvider
from app.llm.session import run_session
from app.rag.embeddings import EmbeddingError, OpenAIEmbedder
from app.rag.store import KnowledgeStore
from app.tools.database import DatabaseTools
from app.tools.dispatch import Dispatcher


def ask(question: str, *, settings: LLMSettings | None = None) -> dict:
    try:
        settings = settings if settings is not None else LLMSettings()
        with ExitStack() as stack:
            provider = OpenAIProvider(settings)
            stack.callback(provider.close)
            embedding_settings = EmbeddingSettings()
            embedder = OpenAIEmbedder(embedding_settings, max_input_bytes=16000)
            stack.callback(embedder.close)
            configured = SQLToolLimits()
            # The chat tool returns bounded samples; aggregate totals belong in SQL.
            limits = configured.model_copy(
                update={
                    "sql_max_rows": min(configured.sql_max_rows, 50),
                    "sql_max_result_bytes": min(configured.sql_max_result_bytes, 12000),
                }
            )
            database = stack.enter_context(DatabaseTools(AnalyticsSettings(), limits))
            knowledge = stack.enter_context(KnowledgeStore(KnowledgeReaderSettings()))
            dispatcher = Dispatcher(
                database,
                knowledge,
                embedder,
                index_name=embedding_settings.knowledge_index_name,
                max_sql_calls=settings.llm_max_sql_calls,
            )
            result = run_session(question, provider, dispatcher, settings)
            result["embedding_usage"] = {
                "model": embedder.space.model,
                "requests": embedder.requests,
                "input_bytes": embedder.input_bytes,
                "prompt_tokens": embedder.prompt_tokens,
            }
            return result
    except (SafeError, EmbeddingError) as exc:
        return {"status": "error", "error": {"category": str(exc)}}
    except ValidationError, ValueError:
        return {"status": "error", "error": {"category": "configuration_error"}}
