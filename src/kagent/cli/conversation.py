from __future__ import annotations

from typing import Any

from kagent.cli.memory import (
    RuntimeSessionMemory,
    compact_runtime_session_memory,
    redact_runtime_session_memory_text,
)
from kagent.cli.ui import join_non_empty, summarize_runtime_output

RUNTIME_MEMORY_MAX_TURNS = 12
_MEMORY_MAX_CHARS = 4000
_MEMORY_RECENT_TURNS = 6
_MEMORY_SUMMARY_CHARS = 2400
_MEMORY_MAX_FACTS = 16
_MEMORY_MAX_OPEN_ITEMS = 16


def runtime_goal_with_memory(
    goal: str,
    session_memory: RuntimeSessionMemory,
) -> str:
    if not session_memory:
        return goal
    memory_lines = _runtime_compact_memory_lines(session_memory)
    recent_lines = []
    for turn in session_memory.turns[-RUNTIME_MEMORY_MAX_TURNS:]:
        user = _compact_runtime_memory_text(turn.get("user", ""))
        assistant = _compact_runtime_memory_text(turn.get("assistant", ""))
        if user:
            recent_lines.append(f"User: {user}")
        if assistant:
            recent_lines.append(f"Assistant: {assistant}")
    if recent_lines:
        memory_lines.append("Recent turns:")
        memory_lines.extend(recent_lines)
    memory_text = "\n".join(memory_lines)
    if len(memory_text) > _MEMORY_MAX_CHARS:
        memory_text = memory_text[-_MEMORY_MAX_CHARS:]
    return (
        "Compacted conversation memory from this interactive session:\n"
        f"{memory_text}\n\n"
        "Use the memory above to resolve references, user identity, prior "
        "requests, and follow-up questions. Answer the current user message; "
        "do not answer as if the user is asking about the model identity unless "
        "they explicitly ask who the assistant/model is.\n\n"
        "Current user message:\n"
        f"{goal}"
    )


def remember_runtime_turn(
    session_memory: RuntimeSessionMemory,
    goal: str,
    payload: Any,
) -> None:
    if not isinstance(payload, dict):
        return
    answer = str(payload.get("answer", "")).strip()
    if not answer:
        answer = _runtime_memory_answer_from_observations(payload.get("observations"))
    session_memory.append(
        {
            "user": _compact_runtime_memory_text(goal),
            "assistant": _compact_runtime_memory_text(answer),
        }
    )
    compact_runtime_session_memory(
        session_memory,
        max_recent_turns=_MEMORY_RECENT_TURNS,
        max_summary_chars=_MEMORY_SUMMARY_CHARS,
        max_facts=_MEMORY_MAX_FACTS,
        max_open_items=_MEMORY_MAX_OPEN_ITEMS,
    )


def _runtime_compact_memory_lines(session_memory: RuntimeSessionMemory) -> list[str]:
    lines = []
    if session_memory.summary:
        lines.append("Summary:")
        lines.extend(f"  {line}" for line in session_memory.summary.splitlines() if line)
    if session_memory.facts:
        lines.append("Durable facts:")
        lines.extend(f"  - {fact}" for fact in session_memory.facts)
    if session_memory.open_items:
        lines.append("Open items:")
        lines.extend(f"  - {item}" for item in session_memory.open_items)
    return lines


def _runtime_memory_answer_from_observations(observations: Any) -> str:
    if not isinstance(observations, list):
        return ""
    snippets = []
    for observation in observations[-3:]:
        if not isinstance(observation, dict):
            continue
        tool = str(observation.get("tool", "")).strip()
        status = str(observation.get("status", "")).strip()
        output_summary = summarize_runtime_output(observation.get("output"))
        snippets.append(join_non_empty([tool, status, output_summary], " "))
    return "; ".join(snippet for snippet in snippets if snippet)


def _compact_runtime_memory_text(text: str) -> str:
    compact = " ".join(redact_runtime_session_memory_text(str(text)).split())
    if len(compact) > 500:
        return compact[:497] + "..."
    return compact


__all__ = [
    "RUNTIME_MEMORY_MAX_TURNS",
    "remember_runtime_turn",
    "runtime_goal_with_memory",
]
