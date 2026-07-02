from __future__ import annotations

import argparse
import contextlib
import io
import time
import warnings
from typing import Any, Callable, Dict, List

from self_correcting_langgraph_agent.core.invariants import validate_run_invariants
from self_correcting_langgraph_agent.core.summary import summarize_run
from self_correcting_langgraph_agent.eval.cases import (
    CaseCheck,
    EvaluationCase,
    build_evaluation_cases,
)
from self_correcting_langgraph_agent.utils.json_output import format_and_write_json


def evaluate_agent(category: str = "", case_name: str = "") -> Dict[str, Any]:
    started_at = time.perf_counter()
    warning_sink = io.StringIO()
    with contextlib.redirect_stderr(warning_sink), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from self_correcting_langgraph_agent.core.agent import AgentConfig, AgentStatus, run_agent

        all_cases = build_evaluation_cases(AgentConfig, AgentStatus, run_agent)
        _validate_case_filters(all_cases, category=category, case_name=case_name)
        selected_cases = _filter_cases(
            all_cases,
            category=category,
            case_name=case_name,
        )
        cases = [
            _run_case(item.name, item.category, item.run, item.check)
            for item in selected_cases
        ]
    passed = sum(1 for case in cases if case["passed"])
    recovered_cases = _recovered_case_count(cases)
    return {
        "passed": passed,
        "failed": len(cases) - passed,
        "filters": {"category": category, "case": case_name},
        "recovered_cases": str(recovered_cases),
        "recovery_rate": f"{recovered_cases / len(cases):.2f}" if cases else "0.00",
        "category_counts": _category_counts(cases),
        "duration_seconds": _duration_since(started_at),
        "slowest_case": _slowest_case_name(cases),
        "cases": cases,
    }


def registered_evaluation_cases() -> List[Dict[str, str]]:
    warning_sink = io.StringIO()
    with contextlib.redirect_stderr(warning_sink), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from self_correcting_langgraph_agent.core.agent import AgentConfig, AgentStatus, run_agent

        return [
            {"name": case.name, "category": case.category}
            for case in build_evaluation_cases(AgentConfig, AgentStatus, run_agent)
        ]


def _validate_case_filters(
    cases: List[EvaluationCase],
    *,
    category: str,
    case_name: str,
) -> None:
    if category and category not in {case.category for case in cases}:
        raise ValueError(f"unknown evaluator category: {category}")
    if case_name and case_name not in {case.name for case in cases}:
        raise ValueError(f"unknown evaluator case: {case_name}")


def _filter_cases(
    cases: List[EvaluationCase],
    *,
    category: str,
    case_name: str,
) -> List[EvaluationCase]:
    selected = cases
    if category:
        selected = [case for case in selected if case.category == category]
    if case_name:
        selected = [case for case in selected if case.name == case_name]
    return selected


def _run_case(
    name: str,
    category: str,
    run: Callable[[], Dict[str, Any]],
    check: CaseCheck,
) -> Dict[str, Any]:
    started_at = time.perf_counter()
    try:
        result = run()
    except Exception as exc:
        return {
            "name": name,
            "category": category,
            "passed": False,
            "status": "error",
            "answer": None,
            "retry_count": 0,
            "events": [],
            "invariant_errors": [],
            "summary": {},
            "error": str(exc),
            "duration_seconds": _duration_since(started_at),
        }

    invariant_errors = validate_run_invariants(result)
    return {
        "name": name,
        "category": category,
        "passed": check(result) and not invariant_errors,
        "status": result["status"].value,
        "answer": result.get("answer"),
        "retry_count": result.get("retry_count", 0),
        "events": [event["node"] for event in result.get("events", [])],
        "invariant_errors": invariant_errors,
        "summary": summarize_run(result),
        "error": "",
        "duration_seconds": _duration_since(started_at),
    }


def _duration_since(started_at: float) -> str:
    return f"{time.perf_counter() - started_at:.4f}"


def _slowest_case_name(cases: List[Dict[str, Any]]) -> str:
    if not cases:
        return ""
    return max(cases, key=lambda case: float(case["duration_seconds"]))["name"]


def _recovered_case_count(cases: List[Dict[str, Any]]) -> int:
    return sum(
        1
        for case in cases
        if case.get("summary", {}).get("recovered") == "true"
    )


def _category_counts(cases: List[Dict[str, Any]]) -> Dict[str, str]:
    counts: Dict[str, int] = {}
    for case in cases:
        category = case.get("category", "")
        counts[category] = counts.get(category, 0) + 1
    return {category: str(counts[category]) for category in sorted(counts)}


def _exit_code_for_report(report: Dict[str, Any], *, fail_on_failure: bool) -> int:
    if fail_on_failure and int(report.get("failed", 0)) > 0:
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the self-correcting agent.")
    parser.add_argument(
        "--category",
        default="",
        help="Run only evaluator cases in this category, such as recovery or tool.",
    )
    parser.add_argument(
        "--case",
        default="",
        help="Run only the evaluator case with this exact name.",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="List evaluator case names and categories without running them.",
    )
    parser.add_argument(
        "--output",
        default="",
        metavar="PATH",
        help="Write the JSON payload to PATH as well as stdout.",
    )
    parser.add_argument(
        "--fail-on-failure",
        action="store_true",
        help="Exit with code 1 when the evaluator report contains failed cases.",
    )
    args = parser.parse_args()
    if args.list_cases:
        _emit_json_payload({"cases": registered_evaluation_cases()}, args.output, parser)
        return
    try:
        report = evaluate_agent(category=args.category, case_name=args.case)
    except ValueError as exc:
        parser.error(str(exc))
    _emit_json_payload(report, args.output, parser)
    raise SystemExit(_exit_code_for_report(report, fail_on_failure=args.fail_on_failure))


def _emit_json_payload(
    payload: Dict[str, Any],
    output_path: str,
    parser: argparse.ArgumentParser,
) -> None:
    try:
        json_payload = format_and_write_json(payload, output_path)
    except OSError as exc:
        parser.error(f"could not write --output file: {exc}")
    print(json_payload)


if __name__ == "__main__":
    main()
