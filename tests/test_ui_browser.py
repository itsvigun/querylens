"""Opt-in Chromium over real HTTP with labeled offline answers; never calls a provider."""

import copy
import os
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from app.config import Settings
from app.main import create_app

pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(os.getenv("QUERYLENS_BROWSER") != "1", reason="Opt-in Chromium checks"),
]
INJECTION = '<img src=x onerror="window.injected=true"><script>window.injected=true</script>'
ANSWER = {
    "status": "answered",
    "output_kind": "offline_ui_fixture",
    "explanation": "Completed-order revenue for September. " + INJECTION,
    "facts": [
        {
            "label": "Revenue, EUR",
            "query_id": "sql_1",
            "row": 0,
            "column": 0,
            "value": "9007199254740993.01",
            "undefined": False,
        },
        {
            "label": "Unavailable denominator",
            "query_id": "sql_1",
            "row": 0,
            "column": 1,
            "value": None,
            "undefined": True,
        },
    ],
    "queries": [
        {
            "query_id": "sql_1",
            "status": "ok",
            "executed_sql": "SELECT '" + INJECTION + "'",
            "columns": [{"name": "value", "type": "numeric"}, {"name": "value", "type": "numeric"}],
            "rows": [["9007199254740993.01", None]],
            "row_count": 1,
            "truncated": False,
        }
    ],
    "sources": [
        {
            "source_id": "offline:revenue",
            "heading": "Metrics > Revenue",
            "content": INJECTION,
            "source_path": "knowledge/metrics.md",
            "citation": "knowledge/metrics.md#L8-L17",
        }
    ],
    "limitations": ["Labeled offline browser fixture; not a live analytics answer."],
    "warnings": [],
    "duration_ms": 100,
    "usage": {"model": "offline", "input_tokens": 0, "output_tokens": 0, "usage_complete": True},
    "trace": [{"tool": "execute_sql", "status": "ok", "duration_ms": 5}],
}


@pytest.fixture(scope="module")
def ui_server():
    state = {"answer": copy.deepcopy(ANSWER), "calls": [], "hold": None}

    def offline_ask(question):
        state["calls"].append(question)
        if state["hold"]:
            assert state["hold"].wait(10), "Browser test did not release its request"
        return copy.deepcopy(state["answer"])

    settings = Settings(_env_file=None, postgres_password="offline-test-password", postgres_port=1)
    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("app.api.chat.ask", offline_ask)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert server.started
                yield f"http://127.0.0.1:{sock.getsockname()[1]}", app, state
            finally:
                if state["hold"]:
                    state["hold"].set()
                server.should_exit = True
                thread.join(10)
                assert not thread.is_alive()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def ui(browser, ui_server):
    from playwright.sync_api import expect

    url, app, state = ui_server
    state.update(answer=copy.deepcopy(ANSWER), calls=[], hold=None)
    page = browser.new_page(viewport={"width": 1280, "height": 960})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url)
    expect(page.locator("#reference-date")).to_contain_text("2026-10-01 UTC")
    yield page, state, app
    if state["hold"]:
        state["hold"].set()
    page.close()
    assert not errors


def ask(page, question="September revenue?"):
    page.get_by_label("Your question", exact=True).fill(question)
    page.get_by_role("button", name="Ask QueryLens").click()


@pytest.mark.parametrize("width", [1280, 390])
def test_answer_evidence_precision_and_untrusted_text(ui, width):
    from playwright.sync_api import expect

    page, state, _ = ui
    page.set_viewport_size({"width": width, "height": 960})
    page.get_by_role("button", name="Revenue last month").click()
    assert state["calls"] == []
    screenshots = os.getenv("QUERYLENS_SCREENSHOT_DIR")
    if screenshots:
        Path(screenshots).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=f"{screenshots}/ui-empty-{width}.png", full_page=True)
    page.get_by_role("button", name="Ask QueryLens").click()
    expect(page.locator("#answer-badge")).to_have_text("Answered")
    assert state["calls"] == ["What was completed-order revenue in September, in EUR?"]
    expect(page.locator(".fact-value").first).to_have_text("9007199254740993.01")
    expect(page.locator(".fact-value").nth(1)).to_have_text("Undefined")
    expect(page.get_by_role("cell", name="NULL (undefined)", exact=True)).to_be_visible()
    assert page.get_by_role("columnheader", name="value", exact=True).count() == 2
    page.get_by_text("View executed SQL", exact=True).click()
    expect(page.locator(".sql")).to_contain_text(INJECTION)
    page.locator(".source summary").click()
    expect(page.locator(".source-content")).to_have_text(INJECTION)
    expect(page.locator(".citation")).to_have_text("knowledge/metrics.md#L8-L17")
    assert page.locator("#answer-content img, #answer-content script").count() == 0
    assert page.evaluate("window.injected") is None
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if screenshots:
        page.screenshot(path=f"{screenshots}/ui-answer-{width}.png", full_page=True)


@pytest.mark.parametrize(
    "status,label",
    [
        ("clarification", "Clarify"),
        ("unsupported", "Unsupported"),
        ("insufficient_context", "Missing context"),
    ],
)
def test_non_answer_and_editing_full_question(ui, status, label):
    from playwright.sync_api import expect

    page, state, _ = ui
    state["answer"] = {
        "status": status,
        "explanation": "Please specify a period.",
        "facts": [],
        "sources": [],
        "output_kind": "offline_ui_fixture",
    }
    ask(page, "Revenue?")
    expect(page.locator("#answer-badge")).to_have_text(label)
    expect(page.get_by_label("Your question", exact=True)).to_have_value("Revenue?")
    if status == "clarification":
        expect(
            page.locator("#answer-content").get_by_text("Edit your full question", exact=False)
        ).to_be_visible()
    state["answer"] = copy.deepcopy(ANSWER)
    ask(page, "Revenue in September?")
    expect(page.locator("#answer-badge")).to_have_text("Answered")
    assert state["calls"] == ["Revenue?", "Revenue in September?"]


