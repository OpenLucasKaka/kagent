from __future__ import annotations

import json
import os
import shutil
import sys
import textwrap
from typing import Any

from kagent.utils.json_output import json_ready


def runtime_ui_color_enabled() -> bool:
    return (
        sys.stdout.isatty()
        and "NO_COLOR" not in os.environ
        and os.environ.get("TERM", "") != "dumb"
    )


def runtime_ready_message(*, color: bool = False) -> str:
    return "\n".join(
        [
            _color("Kagent", "bold", enabled=color),
            "  [K]  (o_o)  K-bot",
            "       /|K|\\  ask, approve, automate",
            _dim("        / \\   ready · /help · /json · exit", enabled=color),
        ]
    )


def runtime_prompt(*, color: bool = False) -> str:
    return _prompt_color("› ", "cyan", enabled=color)


def runtime_interactive_help() -> str:
    return "\n".join(
        [
            "Kagent command menu",
            "",
            "Session",
            "  /pwd       show working directory",
            "  /cd PATH   change working directory",
            "  /status    show shell state",
            "  /config    show provider config",
            "  /tools     show available actions",
            "  /memory    review remembered turns",
            "  /clear     clear remembered turns",
            "  /last      replay last answer",
            "",
            "Output",
            "  /compact   clean transcript",
            "  /json      full JSON traces",
            "  /trace     last JSON trace once",
            "",
            "Debug",
            "  /help      command menu",
            "  exit       quit",
        ]
    )


def format_runtime_provider_config(provider: Any) -> str:
    config = getattr(provider, "config", None)
    snapshot_fn = getattr(config, "redacted_snapshot", None)
    if not callable(snapshot_fn):
        return "Kagent provider\n  provider  inline/test\n  api_key   not configured"
    snapshot = snapshot_fn()
    provider_name = str(
        snapshot.get("llm_provider_display_name")
        or snapshot.get("llm_provider")
        or "unknown"
    )
    base_url = str(snapshot.get("llm_base_url", "")).strip() or "-"
    model = str(snapshot.get("llm_model", "")).strip() or "-"
    api_key_state = (
        "configured"
        if str(snapshot.get("llm_api_key_configured", "")).lower() == "true"
        else "not configured"
    )
    timeout = str(snapshot.get("llm_timeout_seconds", "")).strip()
    retries = str(snapshot.get("llm_max_retries", "")).strip()
    backoff = str(snapshot.get("llm_retry_backoff_seconds", "")).strip()
    return "\n".join(
        [
            "Kagent provider",
            f"  provider  {provider_name}",
            f"  base_url  {base_url}",
            f"  model     {model}",
            f"  api_key   {api_key_state}",
            f"  timeout   {timeout}s" if timeout else "  timeout   -",
            f"  retries   {retries}" if retries else "  retries   -",
            f"  backoff   {backoff}s" if backoff else "  backoff   -",
        ]
    )


def format_runtime_interactive_tools(tools: list[dict[str, Any]]) -> str:
    rows = []
    for tool in sorted(tools, key=lambda item: str(item.get("name", ""))):
        name = str(tool.get("name", "")).strip()
        if not name:
            continue
        if name in {"note"}:
            continue
        approval = str(tool.get("approval_required_by_default", "")).strip().lower()
        access = "approval" if approval == "true" else "allowed"
        description = _one_line_text(str(tool.get("description", "")).strip())
        rows.append((name, access, description))
    if not rows:
        return "Kagent actions\n  none"
    name_width = max(len(name) for name, _access, _description in rows)
    return "\n".join(
        ["Kagent actions"]
        + [
            f"  {name.ljust(name_width)}  {access.ljust(8)}  {description}".rstrip()
            for name, access, description in rows
        ]
    )


