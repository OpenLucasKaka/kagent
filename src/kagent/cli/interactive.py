from __future__ import annotations

import json
import os
import shlex
import sys
import threading
import time
from typing import Any

from kagent.cli.commands import (
    is_runtime_interactive_command,
    runtime_interactive_command_suggestions,
    runtime_interactive_command_usage,
    runtime_interactive_completion_words,
)
from kagent.cli.memory import (
    RuntimeSessionMemory,
    clear_runtime_history,
    compact_runtime_session_memory,
    default_runtime_history_path,
    load_runtime_session_memory,
    redact_runtime_session_memory_text,
    runtime_prompt_history,
    save_runtime_session_memory,
)
from kagent.cli.trace import (
    persist_runtime_cli_trace_or_raise,
    save_runtime_trace_snapshot_or_raise,
)
from kagent.cli.ui import (
    approval_prompt,
    format_runtime_interactive_doctor,
    format_runtime_interactive_status,
    format_runtime_interactive_summary,
    format_runtime_interactive_tools,
    format_runtime_notice,
    format_runtime_pending_approval_detail,
    format_runtime_progress_event,
    format_runtime_provider_config,
    format_runtime_session_memory,
    join_non_empty,
    runtime_interactive_help,
    runtime_prompt,
    runtime_ready_message,
    runtime_ui_color_enabled,
    summarize_runtime_output,
)
from kagent.utils.json_output import format_and_write_json, json_ready

_INTERACTIVE_MEMORY_MAX_TURNS = 12
_INTERACTIVE_MEMORY_MAX_CHARS = 4000
_INTERACTIVE_MEMORY_RECENT_TURNS = 6
_INTERACTIVE_MEMORY_SUMMARY_CHARS = 2400
_INTERACTIVE_MEMORY_MAX_FACTS = 16
_INTERACTIVE_MEMORY_MAX_OPEN_ITEMS = 16


def run_runtime_interactive(
    *,
    provider: Any,
    run_runtime_agent: Any,
    max_iterations: int,
    fail_on_agent_failure: bool,
    full_trace_output: bool = False,
    metadata: dict[str, str] | None = None,
    tags: list[str] | None = None,
    trace_dir: str = "",
    persist_trace: Any = None,
    session_memory_path: str = "",
) -> None:
    interactive_tty = sys.stdin.isatty()
    prompt_stream = sys.__stderr__ or sys.stderr
    full_json_mode = full_trace_output
    session_memory = load_runtime_session_memory(
        session_memory_path,
        max_turns=_INTERACTIVE_MEMORY_MAX_TURNS,
    )
    last_payload: Any = None
    line_reader: Any = None
    if interactive_tty:
        line_reader = _runtime_interactive_line_reader(prompt_stream)
        print(runtime_ready_message(color=runtime_ui_color_enabled()), file=prompt_stream)
    while True:
        try:
            line = (
                line_reader.read(color=runtime_ui_color_enabled())
                if interactive_tty and line_reader is not None
                else sys.stdin.readline()
            )
        except EOFError:
            return
        if not interactive_tty and line == "":
            return
        goal = line.strip()
        if not goal:
            if interactive_tty:
                _erase_empty_runtime_prompt_line()
            continue
        if goal.lower() in {"exit", "quit", ":q"}:
            return
        if interactive_tty and goal.startswith("/"):
            if not is_runtime_interactive_command(goal):
                _print_unknown_runtime_interactive_command(goal)
                continue
            handled, full_json_mode = _handle_runtime_interactive_command(
                goal,
                full_json_mode,
                session_memory,
                last_payload,
                session_memory_path=session_memory_path,
                trace_dir=trace_dir,
                provider=provider,
                line_reader=line_reader,
            )
            if handled:
                continue
            _print_invalid_runtime_interactive_command(goal)
            continue
        runtime_goal = _runtime_interactive_goal_with_memory(goal, session_memory)
        progress_sink = _runtime_interactive_progress_sink(
            enabled=interactive_tty and not full_json_mode
        )
        try:
            payload = json_ready(
                run_runtime_agent(
                    runtime_goal,
                    provider=provider,
                    max_iterations=max_iterations,
                    metadata=metadata,
                    tags=tags,
                    event_sink=progress_sink,
                    stream_answers=interactive_tty and not full_json_mode,
                )
            )
        finally:
            _close_runtime_progress_sink(progress_sink)
        if trace_dir and persist_trace is not None:
            persist_runtime_cli_trace_or_raise(payload, trace_dir, persist_trace)
        _print_runtime_interactive_payload(
            payload,
            full_json=full_json_mode or not interactive_tty,
        )
        if payload.get("status") == "requires_approval" and interactive_tty:
            payload = _maybe_run_approved_runtime_action(
                payload=payload,
                goal=runtime_goal,
                run_runtime_agent=run_runtime_agent,
                metadata=metadata,
                tags=tags,
                progress_enabled=not full_json_mode,
            )
            if payload is not None:
                if trace_dir and persist_trace is not None:
                    persist_runtime_cli_trace_or_raise(payload, trace_dir, persist_trace)
                _print_runtime_interactive_payload(
                    payload,
                    full_json=full_json_mode,
                )
        last_payload = payload
        _remember_runtime_interactive_turn(session_memory, goal, payload)
        save_runtime_session_memory(session_memory_path, session_memory)
        if fail_on_agent_failure and payload.get("status") == "failed":
            raise SystemExit(1)


