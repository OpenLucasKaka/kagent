import json
import subprocess

from self_correcting_langgraph_agent.ops.metrics import summarize_metrics_file


def test_summarize_metrics_file_reports_trends(tmp_path):
    metrics_path = tmp_path / "metrics.jsonl"
    metrics_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "iteration": 1,
                        "duration_seconds": "10",
                        "status": "passed",
                        "checks_exit_code": 0,
                        "evaluator_passed": 6,
                        "evaluator_failed": 0,
                        "evaluator_slowest_case": "multi_step_success",
                        "evaluator_recovered_cases": "2",
                        "evaluator_recovery_rate": "0.33",
                        "evaluator_category_counts": {"tool": "3", "recovery": "2"},
                    }
                ),
                json.dumps(
                    {
                        "iteration": 2,
                        "duration_seconds": "20",
                        "status": "failed",
                        "checks_exit_code": 1,
                        "evaluator_passed": 5,
                        "evaluator_failed": 1,
                        "evaluator_slowest_case": "retry_budget_failure",
                        "evaluator_recovered_cases": "1",
                        "evaluator_recovery_rate": "0.17",
                        "evaluator_category_counts": {"tool": "2", "failure": "1"},
                    }
                ),
                json.dumps(
                    {
                        "iteration": 3,
                        "duration_seconds": "12",
                        "status": "passed",
                        "checks_exit_code": 0,
                        "evaluator_passed": 6,
                        "evaluator_failed": 0,
                        "evaluator_slowest_case": "multi_step_success",
                        "evaluator_recovered_cases": "2",
                        "evaluator_recovery_rate": "0.33",
                        "evaluator_category_counts": {"tool": "3", "recovery": "2"},
                    }
                ),
            ]
        )
        + "\n"
    )

    assert summarize_metrics_file(metrics_path) == {
        "iterations": "3",
        "passed": "2",
        "failed": "1",
        "pass_rate": "0.67",
        "health": "degraded",
        "metrics_file_found": "true",
        "average_duration_seconds": "14.00",
        "latest_status": "passed",
        "recent_health": "recovering",
        "consecutive_passes": "1",
        "recent_statuses": ["passed", "failed", "passed"],
        "failed_iterations": ["2"],
        "malformed_lines": [],
        "latest_evaluator_passed": "6",
        "latest_evaluator_failed": "0",
        "latest_slowest_case": "multi_step_success",
        "latest_recovered_cases": "2",
        "latest_recovery_rate": "0.33",
        "latest_category_counts": {"recovery": "2", "tool": "3"},
        "recommendations": [
            "inspect failed iterations: 2",
            "latest run is passing after previous failures",
        ],
    }


def test_metrics_module_prints_json_summary(tmp_path):
    metrics_path = tmp_path / "metrics.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "iteration": 1,
                "duration_seconds": "7",
                "status": "passed",
                "checks_exit_code": 0,
                "evaluator_passed": 6,
                "evaluator_failed": 0,
                "evaluator_slowest_case": "multi_step_success",
                "evaluator_recovered_cases": "2",
                "evaluator_recovery_rate": "0.33",
                "evaluator_category_counts": {"tool": "3", "recovery": "2"},
            }
        )
        + "\n"
    )

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.metrics",
            str(metrics_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["iterations"] == "1"
    assert payload["pass_rate"] == "1.00"
    assert payload["health"] == "healthy"
    assert payload["latest_status"] == "passed"
    assert payload["recent_health"] == "healthy"
    assert payload["consecutive_passes"] == "1"
    assert payload["recent_statuses"] == ["passed"]
    assert payload["latest_slowest_case"] == "multi_step_success"
    assert payload["latest_recovered_cases"] == "2"
    assert payload["latest_recovery_rate"] == "0.33"
    assert payload["latest_category_counts"] == {"recovery": "2", "tool": "3"}
    assert payload["malformed_lines"] == []
    assert payload["recommendations"] == []


def test_metrics_module_can_write_summary_to_output_file(tmp_path):
    metrics_path = tmp_path / "metrics.jsonl"
    output_path = tmp_path / "summary.json"
    metrics_path.write_text(
        json.dumps(
            {
                "iteration": 1,
                "duration_seconds": "7",
                "status": "passed",
                "checks_exit_code": 0,
            }
        )
        + "\n"
    )

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.metrics",
            str(metrics_path),
            "--output",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stderr == ""
    assert json.loads(output_path.read_text()) == json.loads(completed.stdout)


def test_metrics_module_can_fail_when_recent_health_does_not_match(tmp_path):
    metrics_path = tmp_path / "metrics.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "iteration": 1,
                "duration_seconds": "7",
                "status": "failed",
                "checks_exit_code": 1,
            }
        )
        + "\n"
    )

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.metrics",
            str(metrics_path),
            "--require-recent-health",
            "healthy",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["recent_health"] == "failing"


