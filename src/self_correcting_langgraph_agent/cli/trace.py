from __future__ import annotations

from pathlib import Path
from typing import Any

from self_correcting_langgraph_agent.service.safety import safe_trace_file_stem


def persist_runtime_cli_trace(
    result: dict,
    trace_dir: str,
    persist_trace: Any,
) -> None:
    result["trace_path"] = str(
        Path(trace_dir) / f"{safe_trace_file_stem(result.get('run_id'))}.json"
    )
    persist_trace(result, trace_dir)


def persist_runtime_cli_trace_or_raise(
    result: dict,
    trace_dir: str,
    persist_trace: Any,
) -> None:
    try:
        persist_runtime_cli_trace(result, trace_dir, persist_trace)
    except OSError as exc:
        raise ValueError(f"could not persist --trace-dir trace: {exc}") from exc
