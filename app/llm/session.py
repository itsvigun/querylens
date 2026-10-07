"""First bounded tool loop; LangGraph orchestration follows in its own milestone."""

from time import monotonic

from pydantic import ValidationError

from app.config import LLMSettings
from app.demo import DATASET_VERSION, REFERENCE_DATE
from app.llm.contracts import FinalAnswer, SafeError, encode, valid_text


def resolve_answer(text: str, dispatcher) -> dict:
    try:
        final = FinalAnswer.model_validate_json(text)
    except ValidationError:
        raise SafeError("invalid_answer") from None
    prose = [final.explanation, *final.limitations, *(f.label for f in final.facts)]
    if any(any(c.isnumeric() for c in sentence) for sentence in prose):
        raise SafeError("unreferenced_numbers")
    if len(set(final.source_ids)) != len(final.source_ids) or any(
        sid not in dispatcher.sources for sid in final.source_ids
    ):
        raise SafeError("unknown_source")
    successful = {q["query_id"]: q for q in dispatcher.queries if q["status"] == "ok"}
    if final.status == "answered":
        if not dispatcher.schema_seen or not successful or not final.source_ids:
            raise SafeError("ungrounded_answer")
        if not final.facts and any(q["rows"] for q in successful.values()):
            raise SafeError("ungrounded_answer")
    elif final.facts:
        raise SafeError("ungrounded_answer")
    facts = []
    for fact in final.facts:
        query = successful.get(fact.query_id)
        if query is None or fact.row >= len(query["rows"]) or fact.column >= len(query["columns"]):
            raise SafeError("invalid_fact_reference")
        value = query["rows"][fact.row][fact.column]
        facts.append({**fact.model_dump(), "value": value, "undefined": value is None})
    return {
        "status": final.status,
        "explanation": final.explanation,
        "facts": facts,
        "sources": [dispatcher.sources[sid] for sid in final.source_ids],
        "limitations": final.limitations,
    }


def run_session(question: str, provider, dispatcher, settings: LLMSettings) -> dict:
    started = monotonic()
    deadline = started + settings.request_timeout_seconds
    trace = []
    result = {"status": "error", "error": {"category": "invalid_question"}}
    try:
        if not valid_text(question, 2000):
            raise SafeError("invalid_question")
        messages = [{"role": "user", "content": question}]
        seen_ids = set()
        tools = 0
        for _ in range(settings.llm_max_calls):
            if monotonic() >= deadline:
                raise SafeError("deadline_exceeded")
            turn = provider.respond(messages, deadline=deadline)
            if monotonic() >= deadline:
                raise SafeError("deadline_exceeded")
            if not turn.calls:
                result = resolve_answer(turn.text, dispatcher)
                break
            ids = [call.call_id for call in turn.calls]
            if len(set(ids)) != len(ids) or seen_ids.intersection(ids):
                raise SafeError("duplicate_call_id")
            if tools + len(turn.calls) > settings.llm_max_tool_calls:
                raise SafeError("tool_budget_exhausted")
            seen_ids.update(ids)
            messages.extend(turn.output)
            for call in turn.calls:
                tools += 1
                tool_started = monotonic()
                output = dispatcher.dispatch(call.name, call.arguments, deadline=deadline)
                trace.append(
                    {
                        "tool": call.name,
                        "call_id": call.call_id,
                        "status": output["status"],
                        "error": output.get("error"),
                        "duration_ms": int((monotonic() - tool_started) * 1000),
                    }
                )
                if (output.get("error") or {}).get("category") in (
                    "deadline_exceeded",
                    "sql_budget_exhausted",
                ):
                    raise SafeError(output["error"]["category"])
                messages.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": encode(output),
                    }
                )
        else:
            raise SafeError("llm_budget_exhausted")
    except SafeError as exc:
        result = {"status": "error", "error": {"category": str(exc)}}
    result.update(
        {
            "output_kind": "synthetic_analytics",
            "dataset_version": DATASET_VERSION,
            "demo_reference_date": REFERENCE_DATE.isoformat(),
            "queries": dispatcher.queries,
            "trace": trace,
            "usage": provider.usage(),
            "duration_ms": int((monotonic() - started) * 1000),
            "warnings": ["Synthetic demo data; observed contributions do not establish causality."]
            + (
                ["SQL results were truncated; inspect query limits before interpreting samples."]
                if any(q.get("truncated") for q in dispatcher.queries)
                else []
            ),
        }
    )
    return result
