# Web UI

[Documentation index](README.md)

The UI is available at [http://127.0.0.1:8000/](http://127.0.0.1:8000/).
Complete [setup](setup.md), configure the server-side API key and explicitly
[ingest the knowledge corpus](retrieval.md) before asking real questions.
The page itself only loads local assets and `GET /demo`; opening it or selecting
an example makes no provider call. The Ask button submits one `POST /api/chat`.

## Using the workspace

1. Read the visible synthetic label, UTC reference date, dataset version and currency.
2. Enter a metric and period, or select an example to fill the question field.
3. Click **Ask QueryLens** (or press Ctrl/Cmd+Enter). The form disables while waiting.
4. Inspect the answer facts, SQL/result tables, source citations and expanded source text.
   **Run details** exposes returned timing, model/token usage and tool trace.
5. For clarification, edit the full question and ask again. Questions are independent;
   no previous answer or conversation history is sent automatically.

The byte counter matches the API's 2000-byte UTF-8 limit. Failed context loading
disables submission until **Reload context** succeeds, so the time anchor remains
explicit. Browser waiting is capped at 130 seconds; this stops waiting locally
and does not guarantee cancellation of server work. Failures never auto-retry.

Answers, clarification, unsupported questions and missing context have distinct
states. Provider/configuration/index failures and HTTP errors show fixed guidance.
Previous results disappear when a new request starts, so failed requests cannot
leave a stale answer presented as their result. Failed SQL attempts, warnings,
limitations and truncation are shown when returned. Empty tables say **No rows
returned**; NULL facts say **Undefined**. Truncated tables are labeled as samples.

## Implementation and boundaries

- [`app/api/ui.py`](../app/api/ui.py) serves the HTML at `/`, independently of DB/provider access.
- [`app/static/index.html`](../app/static/index.html) holds the accessible page structure.
- [`app/static/assets/app.js`](../app/static/assets/app.js) loads metadata, submits questions and renders results.
- [`app/static/assets/app.css`](../app/static/assets/app.css) supplies responsive layout and reduced-motion styles.
- The existing FastAPI app mounts `/assets`; `/docs` continues to serve Swagger UI.

The UI uses browser-native HTML/CSS/JavaScript with local assets and system fonts.
There is no JavaScript build or frontend runtime dependency. The Dockerfile's
existing `COPY app` includes the page and assets. Paths are resolved relative to
the module, not the launch directory. Browser testing alone uses the optional
Playwright dependency group.

All returned text is inserted with `textContent`, including SQL, table headers,
explanations and source content. No Markdown/HTML renderer interprets model text;
source paths/citations are displayed as text, not followed as URLs. Fact links
target only validated local query anchors. Numeric strings remain strings, so
Decimal money and integers beyond JavaScript's exact range are preserved. Displayed
row/column references are one-based; the API's references are zero-based.

The page sends a restrictive Content-Security-Policy allowing only same-origin
assets and requests, with no inline scripts/styles or framing. It has labeled
inputs, live status announcements, visible keyboard focus, accessible disclosures,
scrollable result tables and a mobile layout. The browser never receives API keys
or database credentials, and answers are not persisted in browser storage.

Server-side SQL permissions, budgets and answer validation remain authoritative;
the UI's controls do not replace them. The main API keeps its configured request
budgets. Cost estimation, streaming, history and a deployed public demo are outside
this milestone. See [testing](testing.md#browser-checks) and the
[stage 6 verification record](verification.md#stage-6) for actual evidence.
