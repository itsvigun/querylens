"""Exercise the compiled LangGraph offline; stub results are not live AI evidence."""

from time import monotonic

import pytest
from test_llm import (
    StubProvider,
    calls_turn,
    context_turn,
    encode,
    final_turn,
    function_call,
    llm_settings,
    make_dispatcher,
)

from app.llm import workflow
from app.llm.contracts import SafeError
from app.llm.session import run_session
from app.tools.database import SQLResult, ToolError


def sql_turn(number=1):
    return calls_turn(function_call("execute_sql", {"query": "SELECT 1"}, f"sql_{number}"))


class FailingSQL:
    def __init__(self, failures):
        self.failures = failures
        self.calls = []

    def execute_sql(self, query, *, deadline):
        self.calls.append(query)
        if len(self.calls) <= self.failures:
            return SQLResult(
                status="error", error=ToolError(category="unknown_column", message="Check schema.")
            )
        return SQLResult(
            status="ok", columns=[{"name": "value", "type": "numeric"}], rows=[["336080.07"]]
        )


def test_correct_question_keeps_grounded_values_and_local_graph_trace():
    provider = StubProvider([context_turn(), sql_turn(), final_turn()])
    result = run_session("September revenue?", provider, make_dispatcher(), llm_settings())
    assert result["status"] == "answered"
    assert result["facts"][0]["value"] == "336080.07"
    assert result["workflow"] == {
        "engine": "langgraph",
        "llm_calls": 3,
        "tool_calls": 3,
        "sql_attempts": 1,
        "sql_repairs": 0,
        "sql_successes": 1,
    }
    assert result["workflow_trace"][-1]["node"] == "finish"
    assert result["workflow_trace"][-1]["next_node"] == "__end__"
    assert "question" not in result and "messages" not in result


@pytest.mark.parametrize("failures", [1, 2])
def test_sql_error_feedback_reaches_model_then_repair_succeeds(failures):
    dispatcher = make_dispatcher()
    dispatcher.database = FailingSQL(failures)
    provider = StubProvider(
        [
            context_turn(),
            *(sql_turn(n) for n in range(1, failures + 2)),
            final_turn(
                facts=[
                    {
                        "label": "Revenue, EUR",
                        "query_id": f"sql_{failures + 1}",
                        "row": 0,
                        "column": 0,
                    }
                ]
            ),
        ]
    )
    result = run_session("September revenue?", provider, dispatcher, llm_settings())
    assert result["status"] == "answered", result
    assert result["workflow"]["sql_repairs"] == failures
    assert result["workflow"]["sql_attempts"] == failures + 1
    assert sum(e["node"] == "repair" for e in result["workflow_trace"]) == failures
    assert "unknown_column" in encode(provider.messages[2])
    assert result["facts"][0]["value"] == result["queries"][-1]["rows"][0][0]


@pytest.mark.parametrize("repairs", [0, 1, 2])
def test_exhausted_sql_repairs_stop_without_another_model_or_database_call(repairs):
    dispatcher = make_dispatcher()
    dispatcher.database = FailingSQL(100)
    provider = StubProvider([context_turn(), *(sql_turn(n) for n in range(1, 5))])
    result = run_session(
        "Revenue?", provider, dispatcher, llm_settings(llm_max_sql_repairs=repairs)
    )
    assert result["error"]["category"] == "sql_retry_budget_exhausted"
    assert len(dispatcher.database.calls) == repairs + 1
    assert len(provider.messages) == repairs + 2
    assert result["workflow"]["sql_repairs"] == repairs
    assert len(result["queries"]) == repairs + 1
    assert result["workflow_trace"][-1]["node"] == "finish"


@pytest.mark.parametrize("status", ["clarification", "unsupported", "insufficient_context"])
def test_non_answer_terminal_status_needs_no_sql(status):
    dispatcher = make_dispatcher()
    provider = StubProvider([final_turn(status=status, facts=[], source_ids=[])])
    result = run_session("Which period?", provider, dispatcher, llm_settings())
    assert result["status"] == status
    assert result["queries"] == [] and result["trace"] == []
    assert dispatcher.database.calls == []
    assert [e["node"] for e in result["workflow_trace"]] == [
        "prepare",
        "model",
        "finalize",
        "finish",
    ]


@pytest.mark.parametrize(
    "category",
    ["index_missing", "embedding_authentication", "database_unavailable", "reader_required"],
)
def test_string_retrieval_errors_terminate_with_safe_category(category):
    dispatcher = make_dispatcher()
    dispatcher.knowledge.search_documentation = lambda *a, **k: {
        "status": "error",
        "error": category,
        "sources": [],
    }
    provider = StubProvider([context_turn(), sql_turn()])
    result = run_session("Revenue?", provider, dispatcher, llm_settings())
    assert result["error"]["category"] == category
    assert result["trace"][-1]["error"] == {"category": category}
    assert len(provider.messages) == 1 and dispatcher.database.calls == []


def test_insufficient_retrieval_context_can_return_an_explanation():
    dispatcher = make_dispatcher()
    dispatcher.knowledge.search_documentation = lambda *a, **k: {
        "status": "insufficient_context",
        "sources": [],
    }
    provider = StubProvider(
        [context_turn(), final_turn(status="insufficient_context", facts=[], source_ids=[])]
    )
    result = run_session("Unknown metric?", provider, dispatcher, llm_settings())
    assert result["status"] == "insufficient_context"
    assert result["workflow"]["sql_attempts"] == 0


def test_tool_budget_rejects_whole_batch_before_dispatch():
    dispatcher = make_dispatcher()
    provider = StubProvider([context_turn()])
    result = run_session("Revenue?", provider, dispatcher, llm_settings(llm_max_tool_calls=1))
    assert result["error"]["category"] == "tool_budget_exhausted"
    assert not dispatcher.schema_seen and result["trace"] == []