def _enable_interactive_line_editing() -> None:
    try:
        import readline  # noqa: F401
    except ImportError:
        return


class _RuntimeLineReader:
    def read(self, *, color: bool) -> str:
        raise NotImplementedError

    def clear_history(self) -> None:
        return

    def line_editor_name(self) -> str:
        return "input"


class _InputLineReader(_RuntimeLineReader):
    def read(self, *, color: bool) -> str:
        return input(runtime_prompt(color=color))

    def line_editor_name(self) -> str:
        return "readline/input"


class _PromptToolkitLineReader(_RuntimeLineReader):
    def __init__(self, session: Any):
        self._session = session

    def read(self, *, color: bool) -> str:
        message: Any = [("class:prompt", "› ")] if color else "› "
        return self._session.prompt(
            message,
            wrap_lines=True,
            multiline=False,
        )

    def clear_history(self) -> None:
        history = getattr(self._session, "history", None)
        loaded_strings = getattr(history, "_loaded_strings", None)
        if isinstance(loaded_strings, list):
            loaded_strings.clear()

    def line_editor_name(self) -> str:
        return "prompt_toolkit"


def _runtime_interactive_line_reader(prompt_stream: Any) -> _RuntimeLineReader:
    prompt_toolkit_session = _prompt_toolkit_session_for_tty(prompt_stream)
    if prompt_toolkit_session is not None:
        return _PromptToolkitLineReader(prompt_toolkit_session)
    _enable_interactive_line_editing()
    return _InputLineReader()


def _prompt_toolkit_session_for_tty(prompt_stream: Any) -> Any:
    if sys.stdin is not getattr(sys, "__stdin__", None):
        return None
    if not _stream_is_tty(sys.stdin):
        return None
    if not _stream_is_tty(prompt_stream):
        return None
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import WordCompleter
        from prompt_toolkit.styles import Style
    except ImportError:
        return None
    completer = WordCompleter(
        runtime_interactive_completion_words(),
        ignore_case=True,
        sentence=True,
    )
    return PromptSession(
        complete_while_typing=True,
        completer=completer,
        enable_history_search=True,
        history=runtime_prompt_history(default_runtime_history_path()),
        style=Style.from_dict({"prompt": "ansicyan"}),
    )


def _stream_is_tty(stream: Any) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(callable(isatty) and isatty())


def _print_runtime_interactive_payload(payload: Any, *, full_json: bool) -> None:
    if full_json:
        print(format_and_write_json(payload, ""))
        return
    if sys.stdin.isatty():
        print()
    print(
        format_runtime_interactive_summary(
            payload,
            color=runtime_ui_color_enabled(),
        )
    )
    if sys.stdin.isatty():
        print()


def _runtime_interactive_progress_sink(*, enabled: bool) -> Any:
    if not enabled:
        return None
    return _RuntimeInteractiveProgress()


def _close_runtime_progress_sink(progress_sink: Any) -> None:
    close = getattr(progress_sink, "close", None)
    if callable(close):
        close()


def _erase_empty_runtime_prompt_line() -> None:
    sys.stdout.write("\x1b[1A\r\x1b[2K")
    sys.stdout.flush()