def test_summarize_metrics_file_reports_missing_file(tmp_path):
    metrics_path = tmp_path / "missing.jsonl"

    summary = summarize_metrics_file(metrics_path)

    assert summary["iterations"] == "0"
    assert summary["health"] == "unknown"
    assert summary["recent_health"] == "unknown"
    assert summary["metrics_file_found"] == "false"
    assert summary["recommendations"] == [
        f"metrics file not found: {metrics_path}"
    ]


def test_summarize_metrics_file_reports_malformed_lines(tmp_path):
    metrics_path = tmp_path / "metrics.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "iteration": 1,
                "duration_seconds": "4",
                "status": "passed",
                "checks_exit_code": 0,
                "evaluator_passed": 8,
                "evaluator_failed": 0,
            }
        )
        + "\n"
        + "{not-json}\n"
    )

    summary = summarize_metrics_file(metrics_path)

    assert summary["iterations"] == "1"
    assert summary["passed"] == "1"
    assert summary["health"] == "degraded"
    assert summary["recent_health"] == "healthy"
    assert summary["malformed_lines"] == ["2"]
    assert summary["recommendations"] == ["inspect malformed metrics lines: 2"]


def test_summarize_metrics_file_reports_non_object_lines_as_malformed(tmp_path):
    metrics_path = tmp_path / "metrics.jsonl"
    metrics_path.write_text("[]\n")

    summary = summarize_metrics_file(metrics_path)

    assert summary["iterations"] == "0"
    assert summary["health"] == "failing"
    assert summary["recent_health"] == "unknown"
    assert summary["malformed_lines"] == ["1"]


def test_summarize_metrics_file_recommends_category_count_visibility(tmp_path):
    metrics_path = tmp_path / "metrics.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "iteration": 1,
                "duration_seconds": "5",
                "status": "passed",
                "checks_exit_code": 0,
                "evaluator_passed": 14,
                "evaluator_failed": 0,
            }
        )
        + "\n"
    )

    summary = summarize_metrics_file(metrics_path)

    assert summary["latest_category_counts"] == {}
    assert summary["recent_health"] == "healthy"
    assert summary["recommendations"] == [
        "review continuous metrics wiring; latest evaluator category counts are missing"
    ]


def test_summarize_metrics_file_recommends_check_log_when_latest_failed_before_evaluator(tmp_path):
    metrics_path = tmp_path / "metrics.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "iteration": 1,
                "duration_seconds": "5",
                "status": "failed",
                "checks_exit_code": 1,
                "evaluator_passed": None,
                "evaluator_failed": None,
            }
        )
        + "\n"
    )

    summary = summarize_metrics_file(metrics_path)

    assert summary["recommendations"] == [
        "inspect failed iterations: 1",
        "inspect check log; latest run failed before a fresh evaluator report",
    ]
    assert summary["recent_health"] == "failing"


def test_summarize_metrics_file_accepts_fractional_durations(tmp_path):
    metrics_path = tmp_path / "metrics.jsonl"
    metrics_path.write_text(
        json.dumps(
            {
                "iteration": 1,
                "duration_seconds": "1.5",
                "status": "passed",
                "checks_exit_code": 0,
                "evaluator_passed": 10,
                "evaluator_failed": 0,
            }
        )
        + "\n"
    )

    summary = summarize_metrics_file(metrics_path)

    assert summary["average_duration_seconds"] == "1.50"
    assert summary["health"] == "healthy"
    assert summary["recent_health"] == "healthy"
