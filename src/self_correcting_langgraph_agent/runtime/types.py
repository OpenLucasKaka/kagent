from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

MAX_PLAN_ACTIONS = 50
MAX_ACTION_REASON_CHARS = 2000
MAX_PLAN_FINAL_ANSWER_CHARS = 20000
_PLAN_FIELDS = {"actions", "final_answer"}
_ACTION_FIELDS = {"id", "tool", "input", "reason", "depends_on"}


@dataclass(frozen=True)
class AgentAction:
    id: str
    tool: str
    input: Dict[str, Any]
    reason: str = ""
    depends_on: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "id": self.id,
            "tool": self.tool,
            "input": self.input,
            "reason": self.reason,
        }
        if self.depends_on:
            payload["depends_on"] = self.depends_on
        return payload


@dataclass(frozen=True)
class AgentPlan:
    actions: List[AgentAction]
    final_answer: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "actions": [action.to_dict() for action in self.actions]
        }
        if self.final_answer:
            payload["final_answer"] = self.final_answer
        return payload


@dataclass(frozen=True)
class AgentObservation:
    action_id: str
    tool: str
    status: str
    output: Dict[str, Any]
    error_code: str = ""
    error: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "action_id": self.action_id,
            "tool": self.tool,
            "status": self.status,
            "output": self.output,
        }
        if self.error_code:
            payload["error_code"] = self.error_code
        if self.error:
            payload["error"] = self.error
        if self.started_at:
            payload["started_at"] = self.started_at
        if self.completed_at:
            payload["completed_at"] = self.completed_at
        if self.duration_seconds:
            payload["duration_seconds"] = self.duration_seconds
        return payload


def parse_agent_plan(text: str) -> AgentPlan:
    payload = _parse_plan_json_object(text)
    if not isinstance(payload, dict):
        raise ValueError("plan must be a JSON object")
    _reject_unknown_fields(payload, _PLAN_FIELDS, "plan")
    actions_payload = payload.get("actions")
    if not isinstance(actions_payload, list):
        raise ValueError("plan actions must be a list")
    if len(actions_payload) > MAX_PLAN_ACTIONS:
        raise ValueError(f"plan actions must contain at most {MAX_PLAN_ACTIONS} item(s)")
    final_answer = payload.get("final_answer", "")
    if not isinstance(final_answer, str):
        raise ValueError("final_answer must be a string")
    if len(final_answer) > MAX_PLAN_FINAL_ANSWER_CHARS:
        raise ValueError(
            f"final_answer must contain at most {MAX_PLAN_FINAL_ANSWER_CHARS} character(s)"
        )

    actions = []
    seen_action_ids = set()
    for index, action_payload in enumerate(actions_payload):
        if not isinstance(action_payload, dict):
            raise ValueError(f"action {index} must be an object")
        _reject_unknown_fields(action_payload, _ACTION_FIELDS, "action")
        action_id = action_payload.get("id")
        if not isinstance(action_id, str) or not action_id.strip():
            raise ValueError("action id is required")
        if action_id != action_id.strip():
            raise ValueError("action id must not contain surrounding whitespace")
        if action_id in seen_action_ids:
            raise ValueError(f"duplicate action id: {action_id}")
        tool = action_payload.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            raise ValueError("action tool is required")
        if tool != tool.strip():
            raise ValueError("action tool must not contain surrounding whitespace")
        action_input = action_payload.get("input", {})
        if not isinstance(action_input, dict):
            raise ValueError("action input must be an object")
        reason = action_payload.get("reason", "")
        if not isinstance(reason, str):
            raise ValueError("action reason must be a string")
        if len(reason) > MAX_ACTION_REASON_CHARS:
            raise ValueError(
                f"action reason must contain at most {MAX_ACTION_REASON_CHARS} character(s)"
            )
        depends_on = _parse_action_dependencies(
            action_payload.get("depends_on", []),
            seen_action_ids,
        )
        seen_action_ids.add(action_id)
        actions.append(
            AgentAction(
                id=action_id,
                tool=tool,
                input=action_input,
                reason=reason,
                depends_on=depends_on,
            )
        )
    return AgentPlan(actions=actions, final_answer=final_answer)


def _parse_plan_json_object(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        strict_error = exc
    decoder = json.JSONDecoder()
    candidates = []
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            payload, _end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "actions" in payload:
            candidates.append(payload)
    if candidates:
        return candidates[-1]
    raise ValueError(f"plan JSON is invalid: {strict_error}") from strict_error


def _reject_unknown_fields(
    payload: Dict[str, Any],
    allowed_fields: set,
    label: str,
) -> None:
    for field_name in payload:
        if field_name not in allowed_fields:
            raise ValueError(f"{label} field is not allowed: {field_name}")


def _parse_action_dependencies(value: Any, seen_action_ids: set) -> List[str]:
    if not isinstance(value, list):
        raise ValueError("action depends_on must be a list")
    dependencies = []
    seen_dependencies = set()
    for dependency in value:
        if not isinstance(dependency, str):
            raise ValueError("action dependency must be a string")
        if not dependency.strip():
            raise ValueError("action dependency is required")
        if dependency != dependency.strip():
            raise ValueError("action dependency must not contain surrounding whitespace")
        if dependency not in seen_action_ids:
            raise ValueError(f"unknown or later action dependency: {dependency}")
        if dependency in seen_dependencies:
            raise ValueError(f"duplicate action dependency: {dependency}")
        seen_dependencies.add(dependency)
        dependencies.append(dependency)
    return dependencies