def test_utf8_input_limit_and_single_active_submission(ui):
    from playwright.sync_api import expect

    page, state, _ = ui
    field = page.get_by_label("Your question", exact=True)
    field.fill("я" * 1001)
    expect(page.locator("#byte-count")).to_have_text("2002 / 2000 bytes")
    expect(page.get_by_role("button", name="Ask QueryLens")).to_be_disabled()
    assert state["calls"] == []
    state["hold"] = threading.Event()
    ask(page)
    expect(page.get_by_role("heading", name="Analyzing your question…")).to_be_visible()
    expect(field).to_be_disabled()
    page.evaluate("document.querySelector('#question-form').requestSubmit()")
    assert len(state["calls"]) == 1
    state["hold"].set()
    expect(page.locator("#answer-badge")).to_have_text("Answered")
    assert len(state["calls"]) == 1


def test_empty_truncated_result_and_wide_table(ui):
    from playwright.sync_api import expect

    page, state, _ = ui
    query = state["answer"]["queries"][0]
    state["answer"]["facts"] = []
    query.update(rows=[], row_count=0, truncated=True, truncation_reasons=["byte_limit"])
    ask(page)
    expect(page.get_by_text("No rows returned.", exact=True)).to_be_visible()
    expect(page.get_by_text("Results are truncated", exact=False)).to_be_visible()
    query.update(
        columns=[{"name": f"very_long_column_{n}"} for n in range(40)],
        rows=[["long value " * 20 for _ in range(40)]],
        row_count=1,
    )
    page.set_viewport_size({"width": 390, "height": 844})
    ask(page)
    expect(page.get_by_role("columnheader")).to_have_count(40)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.locator(".table-scroll").evaluate("el => el.scrollWidth > el.clientWidth")


def test_busy_http_error_and_recovery(ui):
    from playwright.sync_api import expect

    page, state, app = ui
    app.state.chat_lock.acquire()
    try:
        ask(page)
        expect(
            page.get_by_text("Another question is already running.", exact=False)
        ).to_be_visible()
        assert state["calls"] == []
    finally:
        app.state.chat_lock.release()
    page.get_by_role("button", name="Ask QueryLens").click()
    expect(page.locator("#answer-badge")).to_have_text("Answered")


@pytest.mark.parametrize(
    "category,message",
    [
        ("missing_api_key", "OpenAI is not configured."),
        ("index_missing", "The knowledge index is missing."),
        ("deadline_exceeded", "The question reached its time limit."),
        ("sql_retry_budget_exhausted", "The SQL could not be corrected"),
    ],
)
def test_backend_failure_removes_stale_answer(ui, category, message):
    from playwright.sync_api import expect

    page, state, _ = ui
    ask(page)
    expect(page.locator("#answer-badge")).to_have_text("Answered")
    state["answer"] = {"status": "error", "error": {"category": category}}
    ask(page)
    expect(page.get_by_text(message, exact=False)).to_be_visible()
    expect(page.locator(".fact")).to_have_count(0)
    expect(page.get_by_role("button", name="Ask QueryLens")).to_be_enabled()


@pytest.mark.parametrize("failure", ["network", "bad_json", "bad_status", "http_500"])
def test_transport_failures_are_safe_and_retry_is_manual(ui, failure):
    from playwright.sync_api import expect

    page, state, _ = ui

    def fail(route):
        if failure == "network":
            route.abort()
        elif failure == "bad_json":
            route.fulfill(status=200, content_type="text/html", body=INJECTION)
        elif failure == "bad_status":
            route.fulfill(json={"status": "private-error-marker"})
        else:
            route.fulfill(status=500, body="private-error-marker")

    page.route("**/api/chat", fail)
    ask(page)
    expect(page.locator("#answer-badge")).to_have_text("Could not complete")
    expect(page.get_by_role("button", name="Ask QueryLens")).to_be_enabled()
    assert "private-error-marker" not in page.locator("#answer-content").inner_text()
    assert state["calls"] == []


def test_wait_timeout_does_not_automatically_retry(ui):
    from playwright.sync_api import expect

    page, state, _ = ui
    pending = []
    page.route("**/api/chat", lambda route: pending.append(route))
    page.clock.install()
    ask(page)
    expect(page.get_by_role("heading", name="Analyzing your question…")).to_be_visible()
    page.clock.fast_forward(130001)
    expect(page.get_by_text("The browser stopped waiting.", exact=False)).to_be_visible()
    assert len(pending) == 1 and state["calls"] == []


def test_demo_context_failure_and_reload(ui):
    from playwright.sync_api import expect

    page, state, _ = ui
    page.route("**/demo", lambda route: route.fulfill(status=503))
    page.reload()
    expect(page.get_by_role("button", name="Reload context")).to_be_visible()
    page.get_by_label("Your question", exact=True).fill("Revenue?")
    expect(page.get_by_role("button", name="Ask QueryLens")).to_be_disabled()
    page.unroute("**/demo")
    page.get_by_role("button", name="Reload context").click()
    expect(page.locator("#reference-date")).to_contain_text("2026-10-01 UTC")
    expect(page.get_by_role("button", name="Ask QueryLens")).to_be_enabled()
    assert state["calls"] == []