def format_runtime_interactive_status(
    *,
    cwd: str,
    full_json_mode: bool,
    session_memory: list[dict[str, str]],
    last_payload: Any,
    trace_dir: str = "",
) -> str:
    memory_count = len(session_memory)
    memory_label = "turn" if memory_count == 1 else "turns"
    last_status = "-"
    if isinstance(last_payload, dict):
        last_status = str(last_payload.get("status", "")).strip() or "-"
    return "\n".join(
        [
            "Kagent status",
            f"  cwd     {cwd}",
            f"  output  {'full JSON' if full_json_mode else 'compact'}",
            f"  memory  {memory_count} {memory_label}",
            f"  last    {last_status}",
            f"  trace   {trace_dir or 'off'}",
        ]
    )


def format_runtime_session_memory(session_memory: list[dict[str, str]]) -> str:
    if not session_memory:
        return "Memory is empty."
    lines = ["Memory"]
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
    lines = [_format_run_status(payload, status, color=color)]

    answer = str(payload.get("answer", "")).strip()
    if answer:
        lines.append("")
        lines.extend(_answer_lines(answer))

    error_code = str(payload.get("error_code", "")).strip()
    error = str(payload.get("error", "")).strip()
    if error_code or error:
        lines.append("")
        lines.append(_color("Error", "red", enabled=color))
        lines.extend(_indented_lines(join_non_empty([error_code, error], " "), prefix="  "))

    pending = payload.get("pending_approval")
    if isinstance(pending, dict):
        lines.append("")
        lines.append(_color("Approval required", "yellow", enabled=color))
        lines.extend(_indented_lines(_format_pending_approval(pending), prefix="  "))

    visible_observations = visible_runtime_observations(payload.get("observations"))
    if visible_observations:
        lines.append("")
        lines.append(_dim("Actions", enabled=color))
        for observation, repeat_count in visible_observations:
            lines.extend(
                format_runtime_observation_lines(
                    observation, color=color, repeat_count=repeat_count
                )
            )

    return "\n".join(lines)


def format_runtime_progress_event(event: Any, *, color: bool = False) -> str:
    if not isinstance(event, dict):
        return ""
    event_type = str(event.get("type", "")).strip()
    if event_type == "planner_started":
        iteration = str(event.get("iteration", "")).strip()
        suffix = f" iter {iteration}" if iteration else " planning"
        return _dim(f"Thinking ·{suffix}", enabled=color)
    if event_type == "planner_completed":
        action_count = str(event.get("action_count", "")).strip()
        duration = _progress_duration(event)
        suffix = f" · {duration}" if duration else ""
        if action_count == "0":
            return _dim(f"Finalizing{suffix}", enabled=color)
        action_label = "action" if action_count == "1" else "actions"
        return _dim(f"Plan ready · {action_count} {action_label}{suffix}", enabled=color)
    if event_type == "tool_started":
        tool = str(event.get("tool", "")).strip() or "tool"
        if _is_internal_progress_tool(tool):
            return ""
        return _dim(f"Running {tool}...", enabled=color)
    if event_type == "tool_completed":
        status = str(event.get("status", "")).strip()
        tool = str(event.get("tool", "")).strip() or "tool"
        if _is_internal_progress_tool(tool) and status in {"ok", "done"}:
            return ""
        icon = _status_icon(status, color=color)
        return join_non_empty([f"{icon} {tool}", _progress_duration(event)], " · ")
    if event_type == "approval_required":
        tool = str(event.get("tool", "")).strip() or "tool"
        return _color(f"Approval required · {tool}", "yellow", enabled=color)
    if event_type == "planner_failed":
        duration = _progress_duration(event)
        suffix = f" · {duration}" if duration else ""
        return _color(f"Planner failed{suffix}", "red", enabled=color)
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
    if summary:
        headline.append(_dim(summary, enabled=color))
    lines = ["  " + " · ".join(headline)]
    if error_code or error:
        lines.extend(_indented_lines(join_non_empty([error_code, error], " "), prefix="  "))
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
    return _color("Approve this action?", "yellow", enabled=color) + " [y/N] "


