"use strict";

const form = document.querySelector("#question-form");
const question = document.querySelector("#question");
const submit = document.querySelector("#submit-question");
const content = document.querySelector("#answer-content");
const badge = document.querySelector("#answer-badge");
const statusText = document.querySelector("#request-status");
const inputError = document.querySelector("#input-error");
const encoder = new TextEncoder();
let busy = false;
let contextReady = false;

const statusLabels = {
  answered: "Answered", clarification: "Clarify", unsupported: "Unsupported",
  insufficient_context: "Missing context", error: "Could not complete",
};
const errors = {
  missing_api_key: "OpenAI is not configured. Set OPENAI_API_KEY in the server's local .env and restart the API.",
  configuration_error: "The server configuration is incomplete. Check its provider and database settings.",
  index_missing: "The knowledge index is missing. Run the knowledge ingestion job, then ask again.",
  index_mismatch: "The knowledge index does not match the embedding settings. Reindex it before asking again.",
  llm_authentication: "The language provider could not authenticate. Check the server-side API key.",
  embedding_authentication: "The embedding provider could not authenticate. Check the server-side API key.",
  llm_rate_limit: "The language provider has reached a usage limit. Check account limits before retrying.",
  embedding_rate_limit: "The embedding provider has reached a usage limit. Check account limits before retrying.",
  database_unavailable: "The database is unavailable. Check that it is running and try again.",
  database_timeout: "The database request timed out. Try a smaller time period or a simpler question.",
  llm_timeout: "The language provider timed out. You can try again.",
  embedding_timeout: "The documentation search timed out. You can try again.",
  llm_unavailable: "The language provider is unavailable. Try again later.",
  embedding_unavailable: "The embedding provider is unavailable. Try again later.",
  deadline_exceeded: "The question reached its time limit. Try a simpler question or a smaller time period.",
  sql_retry_budget_exhausted: "The SQL could not be corrected within the retry limit. Review the query attempts below or rephrase your question.",
  sql_budget_exhausted: "The question reached its SQL-attempt limit. Try asking for one metric at a time.",
  tool_budget_exhausted: "The question reached its tool-call limit. Try asking for one metric at a time.",
  llm_budget_exhausted: "The question reached its model budget. Try a more focused question.",
  llm_context_budget: "The question exceeded the context budget. Try requesting a smaller result.",
  unknown_column: "A referenced column was unavailable.",
  forbidden_sql: "The proposed SQL was rejected by the read-only policy.",
  invalid_sql: "The proposed SQL could not be parsed.",
  timeout: "The query reached its database timeout.",
  http_429: "Another question is already running. Wait for it to finish, then try again.",
  http_422: "The question was rejected. Enter valid text within the displayed byte limit.",
  network_error: "Could not reach the server. Check the connection before trying again; the server may still be processing the question.",
  browser_timeout: "The browser stopped waiting. The server may still be processing the question; wait before trying again.",
  invalid_response: "The server returned an unexpected response. Check the server and try again.",
};

function node(tag, text, className) {
  const element = document.createElement(tag);
  // All model, SQL and source text stays literal. Never interpret it as HTML.
  if (text !== undefined) element.textContent = String(text);
  if (className) element.className = className;
  return element;
}

function errorMessage(category) {
  return Object.hasOwn(errors, category) ? errors[category] : "The request could not be completed. Try rephrasing your question.";
}

function notice(messages, kind = "") {
  const box = node("div", undefined, `notice ${kind}`);
  if (messages.length === 1) box.append(node("p", messages[0]));
  else {
    const list = node("ul");
    messages.forEach(message => list.append(node("li", message)));
    box.append(list);
  }
  return box;
}

function updateInput() {
  const bytes = encoder.encode(question.value).length;
  const invalid = bytes > 2000 || question.value.includes("\0");
  document.querySelector("#byte-count").textContent = `${bytes} / 2000 bytes`;
  question.setAttribute("aria-invalid", String(invalid));
  inputError.hidden = !invalid;
  inputError.textContent = invalid ? "Use at most 2000 UTF-8 bytes and remove invalid characters." : "";
  submit.disabled = busy || !contextReady || invalid || !question.value.trim();
}

