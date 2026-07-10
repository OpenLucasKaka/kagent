from __future__ import annotations

import json
import sys
import warnings
from dataclasses import dataclass
from typing import Any, Dict, Iterable, TextIO

from kagent.cli.conversation import (
    RUNTIME_MEMORY_MAX_TURNS,
    remember_runtime_turn,
    runtime_goal_with_memory,
)
from kagent.cli.memory import (
    default_runtime_session_memory_path,
    load_runtime_session_memory,
    redact_runtime_session_memory_text,
    save_runtime_session_memory,
)
from kagent.cli.provider import RuntimeProviderConfigError, runtime_provider_config_message
from kagent.cli.session_commands import (
    SessionCommandError,
    execute_session_command,
    redacted_provider_snapshot,
)
from kagent.providers.llm import (
    FakeLLMProvider,
    LLMProviderConfig,
    build_llm_provider,
    missing_provider_config_fields,
    provider_setup_options,
    save_provider_config,
    validate_provider_setup_config,
)
from kagent.runtime import build_resumable_plan, run_runtime_agent
from kagent.utils.json_output import json_ready

Request = Dict[str, Any]
DEFAULT_RUNTIME_MAX_ITERATIONS = 3


@dataclass(frozen=True)
class PendingApproval:
    action: Dict[str, Any]
    goal: str
    runtime_goal: str
    plan: Dict[str, Any]