class _RuntimeInteractiveProgress:
    _FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(self) -> None:
        self._message = ""
        self._frame_index = 0
        self._last_width = 0
        self._started = False
        self._closed = False
        self._active = False
        self._streaming_answer = False
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def __call__(self, event: Any) -> None:
        if isinstance(event, dict):
            event_type = str(event.get("type", "")).strip()
            if event_type == "answer_started":
                self._start_answer_stream()
                return
            if event_type == "answer_delta":
                self._write_answer_delta(str(event.get("delta", "")))
                return
            if event_type == "answer_completed":
                self._finish_answer_stream()
                return
        message = format_runtime_progress_event(
            event,
            color=runtime_ui_color_enabled(),
        )
        if not message or not isinstance(event, dict):
            return
        event_type = str(event.get("type", "")).strip()
        if event_type in {"planner_started", "planner_completed", "tool_started"}:
            self._start_or_update(message)
            return
        self._finish_active(clear=True)
        self._write_line(message)

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._finish_active(clear=True)

    def _start_or_update(self, message: str) -> None:
        with self._lock:
            if self._closed:
                return
            self._message = message
            if not self._started:
                sys.stdout.write("\n")
                self._started = True
            self._active = True
            self._render_locked()
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._spin, daemon=True)
                self._thread.start()

    def _finish_active(self, *, clear: bool) -> None:
        thread: threading.Thread | None
        with self._lock:
            self._active = False
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.25)
        with self._lock:
            if clear:
                self._clear_locked()

    def _write_line(self, message: str) -> None:
        with self._lock:
            if not self._started:
                sys.stdout.write("\n")
                self._started = True
            sys.stdout.write(f"{message}\n")
            sys.stdout.flush()
            self._last_width = 0

    def _start_answer_stream(self) -> None:
        self._finish_active(clear=True)
        with self._lock:
            if not self._started:
                sys.stdout.write("\n")
                self._started = True
            if not self._streaming_answer:
                sys.stdout.write("Answer\n  ")
                self._streaming_answer = True
                self._last_width = 0
                sys.stdout.flush()

    def _write_answer_delta(self, delta: str) -> None:
        if not delta:
            return
        with self._lock:
            if not self._streaming_answer:
                if not self._started:
                    sys.stdout.write("\n")
                    self._started = True
                sys.stdout.write("Answer\n  ")
                self._streaming_answer = True
            sys.stdout.write(delta)
            sys.stdout.flush()

    def _finish_answer_stream(self) -> None:
        with self._lock:
            if self._streaming_answer:
                sys.stdout.write("\n")
                sys.stdout.flush()
                self._streaming_answer = False
                self._last_width = 0

    def _spin(self) -> None:
        while True:
            time.sleep(0.12)
            with self._lock:
                if self._closed or not self._active:
                    return
                self._frame_index += 1
                self._render_locked()

    def _render_locked(self) -> None:
        frame = self._FRAMES[self._frame_index % len(self._FRAMES)]
        line = f"  {frame} {self._message}"
        padding = " " * max(0, self._last_width - len(line))
        sys.stdout.write(f"\r{line}{padding}")
        sys.stdout.flush()
        self._last_width = len(line)

    def _clear_locked(self) -> None:
        if self._last_width:
            sys.stdout.write("\r" + (" " * self._last_width) + "\r")
            sys.stdout.flush()
            self._last_width = 0


