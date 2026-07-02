import json
import subprocess

import pytest

from self_correcting_langgraph_agent.eval.evaluator import (
    _exit_code_for_report,
    _run_case,
    evaluate_agent,
    registered_evaluation_cases,
)


def test_evaluator_scores_core_agent_scenarios():
    report = evaluate_agent()

    assert report["passed"] == 14
    assert report["failed"] == 0
    assert report["recovered_cases"] == "4"
    assert report["recovery_rate"] == "0.29"
    assert report["category_counts"] == {
        "failure": "3",
        "recovery": "4",
        "tool": "6",
        "workflow": "1",
    }
    assert float(report["duration_seconds"]) >= 0
    assert report["slowest_case"] in [case["name"] for case in report["cases"]]
    assert [case["name"] for case in report["cases"]] == [
        "multi_step_success",
        "self_correction_success",
        "retry_budget_failure",
        "uppercase_tool_success",
        "unsupported_plan_failure",
        "empty_answer_recovery",
        "per_step_retry_budget_success",
        "multiplication_tool_success",
        "reverse_text_tool_success",
        "lowercase_text_tool_success",
        "trim_text_tool_success",
        "subtraction_tool_success",
        "tool_error_recovery",
        "empty_plan_failure",
    ]
    assert all(case["passed"] for case in report["cases"])
    assert all(case["invariant_errors"] == [] for case in report["cases"])
    cases_by_name = {case["name"]: case for case in report["cases"]}
    assert cases_by_name["multi_step_success"]["category"] == "workflow"
    assert cases_by_name["multi_step_success"]["summary"]["tool_names"] == [
        "calculate_sum",
        "count_words",
    ]
    assert cases_by_name["multi_step_success"]["summary"]["recovered"] == "false"
    assert cases_by_name["self_correction_success"]["summary"]["recovered"] == "true"
    assert cases_by_name["empty_answer_recovery"]["summary"]["faults"] == ["empty-answer"]
    assert cases_by_name["empty_answer_recovery"]["summary"]["recovered"] == "true"
    assert cases_by_name["empty_answer_recovery"]["summary"]["reflection_reasons"] == [
        "answer was empty"
    ]
    assert cases_by_name["empty_answer_recovery"]["summary"][
        "reflection_reason_counts"
    ] == {"answer was empty": "1"}
    assert cases_by_name["per_step_retry_budget_success"]["retry_count"] == 2
    assert cases_by_name["per_step_retry_budget_success"]["summary"]["recovered"] == "true"
    assert cases_by_name["multiplication_tool_success"]["summary"]["tool_names"] == [
        "multiply_numbers"
    ]
    assert cases_by_name["reverse_text_tool_success"]["summary"]["tool_names"] == [
        "reverse_text"
    ]
    assert cases_by_name["lowercase_text_tool_success"]["summary"]["tool_names"] == [
        "lowercase_text"
    ]
    assert cases_by_name["trim_text_tool_success"]["summary"]["tool_names"] == [
        "trim_text"
    ]
    assert cases_by_name["subtraction_tool_success"]["summary"]["tool_names"] == [
        "subtract_numbers"
    ]
    assert cases_by_name["tool_error_recovery"]["summary"][
        "reflection_reason_counts"
    ] == {"tool execution failed": "1"}
    assert cases_by_name["empty_plan_failure"]["category"] == "failure"
    assert cases_by_name["empty_plan_failure"]["status"] == "failed"
    assert float(cases_by_name["multi_step_success"]["duration_seconds"]) >= 0


def test_evaluator_module_prints_json_report():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.eval.evaluator",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["passed"] == 14
    assert payload["failed"] == 0


def test_evaluator_can_filter_cases_by_category():
    report = evaluate_agent(category="recovery")

    assert report["passed"] == 4
    assert report["failed"] == 0
    assert report["category_counts"] == {"recovery": "4"}
    assert [case["category"] for case in report["cases"]] == [
        "recovery",
        "recovery",
        "recovery",
        "recovery",
    ]


def test_evaluator_can_filter_cases_by_name():
    report = evaluate_agent(case_name="subtraction_tool_success")

    assert report["passed"] == 1
    assert report["failed"] == 0
    assert report["category_counts"] == {"tool": "1"}
    assert [case["name"] for case in report["cases"]] == ["subtraction_tool_success"]


def test_evaluator_module_accepts_category_filter():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.eval.evaluator",
            "--category",
            "recovery",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["passed"] == 4
    assert payload["category_counts"] == {"recovery": "4"}


def test_evaluator_module_accepts_case_filter():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.eval.evaluator",
            "--case",
            "subtraction_tool_success",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["passed"] == 1
    assert [case["name"] for case in payload["cases"]] == ["subtraction_tool_success"]


def test_registered_evaluation_cases_exposes_case_metadata():
    cases = registered_evaluation_cases()

    assert cases[0] == {"name": "multi_step_success", "category": "workflow"}
    assert cases[-1] == {"name": "empty_plan_failure", "category": "failure"}


def test_evaluator_module_can_list_cases_without_running_them():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.eval.evaluator",
            "--list-cases",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["cases"][0] == {
        "name": "multi_step_success",
        "category": "workflow",
    }
    assert "passed" not in payload


def test_evaluator_module_can_write_report_to_output_file(tmp_path):
    output_path = tmp_path / "evaluator.json"
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.eval.evaluator",
            "--case",
            "subtraction_tool_success",
            "--output",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stderr == ""
    assert json.loads(output_path.read_text()) == json.loads(completed.stdout)


def test_evaluator_module_accepts_fail_on_failure_flag_when_report_passes():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.eval.evaluator",
            "--case",
            "subtraction_tool_success",
            "--fail-on-failure",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["failed"] == 0


def test_evaluator_failure_exit_code_is_opt_in():
    assert _exit_code_for_report({"failed": 1}, fail_on_failure=False) == 0
    assert _exit_code_for_report({"failed": 1}, fail_on_failure=True) == 1
    assert _exit_code_for_report({"failed": 0}, fail_on_failure=True) == 0


def test_evaluator_rejects_unknown_category_filter():
    with pytest.raises(ValueError, match="unknown evaluator category: typo"):
        evaluate_agent(category="typo")


def test_evaluator_rejects_unknown_case_filter():
    with pytest.raises(ValueError, match="unknown evaluator case: missing_case"):
        evaluate_agent(case_name="missing_case")


def test_evaluator_module_reports_unknown_filter_without_traceback():
    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.eval.evaluator",
            "--category",
            "typo",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "unknown evaluator category: typo" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_run_case_reports_exceptions_as_failed_cases():
    case = _run_case(
        "exploding_case",
        "failure",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        lambda result: True,
    )

    assert case["name"] == "exploding_case"
    assert case["category"] == "failure"
    assert case["passed"] is False
    assert case["status"] == "error"
    assert case["error"] == "boom"
    assert float(case["duration_seconds"]) >= 0
    assert case["invariant_errors"] == []
