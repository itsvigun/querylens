"""Provider and final-answer contracts, independent of the OpenAI SDK."""

import json
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def valid_text(value, max_bytes: int) -> bool:
    try:
        return (
            isinstance(value, str)
            and bool(value.strip())
            and "\0" not in value
            and len(value.encode()) <= max_bytes
        )
    except UnicodeError:
        return False


class SafeError(ValueError):
    """Only a fixed category is allowed across the service boundary."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class FactReference(StrictModel):
    label: str = Field(min_length=1, max_length=160)
    query_id: str = Field(pattern=r"^sql_[1-3]$")
    row: int = Field(ge=0, le=49)
    column: int = Field(ge=0, le=99)


class FinalAnswer(StrictModel):
    status: Literal["answered", "clarification", "insufficient_context", "unsupported"]
    explanation: str = Field(min_length=1, max_length=3000)
    facts: list[FactReference] = Field(max_length=30)
    source_ids: list[str] = Field(max_length=24)
    limitations: list[str] = Field(max_length=10)


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class Turn:
    # Preserve SDK output items (including reasoning) for stateless replay.
    output: list[dict]
    calls: list[ToolCall]
    text: str


class Provider(Protocol):
    def respond(self, messages: list[dict], *, deadline: float) -> Turn: ...

    def usage(self) -> dict: ...
