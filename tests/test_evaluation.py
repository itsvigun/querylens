"""Independent grader regressions: a self-consistent wrong answer must fail."""

from copy import deepcopy

import pytest

from evals.runner import grade, load_cases, rows_equal, run_evaluation
from scripts.evaluate import main
from scripts.verify_data import expected_report


def sample():
    case = load_cases()["cases"][0]
    source = {"source_path": "knowledge/metrics.md", "heading": "Metric definitions > Revenue"}
    result = {
        "status": "answered",
        "facts": [
            {"query_id": "sql_1", "row": 0, "column": 0, "value": "336080.07", "undefined": False}
        ],
        "sources": [source],
        "queries": [{"status": "ok", "query_id": "sql_1", "rows": [["336080.07"]]}],
    }
    return case, result, [{"sources": [source]}]


def test_dataset_and_independent_metric_references():
    suite = load_cases()
    assert len(suite["cases"]) == 20
    assert sum(c["live_eligible"] for c in suite["cases"]) == 16
    assert suite["cases"][0]["expected_rows"] == [
        [expected_report()["periods"]["september"]["revenue"]]
    ]
    assert next(c for c in suite["cases"] if c["id"] == "undefined_arpu")["expected_rows"] == [
        ["0.00", 0, None]
    ]


def test_correct_values_do_not_require_sql_string_equality():
    case, result, searches = sample()
    result["queries"][0]["executed_sql"] = "A differently written reviewed query"
    assert grade(case, result, searches)["passed"]
    assert rows_equal(
        [["PL", 3, "10.0"], ["DE", 4, "9.0"]], [["DE", 4, "9.00"], ["PL", 3, "10.00"]], 8
    )
    assert not rows_equal([[False]], [[0]], 8)
    assert not rows_equal([[None]], [["0"]], 8)
    assert not rows_equal([[1]], [[1], [1]], 8)
    assert not rows_equal([[1, 2]], [[2, 1]], 8)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_metric",
        "wrong_fact",
        "wrong_status",
        "missing_source",
        "missing_citation",
        "missing_fact",
    ],
)
def test_wrong_or_incomplete_answer_fails(mutation):
    case, result, searches = sample()
    if mutation == "wrong_metric":
        result["queries"][0]["rows"] = [["999.00"]]
        result["facts"][0]["value"] = "999.00"
    elif mutation == "wrong_fact":
        result["facts"][0]["value"] = "999.00"
    elif mutation == "wrong_status":
        result["status"] = "clarification"
    elif mutation == "missing_source":
        searches = []
    elif mutation == "missing_citation":
        result["sources"] = []
    else:
        result["facts"] = []
    scored = grade(case, result, searches)
    assert not scored["passed"]
    if mutation == "wrong_metric":
        assert scored["fact_provenance"] and not scored["metric_values_correct"]


def test_null_and_duplicate_cell_coverage():
    case, result, searches = sample()
    case = deepcopy(case)
    case["expected_rows"] = [[None, 0, 0]]
    result["queries"][0]["rows"] = [[None, 0, 0]]
    result["facts"] = [
        {"query_id": "sql_1", "row": 0, "column": i, "value": value, "undefined": value is None}
        for i, value in enumerate([None, 0, 0])
    ]
    assert grade(case, result, searches)["passed"]
    result["facts"].pop()
    assert not grade(case, result, searches)["passed"]


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--live"],
        ["--offline", "--max-input-bytes", "1000"],
        ["--offline", "--cases", "unknown"],
        ["--offline", "--cases", "arpu", "arpu"],
        [
            "--live",
            "--cases",
            "deadline",
            "--max-input-bytes",
            "40000",
            "--max-output-tokens",
            "2000",
            "--max-embedding-input-bytes",
            "16000",
        ],
    ],
)
def test_cli_refuses_invalid_mode_selection_or_unbudgeted_live(args, monkeypatch):
    monkeypatch.setattr(
        "scripts.evaluate.run_evaluation", lambda *a, **k: pytest.fail("must not run")
    )
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


def test_live_budget_validation_precedes_database_or_provider(monkeypatch):
    monkeypatch.setattr(
        "evals.runner.DatabaseTools", lambda *a, **k: pytest.fail("must not connect")
    )
    with pytest.raises(ValueError):
        run_evaluation(load_cases()["cases"][:1], live=True)


def test_cli_safe_failure_and_failing_report_exit(monkeypatch, capsys, tmp_path):
    def fail(*a, **k):
        raise RuntimeError("sk-private-secret postgres://owner:password@host")

    monkeypatch.setattr("scripts.evaluate.run_evaluation", fail)
    assert main(["--offline"]) == 1
    assert "private-secret" not in capsys.readouterr().err
    monkeypatch.setattr("scripts.evaluate.run_evaluation", lambda *a, **k: {"failed": 1})
    destination = tmp_path / "report.json"
    assert main(["--offline", "--output", str(destination)]) == 1
    with pytest.raises(SystemExit):
        main(["--offline", "--output", str(destination)])


def test_expected_error_requires_bounded_attempts():
    case = next(c for c in load_cases()["cases"] if c["id"] == "deadline")
    result = {
        "status": "error",
        "error": {"category": "deadline_exceeded"},
        "workflow": case["expected_workflow"].copy(),
    }
    assert grade(case, result, [])["passed"]
    result["workflow"]["sql_attempts"] = 4
    assert not grade(case, result, [])["passed"]
