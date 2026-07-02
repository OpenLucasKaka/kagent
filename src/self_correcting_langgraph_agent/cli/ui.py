from __future__ import annotations

import json
import os
import sys
from typing import Any

from self_correcting_langgraph_agent.utils.json_output import json_ready


def runtime_ui_color_enabled() -> bool:
    return (
        sys.stdout.isatty()
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM", "") != "dumb"
    )


def runtime_ready_message(*, color: bool = False) -> str:
    return _dim("self-correcting agent ready  /help", enabled=color)


def runtime_prompt(*, color: bool = False) -> str:
    return _color("› ", "cyan", enabled=color)


def runtime_interactive_help() -> str:
    return "\n".join(
        [
            "commands",
            "  /help      show commands",
            "  /json      stream full JSON traces",
            "  /compact   return to agent transcript output",
            "  /last      replay the last transcript",
            "  /trace     print the last full JSON trace once",
            "  /memory    show session memory",
            "  /clear     clear session memory",
            "  exit       quit",
        ]
    )


def format_runtime_session_memory(session_memory: list[dict[str, str]]) -> str:
    if not session_memory:
        return "memory is empty."
    lines = ["memory"]
    for index, turn in enumerate(session_memory, start=1):
        user = turn.get("user", "")
        assistant = turn.get("assistant", "")
        lines.append(f"  {index}. user   {user}")
        if assistant:
            lines.append(f"     agent  {assistant}")
    return "\n".join(lines)


def format_runtime_interactive_summary(payload: Any, *, color: bool = False) -> str:
    if not isinstance(payload, dict):
        return str(payload)

    status = str(payload.get("status", "")).strip()
    lines = [_run_card_header(payload, status, color=color)]

    answer = str(payload.get("answer", "")).strip()
    if answer:
        lines.append(_box_blank())
        lines.extend(_box_block(answer))

    error_code = str(payload.get("error_code", "")).strip()
    error = str(payload.get("error", "")).strip()
    if error_code or error:
        lines.append(_box_blank())
        lines.append(
            _box_section(
                "error",
                detail=join_non_empty([error_code, error], " "),
            )
        )

    pending = payload.get("pending_approval")
    if isinstance(pending, dict):
        lines.append(_box_blank())
        lines.append(_box_section("approval required"))
        lines.extend(_box_block(_format_pending_approval(pending), prefix="  "))

    visible_observations = visible_runtime_observations(payload.get("observations"))
    if visible_observations:
        lines.append(_box_blank())
        lines.append(_box_section("tools"))
        for observation, repeat_count in visible_observations:
            lines.extend(
                format_runtime_observation_lines(
                    observation, color=color, repeat_count=repeat_count
                )
            )

    lines.append(_box_close())
    return "\n".join(lines)


def format_runtime_progress_event(event: Any, *, color: bool = False) -> str:
    if not isinstance(event, dict):
        return ""
    event_type = str(event.get("type", "")).strip()
    if event_type == "planner_started":
        iteration = str(event.get("iteration", "")).strip()
        suffix = f" iter {iteration}" if iteration else ""
        return _dim(f"  thinking{suffix}...", enabled=color)
    if event_type == "planner_completed":
        action_count = str(event.get("action_count", "")).strip()
        duration = _progress_duration(event)
        if action_count == "0":
            return _dim(f"  finalizing{duration}", enabled=color)
        return _dim(f"  planned {action_count} action(s){duration}", enabled=color)
    if event_type == "tool_started":
        tool = str(event.get("tool", "")).strip() or "tool"
        return _dim(f"  running {tool}...", enabled=color)
    if event_type == "tool_completed":
        status = str(event.get("status", "")).strip()
        tool = str(event.get("tool", "")).strip() or "tool"
        icon = _status_icon(status, color=color)
        return join_non_empty([f"  {icon}", tool, _progress_duration(event)], " ")
    if event_type == "approval_required":
        tool = str(event.get("tool", "")).strip() or "tool"
        return _color(f"  approval required for {tool}", "yellow", enabled=color)
    if event_type == "planner_failed":
        duration = _progress_duration(event)
        return _color(f"  planner failed{duration}", "red", enabled=color)
    return ""


def visible_runtime_observations(observations: Any) -> list[tuple[dict, int]]:
    if not isinstance(observations, list):
        return []
    visible = []
    for observation, repeat_count in _collapse_runtime_observations(observations):
        if _is_internal_note_observation(observation):
            continue
        visible.append((observation, repeat_count))
    return visible


def format_runtime_observation(
    observation: dict,
    *,
    color: bool = False,
    repeat_count: int = 1,
) -> str:
    return "\n".join(
        format_runtime_observation_lines(
            observation, color=color, repeat_count=repeat_count
        )
    )


