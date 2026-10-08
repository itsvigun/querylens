"""Validate model references and insert actual executed SQL cell values."""

from pydantic import ValidationError

from app.llm.contracts import FinalAnswer, SafeError


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
