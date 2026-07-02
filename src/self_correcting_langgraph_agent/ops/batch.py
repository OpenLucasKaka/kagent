from __future__ import annotations

import argparse
import contextlib
import io
import json
import warnings
from pathlib import Path
from typing import Any, Dict, Iterable

from self_correcting_langgraph_agent.utils.config_validation import optional_json_int
from self_correcting_langgraph_agent.utils.json_output import format_and_write_json, json_ready


def run_batch_file(
    input_path: Path,
    output_path: Path,
    *,
    full_trace: bool = False,
) -> Dict[str, str]:
    records = list(_run_batch_records(input_path, full_trace=full_trace))
    output_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    succeeded = sum(1 for record in records if record.get("status") == "done")
    return {
        "processed": str(len(records)),
        "succeeded": str(succeeded),
        "failed": str(len(records) - succeeded),
    }


def _run_batch_records(
    input_path: Path,
    *,
    full_trace: bool,
) -> Iterable[Dict[str, Any]]:
    warning_sink = io.StringIO()
    with contextlib.redirect_stderr(warning_sink), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from self_correcting_langgraph_agent.core.agent import AgentConfig, run_agent
        from self_correcting_langgraph_agent.core.summary import summarize_run

        yield from _run_batch_records_with_agent(
            input_path,
            AgentConfig,
            run_agent,
            summarize_run,
            full_trace=full_trace,
        )


def _run_batch_records_with_agent(
    input_path: Path,
    AgentConfig,
    run_agent,
    summarize_run,
    *,
    full_trace: bool,
):
    for line_number, line in enumerate(input_path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            yield _failed_record(line_number, "", f"invalid JSON: {exc.msg}")
            continue
        if not isinstance(payload, dict):
            yield _failed_record(line_number, "", "input line must be a JSON object")
            continue
        goal = str(payload.get("goal", ""))
        item_id = str(payload.get("id", line_number))
        if not goal.strip():
            yield _failed_record(line_number, item_id, "goal is required")
            continue
        try:
            config = _config_from_payload(AgentConfig, payload)
        except (TypeError, ValueError) as exc:
            yield _failed_record(line_number, item_id, str(exc))
            continue
        state = run_agent(goal, config=config)
        summary = summarize_run(state)
        record = {
            "id": item_id,
            "line_number": str(line_number),
            "status": summary["status"],
        }
        if full_trace:
            record["trace"] = json_ready(state)
        else:
            record["summary"] = summary
        yield record


def _failed_record(line_number: int, item_id: str, error: str) -> Dict[str, str]:
    return {
        "id": item_id,
        "line_number": str(line_number),
        "status": "failed",
        "error": error,
    }


def _config_from_payload(AgentConfig, payload: Dict[str, Any]):
    defaults = AgentConfig()
    return AgentConfig(
        max_steps=_optional_int(payload, "max_steps", defaults.max_steps),
        max_retries=_optional_int(payload, "max_retries", defaults.max_retries),
    )


def _optional_int(payload: Dict[str, Any], key: str, default: int) -> int:
    return optional_json_int(payload, key, default)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run agent goals from a JSONL file and write JSONL summaries."
    )
    parser.add_argument("input_jsonl", help="Input JSONL file with one goal object per line.")
    parser.add_argument("output_jsonl", help="Output JSONL file for result summaries.")
    parser.add_argument(
        "--output",
        default="",
        metavar="PATH",
        help="Write the batch report JSON to PATH as well as stdout.",
    )
    parser.add_argument(
        "--fail-on-failure",
        action="store_true",
        help="Exit with code 1 when any batch record failed.",
    )
    parser.add_argument(
        "--full-trace",
        action="store_true",
        help="Write full agent traces instead of compact summaries.",
    )
    args = parser.parse_args()
    try:
        report = run_batch_file(
            Path(args.input_jsonl),
            Path(args.output_jsonl),
            full_trace=args.full_trace,
        )
        json_payload = format_and_write_json(report, args.output)
    except OSError as exc:
        parser.error(str(exc))
    print(json_payload)
    if args.fail_on_failure and int(report["failed"]) > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