def format_runtime_observation_lines(
    observation: dict,
    *,
    color: bool = False,
    repeat_count: int = 1,
) -> list[str]:
    status = str(observation.get("status", "")).strip() or "-"
    tool = str(observation.get("tool", "")).strip() or "-"
    duration = str(observation.get("duration_seconds", "")).strip()
    summary = summarize_runtime_output(observation.get("output"), tool=tool)
    suffix = f" x{repeat_count}" if repeat_count > 1 else ""
    error_code = str(observation.get("error_code", "")).strip()
    error = str(observation.get("error", "")).strip()

    headline = [join_non_empty([_status_icon(status, color=color), tool + suffix], " ")]
    if duration:
        headline.append(_dim(f"{duration}s", enabled=color))
    lines = [_box_line("  " + "  ".join(headline))]
    if summary:
        lines.append(_box_line("    " + _dim(summary, enabled=color)))
    if error_code or error:
        lines.append(
            _box_line(
                "    error",
                detail=join_non_empty([error_code, error], " "),
            )
        )
    return lines


def summarize_runtime_output(output: Any, *, tool: str = "") -> str:
    if not isinstance(output, dict) or not output:
        return ""
    tool_summary = _summarize_runtime_output_for_tool(tool, output)
    if tool_summary:
        return tool_summary
    preferred_keys = [
        "url",
        "path",
        "changed_files",
        "file_count",
        "application",
        "opened",
        "status_code",
        "content_type",
        "artifact_id",
        "title",
    ]
    items = []
    for key in preferred_keys:
        if key in output:
            items.append(f"{key}={_short_runtime_value(output[key])}")
    if not items:
        for key in sorted(output)[:3]:
            items.append(f"{key}={_short_runtime_value(output[key])}")
    return ", ".join(items)


def approval_prompt(action_id: str, tool: str, *, color: bool = False) -> str:
    subject = join_non_empty([action_id, tool], " ")
    return _color(f"Approve {subject}? ", "yellow", enabled=color) + "[y/N] "


def join_non_empty(values: list[str], separator: str) -> str:
    return separator.join(value for value in values if value)


def _run_card_header(payload: dict, status: str, *, color: bool) -> str:
    return "╭─ " + _format_run_status(payload, status, color=color)


def _format_run_status(payload: dict, status: str, *, color: bool) -> str:
    parts = [
        join_non_empty(
            [_status_icon(status, color=color), _status_label(status, color=color)],
            " ",
        )
    ]
    duration = str(payload.get("duration_seconds", "")).strip()
    if duration:
        parts.append(f"{duration}s")
    iteration_label = _runtime_iteration_label(payload)
    if iteration_label:
        parts.append(f"iter {iteration_label}")
    return "  ".join(parts)


def _format_pending_approval(pending: dict) -> str:
    action = join_non_empty(
        [
            str(pending.get("id", "")).strip(),
            str(pending.get("tool", "")).strip(),
        ],
        " ",
    )
    lines = ["required"]
    if action:
        lines.append(f"  {action}")
    reason = str(pending.get("reason", "")).strip()
    if reason:
        lines.append(f"  reason: {reason}")
    action_input = pending.get("input")
    input_summary = summarize_runtime_output(action_input)
    if input_summary:
        lines.append(f"  input: {input_summary}")
    return "\n".join(lines)


def _indent_block(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line if line else prefix.rstrip() for line in text.splitlines())


def _box_line(text: str, *, detail: str = "") -> str:
    value = f"{text}: {detail}" if detail else text
    return f"│ {value}".rstrip()


def _box_section(text: str, *, detail: str = "") -> str:
    value = f"{text}: {detail}" if detail else text
    return f"├─ {value}".rstrip()


def _box_blank() -> str:
    return "│"


def _box_close() -> str:
    return "╰─"


def _box_block(text: str, *, prefix: str = "") -> list[str]:
    if not text:
        return []
    return [_box_line(prefix + line) if line else _box_blank() for line in text.splitlines()]


def _progress_duration(event: dict) -> str:
    duration = str(event.get("duration_seconds", "")).strip()
    return f" {duration}s" if duration else ""


def _runtime_iteration_label(payload: dict) -> str:
    iteration_count = str(payload.get("iteration_count", "")).strip()
    max_iterations = str(payload.get("max_iterations", "")).strip()
    if iteration_count and max_iterations:
        return f"{iteration_count}/{max_iterations}"
    return iteration_count


def _collapse_runtime_observations(observations: list) -> list[tuple[dict, int]]:
    collapsed: list[tuple[dict, int]] = []
    last_signature = None
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        signature = _runtime_observation_signature(observation)
        if collapsed and signature == last_signature:
            previous, count = collapsed[-1]
            collapsed[-1] = (previous, count + 1)
            continue
        collapsed.append((observation, 1))
        last_signature = signature
    return collapsed