async function requestJSON(url, options = {}, timeout = 130000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal, credentials: "same-origin" });
    if (!response.ok) throw new Error(`http_${response.status}`);
    try { return await response.json(); }
    catch { throw new Error("invalid_response"); }
  } catch (error) {
    if (controller.signal.aborted) throw new Error("browser_timeout");
    if (error instanceof TypeError) throw new Error("network_error");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function loadContext() {
  const retry = document.querySelector("#retry-context");
  retry.hidden = true;
  try {
    const data = await requestJSON("/demo", {}, 10000);
    const date = new Date(data.reference_date);
    if (data.synthetic !== true || !Number.isFinite(date.getTime()) || typeof data.dataset_version !== "string") {
      throw new Error("invalid_response");
    }
    document.querySelector("#reference-date").textContent = `Reference date · ${date.toISOString().slice(0, 10)} UTC`;
    document.querySelector("#dataset-label").textContent = `${data.dataset_version} · ${data.currency}`;
    const lastMonth = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() - 1, 1));
    const month = new Intl.DateTimeFormat("en", { month: "long", year: "numeric", timeZone: "UTC" }).format(lastMonth);
    document.querySelector("#period-note").textContent = `“Last month” means ${month}. All periods use UTC.`;
    contextReady = true;
  } catch {
    contextReady = false;
    document.querySelector("#reference-date").textContent = "Demo context unavailable. Reload before asking a question.";
    retry.hidden = false;
  }
  updateInput();
}

function queryAnchor(id) {
  return /^sql_[1-3]$/.test(id) ? `query-${id}` : null;
}

function renderQueries(queries) {
  const section = node("section");
  const heading = node("h3", "SQL & results", "evidence-heading");
  heading.append(node("span", `${queries.length} query attempt${queries.length === 1 ? "" : "s"}`));
  section.append(heading);
  queries.forEach(query => {
    const card = node("article", undefined, "query");
    if (queryAnchor(query.query_id)) card.id = queryAnchor(query.query_id);
    const header = node("div", undefined, "query-header");
    header.append(node("strong", query.query_id), node("span", query.status === "ok" ? "Executed" : "Failed / rejected"));
    card.append(header);
    if (query.executed_sql) {
      const details = node("details");
      details.append(node("summary", "View executed SQL"), node("pre", query.executed_sql, "sql"));
      card.append(details);
    }
    if (query.status !== "ok") {
      card.append(notice([errorMessage(query.error?.category)], "error"));
    } else {
      const scroller = node("div", undefined, "table-scroll");
      scroller.tabIndex = 0;
      scroller.setAttribute("role", "region");
      scroller.setAttribute("aria-label", `Results for ${query.query_id}`);
      const table = node("table");
      table.append(node("caption", `Results for ${query.query_id} · ${(query.rows || []).length} returned rows`));
      const head = node("thead");
      const headerRow = node("tr");
      (query.columns || []).forEach(column => {
        const th = node("th", column.name);
        th.scope = "col";
        headerRow.append(th);
      });
      head.append(headerRow);
      table.append(head);
      const body = node("tbody");
      (query.rows || []).forEach(row => {
        const tr = node("tr");
        row.forEach(value => tr.append(node("td", value === null ? "NULL (undefined)" : value)));
        body.append(tr);
      });
      table.append(body);
      scroller.append(table);
      card.append(scroller);
      if (!query.rows?.length) card.append(node("p", "No rows returned.", "query-note"));
    }
    if (query.truncated) {
      card.append(notice([`Results are truncated (${(query.truncation_reasons || []).join(", ") || "result limit"}). This table is a sample, not a complete total.`]));
    }
    section.append(card);
  });
  return section;
}

function renderSources(sources) {
  const section = node("section");
  section.append(node("h3", "Sources", "evidence-heading"));
  sources.forEach(source => {
    const details = node("details", undefined, "source");
    const summary = node("summary", source.heading || "Documentation source");
    summary.append(node("span", source.citation || source.source_path || source.source_id, "citation"));
    details.append(summary, node("div", source.content || "No source text returned.", "source-content"));
    section.append(details);
  });
  return section;
}