class StdioRuntimeSession:
    def __init__(self, stdout: TextIO, *, memory_path: str | None = None) -> None:
        self.stdout = stdout
        self.memory_path = (
            default_runtime_session_memory_path() if memory_path is None else memory_path
        )
        self.memory = load_runtime_session_memory(
            self.memory_path,
            max_turns=RUNTIME_MEMORY_MAX_TURNS,
        )
        self.provider_config = LLMProviderConfig.from_sources()
        self.pending_approval: PendingApproval | None = None
        self.last_payload: Dict[str, Any] | None = None

    def handle(self, request: Request) -> None:
        request_type = str(request.get("type", ""))
        if request_type == "run_request":
            self._handle_run_request(request)
            return
        if request_type == "approval_response":
            self._handle_approval_response(request)
            return
        if request_type == "provider_configure":
            self._handle_provider_configure(request)
            return
        if request_type == "session_command":
            self._handle_session_command(request)
            return
        self._fail(
            "invalid_request_type",
            "request type must be run_request, approval_response, provider_configure, "
            "or session_command",
        )

    def ready_event(self) -> Dict[str, Any]:
        return {
            "type": "runtime_ready",
            "provider": redacted_provider_snapshot(self.provider_config),
            "provider_options": provider_setup_options(),
        }

    def _handle_run_request(self, request: Request) -> None:
        if self.pending_approval is not None:
            self._fail(
                "approval_pending",
                "respond to the pending approval before starting another request",
            )
            return
        goal = str(request.get("goal", "")).strip()
        if not goal:
            self._fail("missing_goal", "goal is required")
            return
        try:
            max_iterations = _positive_int(
                request.get("max_iterations"),
                default=DEFAULT_RUNTIME_MAX_ITERATIONS,
            )
        except (TypeError, ValueError) as exc:
            self._fail("invalid_request", str(exc))
            return

        _emit(
            self.stdout,
            {
                "type": "run_started",
                "goal": goal,
                "max_iterations": str(max_iterations),
            },
        )
        try:
            provider = _provider_from_request(request, self.provider_config)
            runtime_goal = runtime_goal_with_memory(goal, self.memory)
            result = run_runtime_agent(
                runtime_goal,
                provider=provider,
                max_iterations=max_iterations,
                event_sink=self._progress_sink,
            )
            self._finish_run(goal, runtime_goal, result)
        except RuntimeProviderConfigError as exc:
            self._fail("provider_not_configured", str(exc))
        except Exception as exc:  # pragma: no cover - defensive protocol boundary
            self._fail("runtime_error", str(exc))

    def _handle_provider_configure(self, request: Request) -> None:
        if self.pending_approval is not None:
            self._provider_configuration_failed(
                "approval_pending",
                "respond to the pending approval before changing the provider",
            )
            return
        try:
            config = LLMProviderConfig(
                provider=str(request.get("provider", "")),
                base_url=str(request.get("base_url", "")).strip(),
                api_key=str(request.get("api_key", "")).strip(),
                model=str(request.get("model", "")).strip(),
            )
            validate_provider_setup_config(config)
            save_provider_config(config)
        except (OSError, TypeError, ValueError) as exc:
            message = str(exc)
            self._provider_configuration_failed(
                "invalid_provider_config",
                message,
                field=_provider_error_field(message),
            )
            return
        self.provider_config = config
        _emit(
            self.stdout,
            {
                "type": "provider_configured",
                "provider": redacted_provider_snapshot(config),
            },
        )

    def _handle_session_command(self, request: Request) -> None:
        command = str(request.get("command", "")).strip()
        if self.pending_approval is not None:
            self._session_command_failed(
                command,
                "approval_pending",
                "Respond to the pending approval before running a command.",
            )
            return
        try:
            result = execute_session_command(
                command,
                memory=self.memory,
                memory_path=self.memory_path,
                provider_config=self.provider_config,
                last_payload=self.last_payload,
            )
        except SessionCommandError as exc:
            self._session_command_failed(
                exc.command or command,
                exc.error_code,
                str(exc),
            )
            return
        except (OSError, TypeError, ValueError) as exc:
            self._session_command_failed(command, "command_failed", str(exc))
            return
        _emit(self.stdout, result.event())

    def _handle_approval_response(self, request: Request) -> None:
        pending = self.pending_approval
        if pending is None:
            self._fail("no_pending_approval", "there is no action waiting for approval")
            return
        action_id = str(request.get("action_id", "")).strip()
        expected_action_id = str(pending.action.get("id", "")).strip()
        if action_id != expected_action_id:
            self._fail("approval_mismatch", "approval action_id does not match")
            return
        approved = request.get("approved")
        if not isinstance(approved, bool):
            self._fail("invalid_request", "approved must be a boolean")
            return

        self.pending_approval = None
        if not approved:
            result = {
                "status": "cancelled",
                "answer": "The requested action was not performed.",
                "goal": pending.runtime_goal,
                "approval": {"action_id": action_id, "approved": "false"},
            }
            self._complete(pending.goal, result)
            return

        resumable_plan = build_resumable_plan(pending.plan, pending.action)
        if resumable_plan is None:
            self._fail("invalid_approval_state", "pending approval cannot be resumed")
            return
        try:
            result = run_runtime_agent(
                pending.runtime_goal,
                provider=FakeLLMProvider(
                    json.dumps(resumable_plan, ensure_ascii=False, sort_keys=True)
                ),
                max_iterations=1,
                approved_action_ids={action_id},
                event_sink=self._progress_sink,
            )
            self._finish_run(pending.goal, pending.runtime_goal, result)
        except Exception as exc:  # pragma: no cover - defensive protocol boundary
            self._fail("runtime_error", str(exc))

    def _finish_run(self, goal: str, runtime_goal: str, result: Any) -> None:
        payload = json_ready(result)
        if not isinstance(payload, dict):
            self._fail("runtime_error", "runtime result must be an object")
            return
        payload["goal"] = goal
        if payload.get("status") == "requires_approval":
            pending = _pending_approval_from_result(payload, goal, runtime_goal)
            if pending is None:
                self._fail("invalid_approval_state", "runtime approval state is incomplete")
                return
            self.pending_approval = pending
            _emit(self.stdout, _approval_event(pending.action))
            return
        self._complete(goal, payload)

    def _complete(self, goal: str, payload: Dict[str, Any]) -> None:
        remember_runtime_turn(self.memory, goal, payload)
        save_runtime_session_memory(self.memory_path, self.memory)
        self.last_payload = dict(payload)
        _emit(
            self.stdout,
            {
                "type": "run_completed",
                "status": str(payload.get("status", "done")),
                "answer": str(payload.get("answer", "")),
                "payload": payload,
            },
        )

    def _progress_sink(self, event: Dict[str, Any]) -> None:
        _emit(self.stdout, {"type": "run_progress", "event": event})

    def _fail(self, error_code: str, message: str) -> None:
        _emit(
            self.stdout,
            {"type": "run_failed", "error_code": error_code, "message": message},
        )

    def _provider_configuration_failed(
        self,
        error_code: str,
        message: str,
        *,
        field: str = "",
    ) -> None:
        payload = {
            "type": "provider_configuration_failed",
            "error_code": error_code,
            "message": message,
        }
        if field:
            payload["field"] = field
        _emit(self.stdout, payload)

    def _session_command_failed(
        self,
        command: str,
        error_code: str,
        message: str,
    ) -> None:
        _emit(
            self.stdout,
            {
                "type": "session_command_failed",
                "command": command,
                "error_code": error_code,
                "message": message,
            },
        )


