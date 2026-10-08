"""Stable entry point for per-request LangGraph orchestration."""

from app.config import LLMSettings
from app.llm.answers import resolve_answer as resolve_answer
from app.llm.workflow import Workflow


def run_session(question: str, provider, dispatcher, settings: LLMSettings) -> dict:
    return Workflow(provider, dispatcher, settings).run(question)
