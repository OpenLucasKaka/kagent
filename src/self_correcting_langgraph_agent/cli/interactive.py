from __future__ import annotations

import json
import sys
from typing import Any

from self_correcting_langgraph_agent.cli.memory import (
    load_runtime_session_memory,
    save_runtime_session_memory,
)
from self_correcting_langgraph_agent.cli.trace import persist_runtime_cli_trace_or_raise
from self_correcting_langgraph_agent.cli.ui import (
    approval_prompt,
    format_runtime_interactive_summary,
    format_runtime_progress_event,
    format_runtime_session_memory,
    join_non_empty,
    runtime_interactive_help,
    runtime_prompt,
    runtime_ready_message,
    runtime_ui_color_enabled,
    summarize_runtime_output,
)
from self_correcting_langgraph_agent.utils.json_output import format_and_write_json, json_ready

_INTERACTIVE_MEMORY_MAX_TURNS = 12
_INTERACTIVE_MEMORY_MAX_CHARS = 4000


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
    if interactive_tty:
        _enable_interactive_line_editing()
        print(runtime_ready_message(color=runtime_ui_color_enabled()), file=prompt_stream)
    while True:
        try:
            line = (
                input(runtime_prompt(color=runtime_ui_color_enabled()))
                if interactive_tty
                else sys.stdin.readline()
            )
        except EOFError:
            return
        if not interactive_tty and line == "":
            return
        goal = line.strip()
        if not goal:
            continue
        if goal.lower() in {"exit", "quit", ":q"}:
            return
        if interactive_tty and goal.startswith("/"):
            handled, full_json_mode = _handle_runtime_interactive_command(
                goal,
                full_json_mode,
                session_memory,
                last_payload,
                session_memory_path=session_memory_path,
            )
            if handled:
                continue
        runtime_goal = _runtime_interactive_goal_with_memory(goal, session_memory)
        progress_sink = _runtime_interactive_progress_sink(
            enabled=interactive_tty and not full_json_mode
        )
        payload = json_ready(
            run_runtime_agent(
                runtime_goal,
                provider=provider,
                max_iterations=max_iterations,
                metadata=metadata,
                tags=tags,
                event_sink=progress_sink,
            )
        )
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


def _print_runtime_interactive_payload(payload: Any, *, full_json: bool) -> None:
    if full_json:
        print(format_and_write_json(payload, ""))
        return
    print(
        format_runtime_interactive_summary(
            payload,
            color=runtime_ui_color_enabled(),
        )
    )


def _runtime_interactive_progress_sink(*, enabled: bool) -> Any:
    if not enabled:
        return None

    def emit(event: Any) -> None:
        line = format_runtime_progress_event(
            event,
            color=runtime_ui_color_enabled(),
        )
        if line:
            print(line)

    return emit


def _handle_runtime_interactive_command(
    command: str,
    full_json_mode: bool,
    session_memory: list[dict[str, str]],
    last_payload: Any,
    *,
    session_memory_path: str = "",
) -> tuple[bool, bool]:
    normalized = command.strip().lower()
    if normalized in {"/json", "/full", "/debug"}:
        print("output mode: full JSON")
        return True, True
    if normalized in {"/compact", "/summary"}:
        print("output mode: compact")
        return True, False
    if normalized in {"/help", "/?"}:
        print(runtime_interactive_help())
        return True, full_json_mode
    if normalized in {"/memory", "/mem"}:
        print(format_runtime_session_memory(session_memory))
        return True, full_json_mode
    if normalized in {"/last", "/last-run"}:
        if last_payload is None:
            print("No previous runtime run.")
        else:
            _print_runtime_interactive_payload(last_payload, full_json=False)
        return True, full_json_mode
    if normalized in {"/trace", "/last-json"}:
        if last_payload is None:
            print("No previous runtime run.")
        else:
            _print_runtime_interactive_payload(last_payload, full_json=True)
        return True, full_json_mode
    if normalized in {"/clear", "/clear-memory"}:
        session_memory.clear()
        save_runtime_session_memory(session_memory_path, session_memory)
        print("memory cleared")
        return True, full_json_mode
    return False, full_json_mode


def _runtime_interactive_goal_with_memory(
    goal: str,
    session_memory: list[dict[str, str]],
) -> str:
    if not session_memory:
        return goal
    memory_lines = []
    for turn in session_memory[-_INTERACTIVE_MEMORY_MAX_TURNS:]:
        user = _compact_runtime_memory_text(turn.get("user", ""))
        assistant = _compact_runtime_memory_text(turn.get("assistant", ""))
        if user:
            memory_lines.append(f"User: {user}")
        if assistant:
            memory_lines.append(f"Assistant: {assistant}")
    memory_text = "\n".join(memory_lines)
    if len(memory_text) > _INTERACTIVE_MEMORY_MAX_CHARS:
        memory_text = memory_text[-_INTERACTIVE_MEMORY_MAX_CHARS:]
    return (
        "Conversation memory from this interactive session:\n"
        f"{memory_text}\n\n"
        "Use the memory above to resolve references, user identity, prior "
        "requests, and follow-up questions. Answer the current user message; "
        "do not answer as if the user is asking about the model identity unless "
        "they explicitly ask who the assistant/model is.\n\n"
        "Current user message:\n"
        f"{goal}"
    )


def _remember_runtime_interactive_turn(
    session_memory: list[dict[str, str]],
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
    del session_memory[:-_INTERACTIVE_MEMORY_MAX_TURNS]


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
    compact = " ".join(str(text).split())
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
    answer = input(
        approval_prompt(action_id, tool, color=runtime_ui_color_enabled())
    ).strip().lower()
    if answer not in {"y", "yes", "approve"}:
        return None
    return json_ready(
        run_runtime_agent(
            goal,
            provider=_InlineRuntimePlanProvider({"actions": [pending]}),
            max_iterations=1,
            approved_action_ids={action_id},
            metadata=metadata,
            tags=tags,
            event_sink=_runtime_interactive_progress_sink(enabled=progress_enabled),
        )
    )


class _InlineRuntimePlanProvider:
    def __init__(self, plan: dict) -> None:
        self.plan = plan

    def complete(self, _system: str, _user: str) -> str:
        return json.dumps(self.plan, ensure_ascii=False, sort_keys=True)
