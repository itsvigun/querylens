"""Sequential LangGraph nodes with server-owned budgets and sanitized local trace."""

from time import monotonic
from typing import TypedDict

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from app.config import LLMSettings
from app.demo import DATASET_VERSION, REFERENCE_DATE
from app.llm.answers import resolve_answer
from app.llm.contracts import Provider, SafeError, ToolCall, encode, valid_text
from app.tools.dispatch import ARGUMENTS, Dispatcher

GRAPH_STEP_LIMIT = 64
SAFE_PROVIDER_ERRORS = {
    "missing_api_key",
    "deadline_exceeded",
    "llm_budget_exhausted",
    "llm_context_budget",
    "invalid_provider_response",
    "llm_incomplete",
    "llm_refusal",
    "llm_timeout",
    "llm_authentication",
    "llm_rate_limit",
    "llm_unavailable",
    "invalid_answer",
    "unreferenced_numbers",
    "unknown_source",
    "ungrounded_answer",
    "invalid_fact_reference",
}
TERMINAL_TOOL_ERRORS = {
    "deadline_exceeded",
    "sql_budget_exhausted",
    "embedding_authentication",
    "embedding_rate_limit",
    "embedding_budget",
    "embedding_timeout",
    "embedding_unavailable",
    "database_unavailable",
    "database_timeout",
    "index_missing",
    "index_mismatch",
    "reader_required",
    "workflow_failed",
}
REPAIRABLE_SQL_ERRORS = {
    "invalid_sql",
    "forbidden_sql",
    "query_limit",
    "result_limit",
    "timeout",
    "unknown_column",
    "database_error",
    "result_format",
}


class WorkflowState(TypedDict):
    question: str
    reference_date: str
    started: float
    deadline: float
    messages: list[dict]
    pending_calls: list[ToolCall]
    call_position: int
    seen_ids: set[str]
    final_text: str
    schema: dict | None
    sources: dict[str, dict]
    queries: list[dict]
    llm_calls: int
    tool_calls: int
    sql_repairs: int
    repair_pending: bool
    last_tool: dict | None
    trace: list[dict]
    workflow_trace: list[dict]
    next_node: str
    error_category: str | None
    answer: dict | None
    result: dict | None