def _handle_runtime_interactive_command(
    command: str,
    full_json_mode: bool,
    session_memory: RuntimeSessionMemory,
    last_payload: Any,
    *,
    session_memory_path: str = "",
    trace_dir: str = "",
    provider: Any = None,
    line_reader: Any = None,
) -> tuple[bool, bool]:
    normalized = command.strip().lower()
    if normalized in {"/json", "/full", "/debug"}:
        print(format_runtime_notice("Output mode", "full JSON traces"))
        return True, True
    if normalized in {"/compact", "/summary"}:
        print(format_runtime_notice("Output mode", "compact transcript"))
        return True, False
    if normalized in {"/help", "/?"}:
        print(runtime_interactive_help())
        return True, full_json_mode
    if normalized in {"/pwd", "/cwd"}:
        print(format_runtime_notice("Working directory", os.getcwd()))
        return True, full_json_mode
    if normalized == "/cd" or normalized.startswith("/cd "):
        _change_runtime_interactive_directory(command)
        return True, full_json_mode
    if normalized in {"/status", "/stat"}:
        print(
            format_runtime_interactive_status(
                cwd=os.getcwd(),
                full_json_mode=full_json_mode,
                session_memory=session_memory,
                last_payload=last_payload,
                trace_dir=trace_dir,
            )
        )
        return True, full_json_mode
    if normalized in {"/doctor", "/diagnostics"}:
        line_editor = ""
        if line_reader is not None:
            line_editor_name = getattr(line_reader, "line_editor_name", None)
            if callable(line_editor_name):
                line_editor = str(line_editor_name())
        print(
            format_runtime_interactive_doctor(
                cwd=os.getcwd(),
                provider=provider,
                session_memory_path=session_memory_path,
                history_path=default_runtime_history_path(),
                trace_dir=trace_dir,
                line_editor=line_editor,
            )
        )
        return True, full_json_mode
    if normalized in {"/config", "/provider"}:
        print(format_runtime_provider_config(provider))
        return True, full_json_mode
    if normalized in {"/tools", "/actions"}:
        from kagent.runtime.tools import registered_runtime_tool_metadata

        print(format_runtime_interactive_tools(registered_runtime_tool_metadata()))
        return True, full_json_mode
    if normalized in {"/memory", "/mem"}:
        print(format_runtime_session_memory(session_memory))
        return True, full_json_mode
    if normalized in {"/compact-memory", "/compress-memory"}:
        before_count = session_memory.compacted_turn_count
        compact_runtime_session_memory(
            session_memory,
            max_recent_turns=_INTERACTIVE_MEMORY_RECENT_TURNS,
            max_summary_chars=_INTERACTIVE_MEMORY_SUMMARY_CHARS,
            max_facts=_INTERACTIVE_MEMORY_MAX_FACTS,
            max_open_items=_INTERACTIVE_MEMORY_MAX_OPEN_ITEMS,
        )
        save_runtime_session_memory(session_memory_path, session_memory)
        compacted_now = session_memory.compacted_turn_count - before_count
        detail = (
            f"{compacted_now} turn{'s' if compacted_now != 1 else ''} compacted"
            if compacted_now
            else "already compact"
        )
        print(format_runtime_notice("Memory compacted", detail))
        return True, full_json_mode
    if normalized in {"/last", "/last-run"}:
        if last_payload is None:
            print(format_runtime_notice("Last run", "no previous run"))
        else:
            _print_runtime_interactive_payload(last_payload, full_json=False)
        return True, full_json_mode
    if normalized in {"/trace", "/last-json"}:
        if last_payload is None:
            print(format_runtime_notice("Last run", "no previous run"))
        else:
            _print_runtime_interactive_payload(last_payload, full_json=True)
        return True, full_json_mode
    if normalized == "/save-trace" or normalized.startswith("/save-trace "):
        _save_last_runtime_trace(command, last_payload)
        return True, full_json_mode
    if normalized == "/export-trace" or normalized.startswith("/export-trace "):
        _save_last_runtime_trace(command, last_payload)
        return True, full_json_mode
    if normalized in {"/clear", "/clear-memory"}:
        session_memory.clear()
        save_runtime_session_memory(session_memory_path, session_memory)
        print(format_runtime_notice("Memory", "cleared"))
        return True, full_json_mode
    if normalized in {"/reset", "/reset-session"}:
        session_memory.clear()
        save_runtime_session_memory(session_memory_path, session_memory)
        clear_runtime_history(default_runtime_history_path())
        if line_reader is not None:
            clear_history = getattr(line_reader, "clear_history", None)
            if callable(clear_history):
                clear_history()
        print(format_runtime_notice("Reset", "memory and prompt history cleared"))
        return True, full_json_mode
    return False, full_json_mode


def _print_unknown_runtime_interactive_command(command: str) -> None:
    suggestions = runtime_interactive_command_suggestions(command)
    detail = "try /help"
    if suggestions:
        detail = "try " + ", ".join(suggestions)
    print(format_runtime_notice("Unknown command", detail))


def _print_invalid_runtime_interactive_command(command: str) -> None:
    usage = runtime_interactive_command_usage(command)
    detail = f"usage: {usage}" if usage else "try /help"
    print(format_runtime_notice("Invalid command", detail))