def _runtime_observation_signature(observation: dict) -> str:
    stable_observation = {
        "action_id": observation.get("action_id"),
        "error": observation.get("error"),
        "error_code": observation.get("error_code"),
        "output": observation.get("output"),
        "status": observation.get("status"),
        "tool": observation.get("tool"),
    }
    return json.dumps(json_ready(stable_observation), ensure_ascii=False, sort_keys=True)


def _is_internal_note_observation(observation: dict) -> bool:
    return (
        str(observation.get("tool", "")).strip() == "note"
        and str(observation.get("status", "")).strip() in {"ok", "done"}
        and not str(observation.get("error_code", "")).strip()
        and not str(observation.get("error", "")).strip()
    )


def _summarize_runtime_output_for_tool(tool: str, output: dict) -> str:
    normalized_tool = tool.strip()
    if normalized_tool == "apply_patch":
        return _summarize_changed_files(output.get("changed_files"))
    if normalized_tool == "open_url":
        return join_non_empty(
            [
                _short_runtime_value(output.get("url", "")),
                _short_runtime_value(output.get("application", "")),
                "opened" if output.get("opened") is True else "",
            ],
            " · ",
        )
    if normalized_tool == "http_request":
        return join_non_empty(
            [
                _short_runtime_value(output.get("url", "")),
                str(output.get("status_code", "")).strip(),
                _short_runtime_value(output.get("content_type", "")),
            ],
            " · ",
        )
    if normalized_tool == "read_file":
        return join_non_empty(
            [
                _short_runtime_value(output.get("path", "")),
                _bytes_label(output.get("bytes")),
                "truncated" if output.get("truncated") is True else "",
            ],
            " · ",
        )
    if normalized_tool == "list_files":
        return join_non_empty(
            [
                _short_runtime_value(output.get("root", "")),
                f"{output.get('file_count')} files"
                if output.get("file_count") is not None
                else "",
                "truncated" if output.get("truncated") is True else "",
            ],
            " · ",
        )
    if normalized_tool == "artifact":
        return join_non_empty(
            [
                _short_runtime_value(output.get("title", "")),
                _short_runtime_value(output.get("kind", "")),
                _short_runtime_value(output.get("format", "")),
                _bytes_label(output.get("bytes")),
            ],
            " · ",
        )
    return ""


def _summarize_changed_files(changed_files: Any) -> str:
    if not isinstance(changed_files, list) or not changed_files:
        return ""
    parts = []
    for item in changed_files[:3]:
        if isinstance(item, dict):
            operation = str(item.get("operation", "")).strip()
            path = str(item.get("path", "")).strip()
            bytes_label = _bytes_label(item.get("bytes"))
            parts.append(join_non_empty([operation, path, bytes_label], " "))
        else:
            parts.append(_short_runtime_value(item))
    if len(changed_files) > 3:
        parts.append(f"+{len(changed_files) - 3} more")
    return "; ".join(part for part in parts if part)


def _bytes_label(value: Any) -> str:
    if value in {None, ""}:
        return ""
    try:
        return f"{int(value)}B"
    except (TypeError, ValueError):
        return ""


def _status_label(status: str, *, color: bool = False) -> str:
    normalized = status.strip() or "-"
    color_name = {
        "done": "green",
        "ok": "green",
        "failed": "red",
        "requires_approval": "yellow",
        "cancelled": "yellow",
    }.get(normalized, "cyan")
    label = "approval" if normalized == "requires_approval" else normalized
    return _color(label, color_name, enabled=color)


def _status_icon(status: str, *, color: bool = False) -> str:
    normalized = status.strip()
    if normalized in {"done", "ok"}:
        return _color("✓", "green", enabled=color)
    if normalized == "failed":
        return _color("✗", "red", enabled=color)
    if normalized in {"requires_approval", "cancelled"}:
        return _color("!", "yellow", enabled=color)
    return _color("•", "cyan", enabled=color)


def _short_runtime_value(value: Any) -> str:
    if isinstance(value, str):
        text = str(value)
    elif isinstance(value, bool):
        text = json.dumps(value)
    elif isinstance(value, (int, float)):
        text = str(value)
    else:
        text = json.dumps(json_ready(value), ensure_ascii=False, sort_keys=True)
    if len(text) > 96:
        return text[:93] + "..."
    return text


def _dim(text: str, *, enabled: bool) -> str:
    return _color(text, "dim", enabled=enabled)


def _color(text: str, style: str, *, enabled: bool) -> str:
    if not enabled:
        return text
    codes = {
        "bold": "1",
        "dim": "2",
        "green": "32",
        "red": "31",
        "yellow": "33",
        "cyan": "36",
    }
    code = codes.get(style)
    if not code:
        return text
    return f"\033[{code}m{text}\033[0m"
