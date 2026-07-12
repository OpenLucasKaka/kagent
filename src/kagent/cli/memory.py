from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from kagent.utils.json_output import json_ready
from kagent.utils.paths import kagent_state_dir, migrate_legacy_kagent_state

SESSION_MEMORY_SCHEMA_VERSION = "2"
SESSION_MEMORY_ENV_VAR = "KAGENT_SESSION_MEMORY_PATH"
HISTORY_ENV_VAR = "KAGENT_HISTORY_PATH"
_API_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9:_-]{8,}\b")
_BEARER_TOKEN_PATTERN = re.compile(
    r"\b(Authorization:\s*Bearer\s+|Bearer\s+)([A-Za-z0-9._~+/:-]{8,})",
    re.IGNORECASE,
)
_URL_CREDENTIAL_PATTERN = re.compile(r"\b(https?://)([^/\s:@]+):([^/\s@]+)@")
_FACT_HINT_PATTERN = re.compile(
    r"(我是|我叫|叫我|记住|偏好|喜欢|不喜欢|my name is|call me|remember|prefer)",
    re.IGNORECASE,
)
_OPEN_ITEM_HINT_PATTERN = re.compile(
    r"(继续|接下来|待办|todo|需要|要求|帮我|创建|修复|优化|上线|部署|follow up|next)",
    re.IGNORECASE,
)
_MAX_COMPACT_LINE_CHARS = 220


@dataclass
class RuntimeSessionMemory:
    summary: str = ""
    facts: list[str] = field(default_factory=list)
    open_items: list[str] = field(default_factory=list)
    turns: list[dict[str, str]] = field(default_factory=list)
    compacted_turn_count: int = 0

    def __bool__(self) -> bool:
        return bool(self.summary or self.facts or self.open_items or self.turns)

    def __len__(self) -> int:
        return len(self.turns)

    def __iter__(self):
        return iter(self.turns)

    def __getitem__(self, key):
        return self.turns[key]

    def __delitem__(self, key) -> None:
        del self.turns[key]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, list):
            return self.turns == other
        if isinstance(other, RuntimeSessionMemory):
            return (
                self.summary == other.summary
                and self.facts == other.facts
                and self.open_items == other.open_items
                and self.turns == other.turns
                and self.compacted_turn_count == other.compacted_turn_count
            )
        return False

    def append(self, turn: dict[str, str]) -> None:
        self.turns.append(turn)

    def clear(self) -> None:
        self.summary = ""
        self.facts.clear()
        self.open_items.clear()
        self.turns.clear()
        self.compacted_turn_count = 0


def default_runtime_session_memory_path(
    env: Mapping[str, str] | None = None,
) -> str:
    source = os.environ if env is None else env
    if SESSION_MEMORY_ENV_VAR in source:
        return source[SESSION_MEMORY_ENV_VAR]
    migrate_legacy_kagent_state(source)
    return str(kagent_state_dir(source) / "session-memory.json")


def default_runtime_history_path(
    env: Mapping[str, str] | None = None,
) -> str:
    source = os.environ if env is None else env
    if HISTORY_ENV_VAR in source:
        return source[HISTORY_ENV_VAR]
    migrate_legacy_kagent_state(source)
    return str(kagent_state_dir(source) / "history")


def runtime_prompt_history(path: str):
    if not path:
        return None
    try:
        from prompt_toolkit.history import FileHistory
    except ImportError:
        return None

    history_path = Path(path)
    _prepare_owner_only_history_file(history_path)

    class _RedactingFileHistory(FileHistory):
        def store_string(self, string: str) -> None:
            super().store_string(redact_runtime_session_memory_text(string))

        def load_history_strings(self):
            for item in super().load_history_strings():
                yield redact_runtime_session_memory_text(item)

    return _RedactingFileHistory(str(history_path))


def clear_runtime_history(path: str) -> None:
    if not path:
        return
    history_path = Path(path)
    _prepare_owner_only_history_file(history_path)
    with history_path.open("w", encoding="utf-8") as handle:
        handle.write("")
    history_path.chmod(0o600)


def _prepare_owner_only_history_file(path: Path) -> None:
    _reject_symlink_memory_file(path)
    _reject_symlink_memory_path_parts(path)
    _ensure_owner_only_memory_dir(path.parent)
    if path.exists():
        _require_owner_only_memory_file(path)
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    os.close(fd)
    path.chmod(0o600)