def _save_last_runtime_trace(command: str, last_payload: Any) -> None:
    if last_payload is None:
        print(format_runtime_notice("Last run", "no previous run"))
        return
    try:
        parts = shlex.split(command.strip())
    except ValueError as exc:
        print(format_runtime_notice("Save trace failed", str(exc)))
        return
    if len(parts) < 2 or not parts[1].strip():
        print(format_runtime_notice("Save trace", "path required: /save-trace PATH"))
        return
    try:
        saved_path = save_runtime_trace_snapshot_or_raise(
            last_payload,
            parts[1].strip(),
        )
    except (OSError, ValueError) as exc:
        print(format_runtime_notice("Save trace failed", str(exc)))
        return
    print(format_runtime_notice("Trace saved", saved_path))


def _change_runtime_interactive_directory(command: str) -> None:
    raw_path = command.strip()[3:].strip()
    target = os.path.expanduser(raw_path or "~")
    if not os.path.isabs(target):
        target = os.path.abspath(target)
    if not os.path.isdir(target):
        print(format_runtime_notice("Directory not found", target))
        return
    os.chdir(target)
    print(format_runtime_notice("Working directory", os.getcwd()))


def _runtime_interactive_goal_with_memory(
    goal: str,
    session_memory: RuntimeSessionMemory,
) -> str:
    if not session_memory:
        return goal
    memory_lines = _runtime_compact_memory_lines(session_memory)
    recent_lines = []
    for turn in session_memory.turns[-_INTERACTIVE_MEMORY_MAX_TURNS:]:
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
    if len(memory_text) > _INTERACTIVE_MEMORY_MAX_CHARS:
        memory_text = memory_text[-_INTERACTIVE_MEMORY_MAX_CHARS:]
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


def _remember_runtime_interactive_turn(
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
        max_recent_turns=_INTERACTIVE_MEMORY_RECENT_TURNS,
        max_summary_chars=_INTERACTIVE_MEMORY_SUMMARY_CHARS,
        max_facts=_INTERACTIVE_MEMORY_MAX_FACTS,
        max_open_items=_INTERACTIVE_MEMORY_MAX_OPEN_ITEMS,
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
        snippets.append(
            join_non_empty(
                [
                    tool,
                    status,
                    output_summary,
                ],
                " ",
            )
        )
    return "; ".join(snippet for snippet in snippets if snippet)


def _compact_runtime_memory_text(text: str) -> str:
    compact = " ".join(redact_runtime_session_memory_text(str(text)).split())
    if len(compact) > 500:
        return compact[:497] + "..."
    return compact


def _maybe_run_approved_runtime_action(
    *,
    payload: Any,
    goal: str,
    run_runtime_agent: Any,
    metadata: dict[str, str] | None = None,
    tags: list[str] | None = None,
    progress_enabled: bool = True,
) -> Any:
    pending = payload.get("pending_approval") if isinstance(payload, dict) else None
    if not isinstance(pending, dict):
        return None
    action_id = str(pending.get("id", "")).strip()
    tool = str(pending.get("tool", "")).strip()
    if not action_id or not tool:
        return None
    while True:
        answer = input(
            approval_prompt(action_id, tool, color=runtime_ui_color_enabled())
        ).strip().lower()
        if answer in {"d", "detail", "details", "view"}:
            print(format_runtime_pending_approval_detail(pending))
            continue
        break
    if answer not in {"y", "yes", "approve"}:
        print(format_runtime_notice("Approval skipped", "action not approved"))
        return None
    progress_sink = _runtime_interactive_progress_sink(enabled=progress_enabled)
    try:
        return json_ready(
            run_runtime_agent(
                goal,
                provider=_InlineRuntimePlanProvider({"actions": [pending]}),
                max_iterations=1,
                approved_action_ids={action_id},
                metadata=metadata,
                tags=tags,
                event_sink=progress_sink,
            )
        )
    finally:
        _close_runtime_progress_sink(progress_sink)


class _InlineRuntimePlanProvider:
    def __init__(self, plan: dict) -> None:
        self.plan = plan

    def complete(self, _system: str, _user: str) -> str:
        return json.dumps(self.plan, ensure_ascii=False, sort_keys=True)