class Workflow:
    """A fresh graph/state per question; clients and credentials stay outside state."""

    def __init__(self, provider: Provider, dispatcher: Dispatcher, settings: LLMSettings):
        self.provider = provider
        self.dispatcher = dispatcher
        self.settings = settings
        self.latest: WorkflowState | None = None
        builder = StateGraph(WorkflowState)
        routes = {
            "prepare": ["model", "finish"],
            "model": ["admit_calls", "finalize", "finish"],
            "admit_calls": ["dispatch_tool", "finish"],
            "dispatch_tool": ["review_tool", "finish"],
            "review_tool": ["dispatch_tool", "repair", "model", "finish"],
            "repair": ["model", "finish"],
            "finalize": ["finish"],
            "finish": [END],
        }
        for name, targets in routes.items():
            builder.add_node(name, self._record_node(name))
            builder.add_conditional_edges(
                name, lambda state: state["next_node"], {target: target for target in targets}
            )
        builder.add_edge(START, "prepare")
        self.graph = builder.compile()

    @staticmethod
    def _fail(category: str) -> dict:
        return {"error_category": category, "answer": None, "result": None, "next_node": "finish"}

    def _record_node(self, name):
        def node(state: WorkflowState):
            node_started = monotonic()
            try:
                if name != "finish" and node_started >= state["deadline"]:
                    update = self._fail("deadline_exceeded")
                else:
                    update = getattr(self, "_" + name)(state)
            except SafeError as error:
                category = str(error) if str(error) in SAFE_PROVIDER_ERRORS else "workflow_failed"
                update = self._fail(category)
            except Exception:
                # Provider/DB exceptions may contain credentials; never stringify them.
                update = self._fail("workflow_failed")
            if name == "finish" and update.get("error_category"):
                update["next_node"] = END
            merged = {**state, **update}
            event = {
                "node": name,
                "next_node": merged["next_node"],
                "status": "error" if merged["error_category"] else "ok",
                "error_category": merged["error_category"],
                "duration_ms": int((monotonic() - node_started) * 1000),
                "llm_calls": merged["llm_calls"],
                "tool_calls": merged["tool_calls"],
                "sql_attempts": self.dispatcher.sql_calls,
                "sql_repairs": merged["sql_repairs"],
            }
            update["workflow_trace"] = [*state["workflow_trace"], event]
            self.latest = {**merged, "workflow_trace": update["workflow_trace"]}
            return update

        return node

    def _prepare(self, state):
        if not valid_text(state["question"], 2000):
            return self._fail("invalid_question")
        return {"messages": [{"role": "user", "content": state["question"]}], "next_node": "model"}

    def _model(self, state):
        if state["llm_calls"] >= self.settings.llm_max_calls:
            return self._fail("llm_budget_exhausted")
        calls = state["llm_calls"] + 1
        try:
            turn = self.provider.respond(state["messages"], deadline=state["deadline"])
        except SafeError as error:
            category = str(error) if str(error) in SAFE_PROVIDER_ERRORS else "workflow_failed"
            return {**self._fail(category), "llm_calls": calls}
        except Exception:
            return {**self._fail("workflow_failed"), "llm_calls": calls}
        if monotonic() >= state["deadline"]:
            return {**self._fail("deadline_exceeded"), "llm_calls": calls}
        return {
            "llm_calls": calls,
            "pending_calls": turn.calls,
            "call_position": 0,
            "final_text": turn.text,
            "messages": [*state["messages"], *turn.output] if turn.calls else state["messages"],
            "next_node": "admit_calls" if turn.calls else "finalize",
        }

    def _admit_calls(self, state):
        ids = [call.call_id for call in state["pending_calls"]]
        if len(set(ids)) != len(ids) or state["seen_ids"].intersection(ids):
            return self._fail("duplicate_call_id")
        if state["tool_calls"] + len(ids) > self.settings.llm_max_tool_calls:
            return self._fail("tool_budget_exhausted")
        return {"seen_ids": state["seen_ids"] | set(ids), "next_node": "dispatch_tool"}

    def _dispatch_tool(self, state):
        call = state["pending_calls"][state["call_position"]]
        if (
            call.name == "execute_sql"
            and state["repair_pending"]
            and state["sql_repairs"] >= self.settings.llm_max_sql_repairs
        ):
            return self._fail("sql_retry_budget_exhausted")
        before = self.dispatcher.sql_calls
        tool_started = monotonic()
        try:
            output = self.dispatcher.dispatch(call.name, call.arguments, deadline=state["deadline"])
        except Exception:
            output = {"status": "error", "error": {"category": "workflow_failed"}}
        error = output.get("error") or {}
        category = error if isinstance(error, str) else error.get("category")
        known = (
            TERMINAL_TOOL_ERRORS
            | REPAIRABLE_SQL_ERRORS
            | {
                "unknown_tool",
                "invalid_arguments",
                "context_required",
                "invalid_input",
                "invalid_embedding",
                "embedding_input_limit",
                "invalid_query",
                "retrieval_limit",
            }
        )
        if category and category not in known:
            category = "workflow_failed"
            output = {"status": "error", "error": {"category": category}}
        actual_sql_attempt = self.dispatcher.sql_calls > before
        repairs = state["sql_repairs"] + int(actual_sql_attempt and state["repair_pending"])
        entry = {
            "tool": call.name if call.name in ARGUMENTS else "unknown_tool",
            "call_id": call.call_id,
            "status": output["status"],
            "error": {"category": category} if category else None,
            "duration_ms": int((monotonic() - tool_started) * 1000),
        }
        return {
            "last_tool": {
                "name": call.name,
                "status": output["status"],
                "error_category": category,
                "actual_sql_attempt": actual_sql_attempt,
            },
            "schema": output
            if call.name == "get_database_schema" and output["status"] == "ok"
            else state["schema"],
            "sources": dict(self.dispatcher.sources),
            "queries": list(self.dispatcher.queries),
            "sql_repairs": repairs,
            "tool_calls": state["tool_calls"] + 1,
            "call_position": state["call_position"] + 1,
            "trace": [*state["trace"], entry],
            "messages": [
                *state["messages"],
                {"type": "function_call_output", "call_id": call.call_id, "output": encode(output)},
            ],
            "next_node": "review_tool",
        }

    def _review_tool(self, state):
        last = state["last_tool"]
        category = last["error_category"]
        if category in TERMINAL_TOOL_ERRORS:
            return self._fail(category)
        pending = state["repair_pending"]
        if last["actual_sql_attempt"]:
            pending = last["status"] != "ok"
        if state["call_position"] < len(state["pending_calls"]):
            next_node = "dispatch_tool"
        else:
            next_node = "repair" if pending else "model"
        return {"repair_pending": pending, "next_node": next_node}

    def _repair(self, state):
        if state["sql_repairs"] >= self.settings.llm_max_sql_repairs:
            return self._fail("sql_retry_budget_exhausted")
        if self.dispatcher.sql_calls >= self.settings.llm_max_sql_calls:
            return self._fail("sql_budget_exhausted")
        return {"next_node": "model"}

    def _finalize(self, state):
        return {
            "answer": resolve_answer(state["final_text"], self.dispatcher),
            "next_node": "finish",
        }

    def _finish(self, state):
        answer = state["answer"]
        if state["error_category"]:
            answer = {"status": "error", "error": {"category": state["error_category"]}}
        return {"result": answer, "next_node": END}

    def run(self, question: str) -> dict:
        started = monotonic()
        state: WorkflowState = {
            "question": question,
            "reference_date": REFERENCE_DATE.isoformat(),
            "started": started,
            "deadline": started + self.settings.request_timeout_seconds,
            "messages": [],
            "pending_calls": [],
            "call_position": 0,
            "seen_ids": set(),
            "final_text": "",
            "schema": None,
            "sources": dict(self.dispatcher.sources),
            "queries": list(self.dispatcher.queries),
            "llm_calls": 0,
            "tool_calls": 0,
            "sql_repairs": 0,
            "repair_pending": False,
            "last_tool": None,
            "trace": [],
            "workflow_trace": [],
            "next_node": "prepare",
            "error_category": None,
            "answer": None,
            "result": None,
        }
        self.latest = state
        try:
            # Local trace only, even if the user's shell enables LangSmith tracing.
            with tracing_context(enabled=False):
                state = self.graph.invoke(state, config={"recursion_limit": GRAPH_STEP_LIMIT})
        except GraphRecursionError:
            state = {**self.latest, **self._fail("workflow_step_limit")}
            state.update(self._record_node("finish")(state))
        except Exception:
            state = {**self.latest, **self._fail("workflow_failed")}
            state.update(self._record_node("finish")(state))
        result = state["result"] or {
            "status": "error",
            "error": {"category": state["error_category"] or "workflow_failed"},
        }
        try:
            usage = self.provider.usage()
        except Exception:
            usage = {"usage_complete": False}
        result.update(
            {
                "output_kind": "synthetic_analytics",
                "dataset_version": DATASET_VERSION,
                "demo_reference_date": state["reference_date"],
                "queries": state["queries"],
                "trace": state["trace"],
                "workflow_trace": state["workflow_trace"],
                "workflow": {
                    "engine": "langgraph",
                    "llm_calls": state["llm_calls"],
                    "tool_calls": state["tool_calls"],
                    "sql_attempts": self.dispatcher.sql_calls,
                    "sql_repairs": state["sql_repairs"],
                    "sql_successes": sum(q["status"] == "ok" for q in state["queries"]),
                },
                "usage": usage,
                "duration_ms": int((monotonic() - started) * 1000),
                "warnings": [
                    "Synthetic demo data; observed contributions do not establish causality."
                ]
                + (
                    [
                        "SQL results were truncated; inspect query limits "
                        "before interpreting samples."
                    ]
                    if any(q.get("truncated") for q in state["queries"])
                    else []
                ),
            }
        )
        return result
