from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from self_correcting_langgraph_agent.utils.json_output import json_ready

SESSION_MEMORY_SCHEMA_VERSION = "1"


def load_runtime_session_memory(path: str, *, max_turns: int) -> list[dict[str, str]]:
    if not path:
        return []
    memory_path = Path(path)
    try:
        payload = json.loads(memory_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if not isinstance(payload, dict):
        raise ValueError("session memory file must contain a JSON object")
    turns = payload.get("turns")
    if not isinstance(turns, list):
        raise ValueError("session memory file must contain a turns array")
    return _normalize_session_memory_turns(turns, max_turns=max_turns)


def save_runtime_session_memory(path: str, turns: list[dict[str, str]]) -> None:
    if not path:
        return
    memory_path = Path(path)
    output_dir = memory_path.parent
    if not output_dir.exists():
        output_dir.mkdir(parents=True)
        output_dir.chmod(0o700)
    payload = {
        "schema_version": SESSION_MEMORY_SCHEMA_VERSION,
        "turns": json_ready(turns),
    }
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{memory_path.name}.",
        suffix=".tmp",
        dir=output_dir,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.chmod(0o600)
        temporary_path.replace(memory_path)
        memory_path.chmod(0o600)
    except Exception:
        if fd != -1:
            os.close(fd)
        temporary_path.unlink(missing_ok=True)
        raise


def _normalize_session_memory_turns(
    turns: list[Any],
    *,
    max_turns: int,
) -> list[dict[str, str]]:
    normalized = []
    for item in turns:
        if not isinstance(item, dict):
            continue
        user = str(item.get("user", "")).strip()
        assistant = str(item.get("assistant", "")).strip()
        if not user and not assistant:
            continue
        normalized.append({"user": user, "assistant": assistant})
    return normalized[-max_turns:]
