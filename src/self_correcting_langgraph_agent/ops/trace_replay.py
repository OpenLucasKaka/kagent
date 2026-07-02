from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from self_correcting_langgraph_agent.utils.json_output import format_and_write_json


def summarize_runtime_trace(trace: Dict[str, Any], *, trace_path: str = "") -> Dict[str, Any]:
    if not isinstance(trace, dict):
        raise ValueError("trace payload must be a JSON object")
    observations = trace.get("observations")
    if not isinstance(observations, list):
        observations = []
    events = trace.get("events")
    if not isinstance(events, list):
        events = []
    progress_events = trace.get("progress_events")
    if not isinstance(progress_events, list):
        progress_events = []
    return {
        "trace_path": trace_path,
        "trace_type": str(trace.get("trace_type", "")),
        "run_id": str(trace.get("run_id", "")),
        "status": str(trace.get("status", "")),
        "goal": str(trace.get("goal", "")),
        "started_at": str(trace.get("started_at", "")),
        "completed_at": str(trace.get("completed_at", "")),
        "duration_seconds": str(trace.get("duration_seconds", "")),
        "iterations": _iterations_label(trace),
        "event_count": str(len(events)),
        "progress_event_count": str(len(progress_events)),
        "observation_count": str(len(observations)),
        "approved_action_count": str(trace.get("approved_action_count", "0")),
        "pending_approval": _pending_approval_summary(trace.get("pending_approval")),
        "tool_counts": _count_by_key(observations, "tool"),
        "observation_status_counts": _count_by_key(observations, "status"),
        "failed_observations": _failed_observations(observations),
        "changed_files": _changed_files(observations),
        "artifacts": _artifacts(observations),
        "progress_timeline": _progress_timeline(progress_events),
        "timeline": _timeline(observations),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a redacted replay summary for a persisted runtime trace."
    )
    parser.add_argument("trace_json", help="Path to a persisted runtime trace JSON file.")
    parser.add_argument(
        "--output",
        default="",
        metavar="PATH",
        help="Write the JSON summary to PATH as well as stdout.",
    )
    args = parser.parse_args()
    try:
        trace = _read_trace(Path(args.trace_json))
        summary = summarize_runtime_trace(trace, trace_path=args.trace_json)
        json_payload = format_and_write_json(summary, args.output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json_payload)


def _read_trace(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("trace payload must be a JSON object")
    return payload


def _iterations_label(trace: Dict[str, Any]) -> str:
    iteration_count = str(trace.get("iteration_count", "")).strip()
    max_iterations = str(trace.get("max_iterations", "")).strip()
    if iteration_count and max_iterations:
        return f"{iteration_count}/{max_iterations}"
    return iteration_count


def _pending_approval_summary(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        "id": str(value.get("id", "")),
        "tool": str(value.get("tool", "")),
        "reason": str(value.get("reason", "")),
    }


def _count_by_key(observations: List[Any], key: str) -> Dict[str, str]:
    counts: Dict[str, int] = {}
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        value = str(observation.get(key, "")).strip()
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return {key: str(counts[key]) for key in sorted(counts)}


def _failed_observations(observations: List[Any]) -> List[Dict[str, str]]:
    failed = []
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        if str(observation.get("status", "")) not in {"failed", "requires_approval"}:
            continue
        failed.append(
            {
                "action_id": str(observation.get("action_id", "")),
                "tool": str(observation.get("tool", "")),
                "status": str(observation.get("status", "")),
                "error_code": str(observation.get("error_code", "")),
                "error": str(observation.get("error", "")),
            }
        )
    return failed


def _changed_files(observations: List[Any]) -> List[Dict[str, str]]:
    changed = []
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        output = observation.get("output")
        if not isinstance(output, dict):
            continue
        files = output.get("changed_files")
        if not isinstance(files, list):
            continue
        for item in files:
            if not isinstance(item, dict):
                continue
            changed.append(
                {
                    "action_id": str(observation.get("action_id", "")),
                    "path": str(item.get("path", "")),
                    "operation": str(item.get("operation", "")),
                    "bytes": str(item.get("bytes", "")),
                }
            )
    return changed


def _artifacts(observations: List[Any]) -> List[Dict[str, str]]:
    artifacts = []
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        output = observation.get("output")
        if not isinstance(output, dict):
            continue
        artifact_id = str(output.get("artifact_id", "")).strip()
        if not artifact_id:
            continue
        artifacts.append(
            {
                "action_id": str(observation.get("action_id", "")),
                "artifact_id": artifact_id,
                "title": str(output.get("title", "")),
                "kind": str(output.get("kind", "")),
                "format": str(output.get("format", "")),
                "bytes": str(output.get("bytes", "")),
            }
        )
    return artifacts


def _timeline(observations: List[Any]) -> List[Dict[str, str]]:
    timeline = []
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        timeline.append(
            {
                "action_id": str(observation.get("action_id", "")),
                "tool": str(observation.get("tool", "")),
                "status": str(observation.get("status", "")),
                "error_code": str(observation.get("error_code", "")),
                "duration_seconds": str(observation.get("duration_seconds", "")),
            }
        )
    return timeline


def _progress_timeline(progress_events: List[Any]) -> List[Dict[str, str]]:
    timeline = []
    fields = [
        "type",
        "node",
        "status",
        "iteration",
        "action_id",
        "tool",
        "reason",
        "error_code",
        "action_count",
        "iteration_count",
        "duration_seconds",
    ]
    for item in progress_events:
        if not isinstance(item, dict):
            continue
        event = {
            field: str(item[field])
            for field in fields
            if field in item and str(item[field]).strip()
        }
        if event:
            timeline.append(event)
    return timeline


if __name__ == "__main__":
    main()