def join_non_empty(values: list[str], separator: str) -> str:
    return separator.join(value for value in values if value)


def _format_run_status(payload: dict, status: str, *, color: bool) -> str:
    parts = [_status_label(status, color=color)]
    if status.strip() == "requires_approval":
        parts.append("pending")
    duration = str(payload.get("duration_seconds", "")).strip()
    if duration:
        parts.append(f"{duration}s")
    iteration_label = _runtime_iteration_label(payload)
    if iteration_label:
        parts.append(f"iter {iteration_label}")
    return " · ".join(parts)


def _format_pending_approval(pending: dict) -> str:
    tool = str(pending.get("tool", "")).strip()
    lines = []
    if tool:
        lines.append(f"tool    {tool}")
    reason = str(pending.get("reason", "")).strip()
    if reason:
        lines.append(f"reason  {reason}")
    action_input = pending.get("input")
    input_summary = _summarize_pending_input(action_input, tool=tool)
    if input_summary:
        lines.append(f"target  {input_summary}")
    return "\n".join(lines)


def _summarize_pending_input(action_input: Any, *, tool: str) -> str:
    if not isinstance(action_input, dict):
        return ""
    if tool in {"open_url", "http_request"}:
        return _short_runtime_value(action_input.get("url", ""))
    if tool == "open_app":
        return _short_runtime_value(action_input.get("application", ""))
    if tool == "shell_command":
        return _short_runtime_value(action_input.get("command", ""))
    return summarize_runtime_output(action_input, tool=tool)


def _answer_lines(text: str) -> list[str]:
    return _wrapped_block_lines(text, prefix="")


def _indented_lines(text: str, prefix: str = "  ") -> list[str]:
    return _wrapped_block_lines(text, prefix=prefix)


def _wrapped_block_lines(text: str, *, prefix: str) -> list[str]:
    width = max(40, shutil.get_terminal_size((100, 24)).columns)
    wrap_width = max(20, width - len(prefix))
    lines: list[str] = []
    in_fence = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            in_fence = not in_fence
            lines.append(prefix + line)
            continue
        if in_fence or not line.strip():
            lines.append(prefix + line)
            continue
        leading = line[: len(line) - len(line.lstrip())]
        content = line.lstrip()
        bullet_prefix = _markdown_continuation_prefix(content)
        wrapped = textwrap.wrap(
            content,
            width=max(20, wrap_width - len(leading)),
            break_long_words=False,
            break_on_hyphens=False,
        )
        if not wrapped:
            lines.append(prefix + line)
            continue
        lines.append(prefix + leading + wrapped[0])
        for continuation in wrapped[1:]:
            lines.append(prefix + leading + bullet_prefix + continuation)
    return lines


def _markdown_continuation_prefix(text: str) -> str:
    stripped = text.lstrip()
    if stripped.startswith(("- ", "* ")):
        return "  "
    if len(stripped) > 3 and stripped[0].isdigit() and stripped[1:3] == ". ":
        return "   "
    return ""


def _progress_duration(event: dict) -> str:
    duration = str(event.get("duration_seconds", "")).strip()
    return f"{duration}s" if duration else ""


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


def _is_internal_progress_tool(tool: str) -> bool:
    return tool.strip() == "note"


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
    if normalized_tool == "open_app":
        return join_non_empty(
            [
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
    labels = {
        "done": "Done",
        "ok": "Done",
        "failed": "Failed",
        "requires_approval": "Approval",
        "cancelled": "Cancelled",
    }
    label = labels.get(normalized, normalized)
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


def _one_line_text(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) > 96:
        return compact[:93] + "..."
    return compact


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


def _prompt_color(text: str, style: str, *, enabled: bool) -> str:
    if not enabled:
        return text
    codes = {
        "cyan": "36",
    }
    code = codes.get(style)
    if not code:
        return text
    return f"\001\033[{code}m\002{text}\001\033[0m\002"
