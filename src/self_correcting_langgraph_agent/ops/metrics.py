from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from self_correcting_langgraph_agent.utils.json_output import format_and_write_json


def summarize_metrics_file(path: Path) -> Dict[str, Any]:
    metrics_file_found = path.exists()
    records, malformed_lines = _read_jsonl(path)
    total = len(records)
    passed_records = [record for record in records if record.get("status") == "passed"]
    failed_records = [record for record in records if record.get("status") != "passed"]
    durations = [_duration_value(record.get("duration_seconds", 0)) for record in records]
    latest = records[-1] if records else {}

    pass_rate = len(passed_records) / total if total else 0.0
    average_duration = sum(durations) / total if total else 0.0
    failed_iterations = [str(record.get("iteration")) for record in failed_records]
    latest_evaluator_failed = _string_or_empty(latest.get("evaluator_failed"))
    latest_status = _string_or_empty(latest.get("status"))
    latest_category_counts = _category_counts(latest.get("evaluator_category_counts"))
    recent_statuses = _recent_statuses(records)
    health = _health(total, len(passed_records), latest_evaluator_failed, malformed_lines)

    return {
        "iterations": str(total),
        "passed": str(len(passed_records)),
        "failed": str(len(failed_records)),
        "pass_rate": f"{pass_rate:.2f}",
        "health": health,
        "metrics_file_found": str(metrics_file_found).lower(),
        "average_duration_seconds": f"{average_duration:.2f}",
        "latest_status": latest_status,
        "recent_health": _recent_health(recent_statuses),
        "consecutive_passes": str(_consecutive_pass_count(records)),
        "recent_statuses": recent_statuses,
        "failed_iterations": failed_iterations,
        "malformed_lines": malformed_lines,
        "latest_evaluator_passed": _string_or_empty(latest.get("evaluator_passed")),
        "latest_evaluator_failed": latest_evaluator_failed,
        "latest_slowest_case": _string_or_empty(latest.get("evaluator_slowest_case")),
        "latest_recovered_cases": _string_or_empty(
            latest.get("evaluator_recovered_cases")
        ),
        "latest_recovery_rate": _string_or_empty(latest.get("evaluator_recovery_rate")),
        "latest_category_counts": latest_category_counts,
        "recommendations": _recommendations(
            failed_iterations,
            latest_evaluator_failed,
            malformed_lines,
            latest_status,
            _string_or_empty(latest.get("evaluator_passed")),
            latest_category_counts,
            metrics_file_found,
            path,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize continuous iteration JSONL metrics."
    )
    parser.add_argument("metrics_jsonl", help="Path to the metrics JSONL file.")
    parser.add_argument(
        "--output",
        default="",
        metavar="PATH",
        help="Write the JSON payload to PATH as well as stdout.",
    )
    parser.add_argument(
        "--require-recent-health",
        choices=["healthy", "recovering", "failing", "unknown"],
        default="",
        help="Exit with code 1 unless recent_health matches this value.",
    )
    args = parser.parse_args()
    summary = summarize_metrics_file(Path(args.metrics_jsonl))
    try:
        json_payload = format_and_write_json(summary, args.output)
    except OSError as exc:
        parser.error(f"could not write --output file: {exc}")
    print(json_payload)
    if args.require_recent_health and summary["recent_health"] != args.require_recent_health:
        raise SystemExit(1)


def _read_jsonl(path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    if not path.exists():
        return [], []
    records = []
    malformed_lines = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines.append(str(line_number))
            continue
        if not isinstance(payload, dict):
            malformed_lines.append(str(line_number))
            continue
        records.append(payload)
    return records, malformed_lines


def _string_or_empty(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _duration_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _consecutive_pass_count(records: List[Dict[str, Any]]) -> int:
    count = 0
    for record in reversed(records):
        if record.get("status") != "passed":
            break
        count += 1
    return count


def _recent_statuses(records: List[Dict[str, Any]], limit: int = 5) -> List[str]:
    return [
        _string_or_empty(record.get("status"))
        for record in records[-limit:]
    ]


def _recent_health(recent_statuses: List[str]) -> str:
    if not recent_statuses:
        return "unknown"
    if recent_statuses[-1] != "passed":
        return "failing"
    if all(status == "passed" for status in recent_statuses):
        return "healthy"
    return "recovering"


def _category_counts(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(value[key]) for key in sorted(value)}


def _health(
    total: int,
    passed: int,
    latest_evaluator_failed: str,
    malformed_lines: List[str],
) -> str:
    if total == 0:
        return "failing" if malformed_lines else "unknown"
    if malformed_lines:
        return "degraded"
    if passed == total and latest_evaluator_failed in {"", "0"}:
        return "healthy"
    if passed == 0:
        return "failing"
    return "degraded"


def _recommendations(
    failed_iterations: List[str],
    latest_evaluator_failed: str,
    malformed_lines: List[str],
    latest_status: str,
    latest_evaluator_passed: str,
    latest_category_counts: Dict[str, str],
    metrics_file_found: bool,
    metrics_path: Path,
) -> List[str]:
    recommendations = []
    if not metrics_file_found:
        recommendations.append(f"metrics file not found: {metrics_path}")
        return recommendations
    if failed_iterations:
        recommendations.append(f"inspect failed iterations: {', '.join(failed_iterations)}")
        if latest_status == "passed":
            recommendations.append("latest run is passing after previous failures")
        elif (
            latest_status == "failed"
            and not latest_evaluator_passed
            and not latest_evaluator_failed
        ):
            recommendations.append(
                "inspect check log; latest run failed before a fresh evaluator report"
            )
    if latest_evaluator_failed not in {"", "0"}:
        recommendations.append("review evaluator failures from the latest run")
    if malformed_lines:
        recommendations.append(
            f"inspect malformed metrics lines: {', '.join(malformed_lines)}"
        )
    elif latest_evaluator_passed and not latest_category_counts:
        recommendations.append(
            "review continuous metrics wiring; latest evaluator category counts are missing"
        )
    return recommendations


if __name__ == "__main__":
    main()