def test_duplicate_id_across_turns_is_not_dispatched_again():
    provider = StubProvider([context_turn(), context_turn()])
    result = run_session("Revenue?", provider, make_dispatcher(), llm_settings())
    assert result["error"]["category"] == "duplicate_call_id"
    assert result["workflow"]["tool_calls"] == 2


def test_unusable_tool_loop_stops_at_model_budget():
    provider = StubProvider([calls_turn(function_call("shell", {}, str(n))) for n in range(4)])
    result = run_session("Revenue?", provider, make_dispatcher(), llm_settings(llm_max_calls=2))
    assert result["error"]["category"] == "llm_budget_exhausted"
    assert len(provider.messages) == 2
    assert result["workflow"]["tool_calls"] == 2


def test_deadline_after_provider_response_prevents_tool_execution(monkeypatch):
    clock = [monotonic()]
    monkeypatch.setattr(workflow, "monotonic", lambda: clock[0])
    provider = StubProvider([context_turn()])
    original = provider.respond

    def slow_response(*args, **kwargs):
        turn = original(*args, **kwargs)
        clock[0] += 61
        return turn

    provider.respond = slow_response
    dispatcher = make_dispatcher()
    result = run_session("Revenue?", provider, dispatcher, llm_settings())
    assert result["error"]["category"] == "deadline_exceeded"
    assert result["workflow"]["llm_calls"] == 1
    assert result["trace"] == [] and not dispatcher.schema_seen


def test_deadline_after_sql_preserves_executed_query_without_followup_model(monkeypatch):
    clock = [monotonic()]
    monkeypatch.setattr(workflow, "monotonic", lambda: clock[0])
    dispatcher = make_dispatcher()
    original = dispatcher.database.execute_sql

    def slow_sql(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] += 61
        return result

    dispatcher.database.execute_sql = slow_sql
    provider = StubProvider([context_turn(), sql_turn(), final_turn()])
    result = run_session("Revenue?", provider, dispatcher, llm_settings())
    assert result["error"]["category"] == "deadline_exceeded"
    assert result["queries"][0]["status"] == "ok"
    assert result["workflow"]["llm_calls"] == 2
    assert result["trace"][-1]["tool"] == "execute_sql"


@pytest.mark.parametrize("error", [RuntimeError("private-marker"), SafeError("private-marker")])
def test_unexpected_provider_errors_are_sanitized_and_not_retried(error):
    provider = StubProvider([])

    def broken(*args, **kwargs):
        raise error

    provider.respond = broken
    result = run_session("Revenue?", provider, make_dispatcher(), llm_settings())
    assert result["error"]["category"] == "workflow_failed"
    assert result["workflow"]["llm_calls"] == 1
    assert "private-marker" not in encode(result)


def test_unrecognized_tool_error_is_sanitized_and_counted():
    dispatcher = make_dispatcher()
    dispatcher.knowledge.search_documentation = lambda *a, **k: {
        "status": "error",
        "error": "private-marker",
        "sources": [],
    }
    result = run_session("Revenue?", StubProvider([context_turn()]), dispatcher, llm_settings())
    assert result["error"]["category"] == "workflow_failed"
    assert result["workflow"]["tool_calls"] == 2
    assert "private-marker" not in encode(result)


def test_recursion_guard_is_a_bounded_sanitized_failure(monkeypatch):
    monkeypatch.setattr(workflow, "GRAPH_STEP_LIMIT", 2)
    provider = StubProvider([context_turn()])
    result = run_session("Revenue?", provider, make_dispatcher(), llm_settings())
    assert result["error"]["category"] == "workflow_step_limit"
    assert result["workflow"]["llm_calls"] == 1
    assert result["trace"] == []
    assert result["workflow_trace"][-1]["node"] == "finish"


def test_total_sql_attempt_budget_can_end_repairs_earlier():
    dispatcher = make_dispatcher()
    dispatcher.database = FailingSQL(100)
    dispatcher.max_sql_calls = 1
    provider = StubProvider([context_turn(), sql_turn(), sql_turn(2)])
    result = run_session("Revenue?", provider, dispatcher, llm_settings(llm_max_sql_calls=1))
    assert result["error"]["category"] == "sql_budget_exhausted"
    assert result["workflow"]["sql_attempts"] == 1
    assert result["workflow"]["sql_repairs"] == 0
    assert len(provider.messages) == 2


def test_unexpected_database_exception_is_counted_without_exposing_its_message():
    dispatcher = make_dispatcher()

    def broken(*args, **kwargs):
        raise RuntimeError("private-database-marker")

    dispatcher.database.execute_sql = broken
    provider = StubProvider([context_turn(), sql_turn(), final_turn()])
    result = run_session("Revenue?", provider, dispatcher, llm_settings())
    assert result["error"]["category"] == "workflow_failed"
    assert result["workflow"]["sql_attempts"] == 1
    assert result["workflow"]["tool_calls"] == 3
    assert len(provider.messages) == 2
    assert "private-database-marker" not in encode(result)


def test_langsmith_environment_cannot_enable_external_tracing(monkeypatch):
    import langsmith

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "offline-test-key")

    def forbidden_client(*args, **kwargs):
        raise AssertionError("External tracing client must not be created.")

    monkeypatch.setattr(langsmith.Client, "__init__", forbidden_client)
    result = run_session(
        "Which period?",
        StubProvider([final_turn(status="clarification", facts=[], source_ids=[])]),
        make_dispatcher(),
        llm_settings(),
    )
    assert result["status"] == "clarification", result