def load_runtime_session_memory(path: str, *, max_turns: int) -> RuntimeSessionMemory:
    if not path:
        return RuntimeSessionMemory()
    memory_path = Path(path)
    try:
        _reject_symlink_memory_file(memory_path)
        _reject_symlink_memory_path_parts(memory_path)
        _tighten_existing_owner_only_memory_dir(memory_path.parent)
        _require_owner_only_memory_file(memory_path)
        payload = json.loads(memory_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return RuntimeSessionMemory()
    if not isinstance(payload, dict):
        raise ValueError("session memory file must contain a JSON object")
    turns = payload.get("turns")
    if not isinstance(turns, list):
        raise ValueError("session memory file must contain a turns array")
    return RuntimeSessionMemory(
        summary=_bounded_memory_text(str(payload.get("summary", "")).strip(), 2400),
        facts=_normalize_memory_lines(payload.get("facts"), max_items=16),
        open_items=_normalize_memory_lines(payload.get("open_items"), max_items=16),
        turns=_normalize_session_memory_turns(turns, max_turns=max_turns),
        compacted_turn_count=_non_negative_int(payload.get("compacted_turn_count")),
    )


def save_runtime_session_memory(
    path: str,
    memory: RuntimeSessionMemory | list[dict[str, str]],
) -> None:
    if not path:
        return
    memory_path = Path(path)
    _reject_symlink_memory_file(memory_path)
    _reject_symlink_memory_path_parts(memory_path)
    output_dir = memory_path.parent
    _ensure_owner_only_memory_dir(output_dir)
    session_memory = coerce_runtime_session_memory(memory)
    payload = {
        "schema_version": SESSION_MEMORY_SCHEMA_VERSION,
        "summary": _redact_session_memory_text(session_memory.summary),
        "facts": json_ready(_redact_memory_lines(session_memory.facts)),
        "open_items": json_ready(_redact_memory_lines(session_memory.open_items)),
        "turns": json_ready(_redact_session_memory_turns(session_memory.turns)),
        "compacted_turn_count": session_memory.compacted_turn_count,
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


def coerce_runtime_session_memory(
    memory: RuntimeSessionMemory | list[dict[str, str]],
) -> RuntimeSessionMemory:
    if isinstance(memory, RuntimeSessionMemory):
        return memory
    return RuntimeSessionMemory(
        turns=_normalize_session_memory_turns(memory, max_turns=len(memory)),
    )


def compact_runtime_session_memory(
    memory: RuntimeSessionMemory | list[dict[str, str]],
    *,
    max_recent_turns: int,
    max_summary_chars: int,
    max_facts: int,
    max_open_items: int,
) -> RuntimeSessionMemory:
    session_memory = coerce_runtime_session_memory(memory)
    overflow_count = max(0, len(session_memory.turns) - max_recent_turns)
    if overflow_count <= 0:
        session_memory.summary = _bounded_memory_text(
            session_memory.summary,
            max_summary_chars,
        )
        session_memory.facts = _dedupe_memory_lines(session_memory.facts)[-max_facts:]
        session_memory.open_items = _dedupe_memory_lines(session_memory.open_items)[
            -max_open_items:
        ]
        return session_memory

    old_turns = session_memory.turns[:overflow_count]
    session_memory.turns = session_memory.turns[overflow_count:]
    session_memory.compacted_turn_count += len(old_turns)

    summary_lines = [_turn_summary_line(turn) for turn in old_turns]
    summary_lines = [line for line in summary_lines if line]
    merged_summary = "\n".join(
        part
        for part in [session_memory.summary.strip(), *summary_lines]
        if part
    )
    session_memory.summary = _bounded_memory_text(merged_summary, max_summary_chars)
    session_memory.facts = _dedupe_memory_lines(
        [
            *session_memory.facts,
            *[
                line
                for turn in old_turns
                for line in _fact_lines_from_turn(turn)
            ],
        ]
    )[-max_facts:]
    session_memory.open_items = _dedupe_memory_lines(
        [
            *session_memory.open_items,
            *[
                line
                for turn in old_turns
                for line in _open_item_lines_from_turn(turn)
            ],
        ]
    )[-max_open_items:]
    return session_memory


def _normalize_session_memory_turns(
    turns: list[Any],
    *,
    max_turns: int,
) -> list[dict[str, str]]:
    normalized = []
    for item in turns:
        if not isinstance(item, dict):
            continue
        user = _redact_session_memory_text(str(item.get("user", "")).strip())
        assistant = _redact_session_memory_text(str(item.get("assistant", "")).strip())
        if not user and not assistant:
            continue
        normalized.append({"user": user, "assistant": assistant})
    return normalized[-max_turns:]


def _normalize_memory_lines(value: Any, *, max_items: int) -> list[str]:
    if not isinstance(value, list):
        return []
    lines = []
    for item in value:
        text = _bounded_memory_text(str(item).strip(), _MAX_COMPACT_LINE_CHARS)
        if text:
            lines.append(text)
    return _dedupe_memory_lines(lines)[-max_items:]


def _redact_session_memory_turns(turns: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "user": _redact_session_memory_text(str(turn.get("user", ""))),
            "assistant": _redact_session_memory_text(str(turn.get("assistant", ""))),
        }
        for turn in turns
        if str(turn.get("user", "")).strip() or str(turn.get("assistant", "")).strip()
    ]


def _redact_memory_lines(lines: list[str]) -> list[str]:
    return [
        _redact_session_memory_text(str(line))
        for line in lines
        if str(line).strip()
    ]


def _redact_session_memory_text(text: str) -> str:
    return redact_runtime_session_memory_text(text)


def redact_runtime_session_memory_text(text: str) -> str:
    redacted = _API_KEY_PATTERN.sub("[REDACTED_API_KEY]", text)
    redacted = _BEARER_TOKEN_PATTERN.sub(r"\1[REDACTED_TOKEN]", redacted)
    return _URL_CREDENTIAL_PATTERN.sub(r"\1[REDACTED_CREDENTIALS]@", redacted)


def _turn_summary_line(turn: dict[str, str]) -> str:
    user = _bounded_memory_text(str(turn.get("user", "")).strip(), 120)
    assistant = _bounded_memory_text(str(turn.get("assistant", "")).strip(), 140)
    if user and assistant:
        return f"- User: {user} | Agent: {assistant}"
    if user:
        return f"- User: {user}"
    if assistant:
        return f"- Agent: {assistant}"
    return ""


def _fact_lines_from_turn(turn: dict[str, str]) -> list[str]:
    user = str(turn.get("user", "")).strip()
    assistant = str(turn.get("assistant", "")).strip()
    lines = []
    for label, text in (("User said", user), ("Agent noted", assistant)):
        if text and _FACT_HINT_PATTERN.search(text):
            lines.append(f"{label}: {_bounded_memory_text(text, _MAX_COMPACT_LINE_CHARS)}")
    return lines


def _open_item_lines_from_turn(turn: dict[str, str]) -> list[str]:
    user = str(turn.get("user", "")).strip()
    assistant = str(turn.get("assistant", "")).strip()
    lines = []
    if user and _OPEN_ITEM_HINT_PATTERN.search(user):
        lines.append(f"Request: {_bounded_memory_text(user, _MAX_COMPACT_LINE_CHARS)}")
    lowered_assistant = assistant.lower()
    follow_up_markers = (
        "failed",
        "blocked",
        "requires approval",
        "待",
        "失败",
        "阻塞",
    )
    if assistant and any(word in lowered_assistant for word in follow_up_markers):
        lines.append(
            f"Follow-up: {_bounded_memory_text(assistant, _MAX_COMPACT_LINE_CHARS)}"
        )
    return lines


def _dedupe_memory_lines(lines: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for line in lines:
        text = _bounded_memory_text(str(line).strip(), _MAX_COMPACT_LINE_CHARS)
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _bounded_memory_text(text: str, max_chars: int) -> str:
    compact = " ".join(redact_runtime_session_memory_text(str(text)).split())
    if max_chars <= 0 or len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3] + "..."


def _non_negative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _require_owner_only_memory_file(path: Path) -> None:
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise ValueError("session memory file must be owner-only (0600)")


def _reject_symlink_memory_file(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("session memory file must not be a symlink")


def _ensure_owner_only_memory_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if _is_shared_system_temp_directory(path):
        return
    path.chmod(0o700)


def _tighten_existing_owner_only_memory_dir(path: Path) -> None:
    if path.exists() and not _is_shared_system_temp_directory(path):
        path.chmod(0o700)


def _reject_symlink_memory_path_parts(path: Path) -> None:
    current = Path(path.anchor) if path.is_absolute() else Path(".")
    parts = path.parent.parts[1:] if path.parent.is_absolute() else path.parent.parts
    for part in parts:
        current = current / part
        if current.exists() and current.is_symlink() and not _is_platform_path_alias(current):
            raise ValueError("session memory path must not contain symlinks")


def _is_platform_path_alias(path: Path) -> bool:
    return str(path) in {"/tmp", "/var"}


def _is_shared_system_temp_directory(path: Path) -> bool:
    try:
        resolved_path = path.resolve(strict=True)
        resolved_system_tmp = Path("/tmp").resolve(strict=True)
        metadata = resolved_path.stat()
    except OSError:
        return False
    return (
        resolved_path == resolved_system_tmp
        and metadata.st_uid == 0
        and bool(metadata.st_mode & stat.S_ISVTX)
    )