function renderRun(data) {
  const details = node("details", undefined, "run-details");
  details.append(node("summary", "Run details"));
  const pieces = [];
  if (Number.isFinite(data.duration_ms)) pieces.push(`${(data.duration_ms / 1000).toFixed(2)} seconds`);
  if (data.usage?.model) pieces.push(data.usage.model);
  if (Number.isFinite(data.usage?.input_tokens)) pieces.push(`${data.usage.input_tokens} input tokens`);
  if (Number.isFinite(data.usage?.output_tokens)) pieces.push(`${data.usage.output_tokens} output tokens`);
  if (data.usage?.usage_complete === false) pieces.push("Usage incomplete");
  details.append(node("p", pieces.join(" · ") || "No usage details returned.", "run-meta"));
  if (data.demo_reference_date) details.append(node("p", `Answer reference date: ${data.demo_reference_date} · ${data.dataset_version || ""}`, "run-meta"));
  const trace = node("ul", undefined, "trace");
  (data.trace || []).forEach(entry => trace.append(node("li", `${entry.tool} · ${entry.status} · ${entry.duration_ms} ms`)));
  details.append(trace);
  return details;
}

function renderAnswer(data, asked) {
  if (!data || !Object.hasOwn(statusLabels, data.status)) throw new Error("invalid_response");
  // Build detached so a malformed response cannot leave half an answer visible.
  const fragment = document.createDocumentFragment();
  fragment.append(node("p", asked, "answer-question"));
  if (data.output_kind && data.output_kind !== "synthetic_analytics") {
    fragment.append(node("p", `Labeled output: ${data.output_kind}`, "fixture-label"));
  }
  if (data.status === "error") fragment.append(notice([errorMessage(data.error?.category)], "error"));
  else fragment.append(node("p", data.explanation || "No explanation returned.", "explanation"));
  if (data.status === "clarification") {
    fragment.append(notice(["Edit your full question to include the requested detail, then ask again."]));
  }
  if (data.facts?.length) {
    const facts = node("div", undefined, "facts");
    data.facts.forEach(fact => {
      const card = node("div", undefined, "fact");
      card.append(node("div", fact.undefined || fact.value === null ? "Undefined" : fact.value, "fact-value"), node("p", fact.label, "fact-label"));
      const anchor = queryAnchor(fact.query_id);
      if (anchor && data.queries?.some(query => query.query_id === fact.query_id)) {
        const link = node("a", `${fact.query_id} · row ${fact.row + 1}, column ${fact.column + 1}`);
        link.href = `#${anchor}`;
        card.append(link);
      }
      facts.append(card);
    });
    fragment.append(facts);
  }
  const notes = [...(data.limitations || []), ...(data.warnings || [])];
  if (notes.length) fragment.append(notice(notes));
  if (data.queries?.length) fragment.append(renderQueries(data.queries));
  if (data.sources?.length) fragment.append(renderSources(data.sources));
  if (data.usage || data.trace?.length) fragment.append(renderRun(data));
  content.replaceChildren(fragment);
  badge.textContent = statusLabels[data.status];
  badge.dataset.status = data.status;
  statusText.textContent = `${statusLabels[data.status]}. Results are available in Explore the answer.`;
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  updateInput();
  if (submit.disabled || busy) return;
  const asked = question.value.trim();
  busy = true;
  question.disabled = true;
  document.querySelectorAll(".example").forEach(button => { button.disabled = true; });
  updateInput();
  document.querySelector(".answer-panel").setAttribute("aria-busy", "true");
  badge.textContent = "Working";
  delete badge.dataset.status;
  const loading = node("div", undefined, "empty-state");
  loading.append(node("div", undefined, "loading-indicator"), node("h3", "Analyzing your question…"), node("p", "This can take a moment. Your answer will appear here."));
  content.replaceChildren(loading);
  statusText.textContent = "Analyzing your question. Please wait.";
  try {
    const data = await requestJSON("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: asked }),
    });
    renderAnswer(data, asked);
  } catch (error) {
    renderAnswer({ status: "error", error: { category: error.message } }, asked);
  } finally {
    busy = false;
    question.disabled = false;
    document.querySelectorAll(".example").forEach(button => { button.disabled = false; });
    document.querySelector(".answer-panel").setAttribute("aria-busy", "false");
    updateInput();
    document.querySelector("#answer-heading").focus({ preventScroll: true });
    if (window.matchMedia("(max-width: 700px)").matches) {
      document.querySelector("#answer-heading").scrollIntoView({ block: "start" });
    }
  }
});

question.addEventListener("input", updateInput);
question.addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    form.requestSubmit();
  }
});
document.querySelectorAll(".example").forEach(button => button.addEventListener("click", () => {
  question.value = button.dataset.question;
  updateInput();
  question.focus();
}));
document.querySelector("#retry-context").addEventListener("click", loadContext);
loadContext();