def main() -> None:
    warnings.filterwarnings("ignore")
    run_stdio_runtime(sys.stdin, sys.stdout)


def run_stdio_runtime(stdin: TextIO, stdout: TextIO) -> None:
    try:
        session = StdioRuntimeSession(stdout)
    except (OSError, ValueError) as exc:
        _emit(
            stdout,
            {
                "type": "runtime_unavailable",
                "message": str(exc),
            },
        )
        return
    _emit(stdout, session.ready_event())
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = _parse_request(line)
        except ValueError as exc:
            session._fail("invalid_json", str(exc))
            continue
        session.handle(request)


def _parse_request(line: str) -> Request:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON request: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("request must be a JSON object")
    return payload


def _pending_approval_from_result(
    payload: Dict[str, Any],
    goal: str,
    runtime_goal: str,
) -> PendingApproval | None:
    action = payload.get("pending_approval")
    plan = payload.get("plan")
    if not isinstance(action, dict) or not isinstance(plan, dict):
        return None
    if not str(action.get("id", "")).strip():
        return None
    return PendingApproval(dict(action), goal, runtime_goal, dict(plan))


def _approval_event(action: Dict[str, Any]) -> Dict[str, Any]:
    action_input = action.get("input")
    safe_input = action_input if isinstance(action_input, dict) else {}
    return {
        "type": "approval_required",
        "action_id": str(action.get("id", "")),
        "title": _approval_title(str(action.get("tool", ""))),
        "reason": _bounded_text(action.get("reason"), 500),
        "target": _approval_target(safe_input),
    }


def _approval_title(tool: str) -> str:
    return {
        "open_url": "Open a website",
        "open_app": "Open an application",
        "http_request": "Contact an external service",
        "shell_command": "Run a system command",
        "apply_patch": "Modify workspace files",
        "write_file": "Create or update a file",
    }.get(tool, "Perform an external action")


def _approval_target(action_input: Dict[str, Any]) -> str:
    for key in ("url", "application", "path", "command", "query"):
        if key in action_input:
            return _bounded_text(action_input[key], 500)
    return ""


def _bounded_text(value: Any, limit: int) -> str:
    text = " ".join(redact_runtime_session_memory_text(str(value or "")).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _provider_from_request(request: Request, config: LLMProviderConfig) -> Any:
    runtime_plan = str(request.get("runtime_plan", "")).strip()
    if runtime_plan:
        return FakeLLMProvider(runtime_plan)
    missing = missing_provider_config_fields(config)
    if missing:
        raise RuntimeProviderConfigError(runtime_provider_config_message(missing))
    return build_llm_provider(config)


def _provider_error_field(message: str) -> str:
    normalized = message.lower()
    if "base_url" in normalized:
        return "base_url"
    if "model" in normalized:
        return "model"
    if "api_key" in normalized:
        return "api_key"
    return ""


def _positive_int(value: Any, *, default: int) -> int:
    if value in (None, ""):
        return default
    parsed = int(value)
    if parsed < 1:
        raise ValueError("max_iterations must be at least 1")
    return parsed


def _emit(stdout: TextIO, payload: Dict[str, Any]) -> None:
    stdout.write(json.dumps(json_ready(payload), ensure_ascii=False, sort_keys=True) + "\n")
    stdout.flush()


__all__: Iterable[str] = ["StdioRuntimeSession", "run_stdio_runtime", "main"]


if __name__ == "__main__":
    main()
