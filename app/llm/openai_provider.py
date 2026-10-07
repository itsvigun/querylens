"""Official Responses API, stateless replay, explicit limits, sanitized errors."""

from time import monotonic

import openai
from openai import OpenAI

from app.config import LLMSettings
from app.llm.contracts import FinalAnswer, SafeError, ToolCall, Turn, encode
from app.llm.prompt import INSTRUCTIONS
from app.tools.dispatch import TOOLS


class OpenAIProvider:
    def __init__(self, settings: LLMSettings, *, client: OpenAI | None = None):
        if not settings.openai_api_key or not settings.openai_api_key.get_secret_value().strip():
            raise SafeError("missing_api_key")
        self.settings = settings
        self.client = (
            client
            if client is not None
            else OpenAI(
                api_key=settings.openai_api_key.get_secret_value(),
                base_url="https://api.openai.com/v1",
                max_retries=0,
                timeout=settings.llm_timeout_seconds,
            )
        )
        self.calls = self.input_bytes = self.input_tokens = self.output_tokens = 0
        self.output_reserved = 0
        self.usage_complete = True

    def close(self):
        self.client.close()

    def usage(self) -> dict:
        return {
            "model": self.settings.llm_model,
            "requests": self.calls,
            "attempted_input_bytes": self.input_bytes,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usage_complete": self.usage_complete,
        }

    def respond(self, messages: list[dict], *, deadline: float) -> Turn:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise SafeError("deadline_exceeded")
        if self.calls >= self.settings.llm_max_calls:
            raise SafeError("llm_budget_exhausted")
        allowance = min(1000, self.settings.llm_max_output_tokens - self.output_reserved)
        if allowance < 256:
            raise SafeError("llm_budget_exhausted")
        body = {
            "model": self.settings.llm_model,
            "instructions": INSTRUCTIONS,
            "input": messages,
            "tools": TOOLS,
            "tool_choice": "auto",
            "parallel_tool_calls": True,
            "store": False,
            "reasoning": {"effort": "none"},
            "max_output_tokens": allowance,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "querylens_answer",
                    "strict": True,
                    "schema": FinalAnswer.model_json_schema(),
                }
            },
        }
        # Counts the whole request, with a conservative allowance for protocol tokens.
        # This bounds local context; provider usage is authoritative for billing.
        size = len(encode(body).encode()) + 1024
        if self.input_bytes + size > self.settings.llm_max_input_bytes:
            raise SafeError("llm_context_budget")
        self.input_bytes += size
        self.calls += 1
        self.output_reserved += allowance
        try:
            response = self.client.with_options(
                timeout=min(remaining, self.settings.llm_timeout_seconds),
                max_retries=0,
            ).responses.create(**body)
            usage = response.usage
            if usage is None or any(
                isinstance(v, bool) or not isinstance(v, int) or v < 0
                for v in (usage.input_tokens, usage.output_tokens)
            ):
                self.usage_complete = False
                raise SafeError("invalid_provider_response")
            self.input_tokens += usage.input_tokens
            self.output_tokens += usage.output_tokens
            # Reclaim unused output only when the provider reports valid usage.
            if usage.output_tokens > allowance:
                raise SafeError("invalid_provider_response")
            self.output_reserved -= allowance - usage.output_tokens
            if monotonic() >= deadline:
                raise SafeError("deadline_exceeded")
            if response.status != "completed" or response.error is not None:
                raise SafeError("llm_incomplete")
            output = [item.model_dump(mode="json", exclude_none=True) for item in response.output]
            if len(encode(output).encode()) > 24000:
                raise SafeError("invalid_provider_response")
            calls = []
            for item in response.output:
                if item.type == "function_call":
                    if (
                        not isinstance(item.call_id, str)
                        or not 1 <= len(item.call_id) <= 128
                        or not isinstance(item.name, str)
                        or not 1 <= len(item.name) <= 64
                        or not isinstance(item.arguments, str)
                        or item.status not in (None, "completed")
                    ):
                        raise SafeError("invalid_provider_response")
                    calls.append(ToolCall(item.call_id, item.name, item.arguments))
                elif item.type == "message":
                    if item.status != "completed":
                        raise SafeError("llm_incomplete")
                    for part in item.content:
                        if part.type == "refusal":
                            raise SafeError("llm_refusal")
                        if part.type != "output_text":
                            raise SafeError("invalid_provider_response")
                elif item.type != "reasoning":
                    raise SafeError("invalid_provider_response")
            if len(calls) > 8 or len({c.call_id for c in calls}) != len(calls):
                raise SafeError("invalid_provider_response")
            return Turn(output, calls, response.output_text)
        except openai.APITimeoutError:
            self.usage_complete = False
            raise SafeError("llm_timeout") from None
        except openai.AuthenticationError:
            self.usage_complete = False
            raise SafeError("llm_authentication") from None
        except openai.RateLimitError:
            self.usage_complete = False
            raise SafeError("llm_rate_limit") from None
        except openai.APIError:
            self.usage_complete = False
            raise SafeError("llm_unavailable") from None
        except SafeError:
            raise
        except ValueError, TypeError, AttributeError:
            self.usage_complete = False
            raise SafeError("invalid_provider_response") from None
