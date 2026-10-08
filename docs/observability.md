# Observability

[Documentation index](README.md)

Each `POST /api/chat` produces one JSON `analytics_request` log on stderr, including
validation errors, busy responses and sanitized unexpected failures. The CLI
`ask()` boundary emits the same summary. Startup, health and opening the UI make
no provider calls or analytics-request events.

A server-generated UUID identifies the request. Chat returns it in `X-Request-ID`
and a returned service result also includes `request_id` in the JSON body.
Client-supplied identifiers are ignored. A ContextVar carries the identifier into
FastAPI's worker thread; the API boundary owns the single event so CLI/service
logging cannot duplicate it. Concurrent requests have independent identifiers.

The allowlist in [`app/observability.py`](../app/observability.py) includes:

- Timestamp, request ID, total boundary duration and HTTP status where applicable.
- Result status and fixed error category.
- OpenAI provider and recognized model identifier.
- Actual model requests, input/output tokens and usage completeness.
- Tool calls, SQL attempts and SQL repairs.
- Recognized embedding model, requests and embedding tokens.

Unknown identifiers are replaced with null/fixed categories. Counts must be
nonnegative bounded integers; booleans and arbitrary strings cannot become counts.
A failure before workflow/provider creation has unavailable counts/model fields;
null and `usage_complete=false` mean missing evidence, not free completed requests.
The log excludes question text, SQL/results, source content, call IDs, replay
messages, headers, settings, exception text and stack traces. It uses structural
selection rather than attempting to redact arbitrary text after logging it.
Tests inject credentials and newline payloads into these excluded fields and
check success, validation, busy, unexpected failure and concurrent request paths.

View container summaries with:

```bash
docker compose logs --tail 50 api
```

The supplied Docker command and documented host command disable Uvicorn access
logs, avoiding a second log channel with arbitrary URL query strings. Application
lifecycle messages remain available. The analytics logger has its own JSON handler
and does not propagate into root/SDK loggers. This is local structured logging,
not external tracing, durable metrics, log retention or alerting. LangSmith
tracing stays disabled. No new telemetry service or dependency is introduced.

Response tool/workflow traces still expose sanitized transition details for
inspection; logs keep only aggregate counts. Duration is observed per request,
not a performance claim. No estimated billing field is added; recorded usage and
historical smoke estimates remain separate. See [chat](chat.md), [configuration](configuration.md)
and [verification](verification.md#stage-7).
