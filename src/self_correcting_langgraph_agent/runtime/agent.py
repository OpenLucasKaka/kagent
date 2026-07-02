from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

from self_correcting_langgraph_agent.runtime.metadata import (
    validate_runtime_metadata,
    validate_runtime_tags,
)
from self_correcting_langgraph_agent.runtime.policy import RuntimePolicy
from self_correcting_langgraph_agent.runtime.tools import (
    RuntimeToolSpec,
    default_runtime_tools,
    execute_runtime_tool,
    runtime_tool_metadata,
)
from self_correcting_langgraph_agent.runtime.types import (
    MAX_ACTION_REASON_CHARS,
    MAX_PLAN_ACTIONS,
    MAX_PLAN_FINAL_ANSWER_CHARS,
    AgentObservation,
    parse_agent_plan,
)

_SYSTEM_PROMPT = (
    """You are a production agent planner.
Your product identity is "self-correcting LangGraph agent runtime", a
non-coding Codex-style runtime that runs inside the user's current CLI or
service process. The LLM is only a replaceable OpenAI-compatible provider.
Never answer user identity, deployment, ownership, or hosting questions as if
you are the underlying model provider. Do not claim to be Qwen, ChatGPT,
Claude, or any other model brand unless the user explicitly asks about the
configured provider.
Return strict JSON only with this shape:
{"actions":[{"id":"step-1","tool":"note","input":{"text":"..."},"reason":"..."}],
"final_answer":"..."}
Use only tools that are available to you.
"""
    f"Return at most {MAX_PLAN_ACTIONS} actions in one plan.\n"
    f"Keep action reason at most {MAX_ACTION_REASON_CHARS} characters.\n"
    f"Keep final_answer at most {MAX_PLAN_FINAL_ANSWER_CHARS} characters; "
    "use artifact for long-form deliverables.\n"
    "Use optional depends_on with prior action IDs when one action depends on earlier output.\n"
    "Use open_url to open a browser page; use http_request only to fetch URL "
    "content as an observation.\n"
    "Use list_files and read_file to observe workspace state before changing "
    "workspace files with apply_patch.\n"
    'If the goal is complete, return {"actions":[]}.'
)

RUNTIME_TRACE_TYPE = "codex_runtime"
MAX_PLANNER_OBSERVATION_STRING_CHARS = 500
RuntimeEventSink = Callable[[Dict[str, Any]], None]


def run_runtime_agent(
    goal: str,
    *,
    provider: Any,
    policy: Optional[RuntimePolicy] = None,
    tools: Optional[Dict[str, RuntimeToolSpec]] = None,
    max_iterations: int = 1,
    approved_action_ids: Optional[Set[str]] = None,
    metadata: Optional[Dict[str, str]] = None,
    tags: Optional[List[str]] = None,
    event_sink: Optional[RuntimeEventSink] = None,
) -> Dict[str, Any]:
    if max_iterations < 1:
        raise ValueError("max_iterations must be at least 1")
    normalized_metadata, metadata_error = validate_runtime_metadata(metadata)
    if metadata_error:
        raise ValueError(metadata_error)
    normalized_tags, tags_error = validate_runtime_tags(tags)
    if tags_error:
        raise ValueError(tags_error)
    run_id = str(uuid4())
    events = []
    started_at = _utc_timestamp()
    started_timer = time.perf_counter()
    active_policy = policy or RuntimePolicy()
    active_tools = tools or default_runtime_tools()
    active_approvals = set(approved_action_ids or set())
    approved_action_id_list = sorted(active_approvals)
    status = "done"
    observations: List[AgentObservation] = []
    plans: List[Dict[str, Any]] = []
    latest_plan = {"actions": []}
    answer = ""
    final_answer_guardrail: Dict[str, str] = {}
    pending_approval: Dict[str, Any] = {}
    iteration_count = 0
    progress_events: List[Dict[str, Any]] = []

    def emit_progress(event: Dict[str, Any]) -> None:
        progress_events.append(event)
        if event_sink is not None:
            event_sink(event)

    for iteration in range(1, max_iterations + 1):
        iteration_count = iteration
        iteration_label = str(iteration)
        user_prompt = _runtime_user_prompt(goal, active_tools, observations)
        planner_started_at = _utc_timestamp()
        planner_timer = time.perf_counter()
        events.append(
            {
                "node": "planner",
                "status": "started",
                "iteration": iteration_label,
                "started_at": planner_started_at,
            }
        )
        _emit_runtime_progress(
            emit_progress,
            "planner_started",
            iteration=iteration_label,
            node="planner",
            status="started",
        )
        try:
            plan_text = provider.complete(_SYSTEM_PROMPT, user_prompt)
            plan = parse_agent_plan(plan_text)
        except Exception as exc:
            timing = _timing_fields(planner_started_at, planner_timer)
            events[-1] = {
                "node": "planner",
                "status": "failed",
                "iteration": iteration_label,
                **timing,
            }
            observations.append(
                AgentObservation(
                    action_id="",
                    tool="planner",
                    status="failed",
                    output={},
                    error_code="invalid_plan",
                    error=str(exc),
                    started_at=planner_started_at,
                    completed_at=timing["completed_at"],
                    duration_seconds=timing["duration_seconds"],
                )
            )
            _emit_runtime_progress(
                emit_progress,
                "planner_failed",
                iteration=iteration_label,
                node="planner",
                status="failed",
                error_code="invalid_plan",
                duration_seconds=timing["duration_seconds"],
            )
            if iteration < max_iterations:
                continue
            status = "failed"
            break
        latest_plan = plan.to_dict()
        plans.append(latest_plan)
        events[-1] = {
            "node": "planner",
            "status": "ok",
            "action_count": str(len(plan.actions)),
            "iteration": iteration_label,
            **_timing_fields(planner_started_at, planner_timer),
        }
        _emit_runtime_progress(
            emit_progress,
            "planner_completed",
            iteration=iteration_label,
            node="planner",
            status="ok",
            action_count=str(len(plan.actions)),
            duration_seconds=events[-1]["duration_seconds"],
        )
        if not plan.actions:
            if plan.final_answer:
                answer, final_answer_guardrail = _runtime_final_answer(
                    goal,
                    plan.final_answer,
                )
            break

        should_replan = False
        iteration_observations: Dict[str, AgentObservation] = {}
        for action in plan.actions:
            policy_started_at = _utc_timestamp()
            policy_timer = time.perf_counter()
            decision = active_policy.authorize(action.tool, action.input)
            policy_status = (
                "approved"
                if decision.status != "allowed" and action.id in active_approvals
                else decision.status
            )
            dependency_metadata = _action_dependency_event_metadata(
                action.depends_on,
                iteration_observations,
            )
            events.append(
                {
                    "node": "policy",
                    "action_id": action.id,
                    "tool": action.tool,
                    "status": policy_status,
                    "reason": decision.reason,
                    "iteration": iteration_label,
                    **dependency_metadata,
                    **_timing_fields(policy_started_at, policy_timer),
                }
            )
            _emit_runtime_progress(
                emit_progress,
                "policy_completed",
                iteration=iteration_label,
                node="policy",
                action_id=action.id,
                tool=action.tool,
                status=policy_status,
                reason=decision.reason,
                duration_seconds=events[-1]["duration_seconds"],
            )
            if decision.status != "allowed" and action.id not in active_approvals:
                pending_approval = action.to_dict()
                approval_started_at = _utc_timestamp()
                approval_timer = time.perf_counter()
                observations.append(
                    AgentObservation(
                        action_id=action.id,
                        tool=action.tool,
                        status="requires_approval",
                        output={},
                        error_code=decision.reason or "policy_denied",
                        error="tool execution requires approval",
                        started_at=approval_started_at,
                        completed_at=_utc_timestamp(),
                        duration_seconds=_duration_since(approval_timer),
                    )
                )
                _emit_runtime_progress(
                    emit_progress,
                    "approval_required",
                    iteration=iteration_label,
                    node="policy",
                    action_id=action.id,
                    tool=action.tool,
                    status="requires_approval",
                    reason=decision.reason or "policy_denied",
                )
                status = "requires_approval"
                break
            _emit_runtime_progress(
                emit_progress,
                "tool_started",
                iteration=iteration_label,
                node="executor",
                action_id=action.id,
                tool=action.tool,
                status="started",
            )
            observation = execute_runtime_tool(
                active_tools,
                action.tool,
                action.input,
                action_id=action.id,
            )
            observations.append(observation)
            iteration_observations[action.id] = observation
            events.append(
                {
                    "node": "executor",
                    "action_id": action.id,
                    "tool": action.tool,
                    "status": observation.status,
                    "iteration": iteration_label,
                    **dependency_metadata,
                    "started_at": observation.started_at,
                    "completed_at": observation.completed_at,
                    "duration_seconds": observation.duration_seconds,
                }
            )
            _emit_runtime_progress(
                emit_progress,
                "tool_completed",
                iteration=iteration_label,
                node="executor",
                action_id=action.id,
                tool=action.tool,
                status=observation.status,
                error_code=observation.error_code,
                duration_seconds=observation.duration_seconds,
            )
            if observation.status != "ok":
                if iteration < max_iterations:
                    should_replan = True
                else:
                    status = "failed"
                break
        if should_replan:
            continue
        if status != "done":
            break
        if plan.final_answer:
            answer, final_answer_guardrail = _runtime_final_answer(
                goal,
                plan.final_answer,
            )

    result = {
        "trace_type": RUNTIME_TRACE_TYPE,
        "run_id": run_id,
        "status": status,
        "goal": goal,
        "started_at": started_at,
        "completed_at": _utc_timestamp(),
        "duration_seconds": _duration_since(started_timer),
        "iteration_count": str(iteration_count),
        "max_iterations": str(max_iterations),
        "iteration_budget_remaining": str(max(0, max_iterations - iteration_count)),
        "prompt_observation_compaction": _prompt_observation_compaction(),
        "approved_action_count": str(len(approved_action_id_list)),
        "approved_action_ids": approved_action_id_list,
        "events": events,
        "progress_events": progress_events,
        "plan": latest_plan,
        "plans": plans,
        "observations": [observation.to_dict() for observation in observations],
    }
    if answer:
        result["answer"] = answer
    if normalized_metadata:
        result["metadata"] = normalized_metadata
    if normalized_tags:
        result["tags"] = normalized_tags
    if final_answer_guardrail:
        result["final_answer_guardrail"] = final_answer_guardrail
    if pending_approval:
        result["pending_approval"] = pending_approval
    failed_observation = _last_failed_observation(observations)
    if status == "failed" and failed_observation is not None:
        result["error_code"] = failed_observation.error_code
        result["error"] = failed_observation.error
    _emit_runtime_progress(
        emit_progress,
        "run_completed",
        node="run",
        status=status,
        iteration_count=str(iteration_count),
        duration_seconds=result["duration_seconds"],
    )
    return result


def _runtime_user_prompt(
    goal: str,
    tools: Dict[str, RuntimeToolSpec],
    observations: List[AgentObservation],
) -> str:
    tool_payload = runtime_tool_metadata(tools)
    prompt = "Goal:\n" + goal + "\n\nAvailable tools:\n" + json.dumps(
        tool_payload,
        sort_keys=True,
    )
    if observations:
        prompt += "\n\nPrevious observations:\n" + json.dumps(
            [_planner_observation_payload(observation) for observation in observations],
            sort_keys=True,
        )
    return prompt


def _runtime_final_answer(goal: str, final_answer: str) -> tuple[str, Dict[str, str]]:
    goal_text = goal.lower()
    answer_text = final_answer.lower()
    if _is_runtime_identity_question(goal_text) and _looks_like_model_identity(answer_text):
        return _runtime_identity_answer(), _final_answer_guardrail(
            "runtime_identity_boundary"
        )
    if _is_runtime_deployment_question(goal_text) and _looks_like_model_deployment(answer_text):
        return _runtime_deployment_answer(), _final_answer_guardrail(
            "runtime_deployment_boundary"
        )
    return final_answer, {}


def _final_answer_guardrail(reason: str) -> Dict[str, str]:
    return {
        "applied": "true",
        "reason": reason,
        "original_answer_omitted": "true",
    }


def _is_runtime_identity_question(goal_text: str) -> bool:
    identity_markers = (
        "你是谁",
        "你是什么",
        "你叫",
        "who are you",
        "what are you",
    )
    return any(marker in goal_text for marker in identity_markers)


def _is_runtime_deployment_question(goal_text: str) -> bool:
    deployment_markers = (
        "部署在哪",
        "部署在哪里",
        "运行在哪",
        "运行在哪里",
        "在哪里运行",
        "where are you deployed",
        "where do you run",
        "where are you running",
    )
    return any(marker in goal_text for marker in deployment_markers)


def _looks_like_model_identity(answer_text: str) -> bool:
    provider_markers = (
        "qwen",
        "通义千问",
        "阿里云研发",
        "阿里巴巴",
        "chatgpt",
        "openai",
        "claude",
        "anthropic",
        "gemini",
    )
    return any(marker in answer_text for marker in provider_markers)


def _looks_like_model_deployment(answer_text: str) -> bool:
    provider_deployment_markers = (
        "阿里云服务器",
        "阿里云",
        "云服务器",
        "model provider",
        "provider server",
        "openai servers",
        "anthropic servers",
    )
    return any(marker in answer_text for marker in provider_deployment_markers)


def _runtime_identity_answer() -> str:
    return (
        "我是 self-correcting LangGraph agent runtime，一个运行在你当前 CLI 或服务"
        "进程里的非 coding Codex-style agent runtime。底层模型只是可替换的 "
        "OpenAI-compatible provider，我不会把 provider 的模型身份当成自己的身份。"
    )


def _runtime_deployment_answer() -> str:
    return (
        "我运行在你当前 CLI 或服务进程中；具体部署位置取决于你在哪台机器、容器或"
        "内部服务上启动这个 runtime。底层 LLM provider 可能在远端，但那不是这个"
        " agent runtime 自己的部署位置。"
    )


def _prompt_observation_compaction() -> Dict[str, Any]:
    return {
        "artifact_content_omitted": True,
        "max_string_chars": str(MAX_PLANNER_OBSERVATION_STRING_CHARS),
        "long_string_shape": "text_prefix/original_chars/truncated_chars",
    }


def _planner_observation_payload(observation: AgentObservation) -> Dict[str, Any]:
    payload = observation.to_dict()
    output = payload.get("output")
    if isinstance(output, dict) and str(output.get("artifact_id", "")).strip():
        payload["output"] = _artifact_prompt_metadata(output)
    else:
        payload["output"] = _compact_prompt_value(output)
    return payload


def _artifact_prompt_metadata(output: Dict[str, Any]) -> Dict[str, Any]:
    metadata = {
        key: output[key]
        for key in ["artifact_id", "title", "kind", "format", "tags", "bytes"]
        if key in output
    }
    metadata["content_omitted"] = True
    return metadata


def _compact_prompt_value(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) <= MAX_PLANNER_OBSERVATION_STRING_CHARS:
            return value
        return {
            "text_prefix": value[:MAX_PLANNER_OBSERVATION_STRING_CHARS],
            "original_chars": len(value),
            "truncated_chars": len(value) - MAX_PLANNER_OBSERVATION_STRING_CHARS,
        }
    if isinstance(value, dict):
        return {key: _compact_prompt_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_compact_prompt_value(item) for item in value]
    return value


def _action_dependency_event_metadata(
    depends_on: List[str],
    observations_by_action_id: Dict[str, AgentObservation],
) -> Dict[str, Any]:
    if not depends_on:
        return {}
    return {
        "depends_on": depends_on,
        "dependency_statuses": {
            action_id: observations_by_action_id[action_id].status
            for action_id in depends_on
            if action_id in observations_by_action_id
        },
    }


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timing_fields(started_at: str, started_timer: float) -> Dict[str, str]:
    return {
        "started_at": started_at,
        "completed_at": _utc_timestamp(),
        "duration_seconds": _duration_since(started_timer),
    }


def _duration_since(started_at: float) -> str:
    return f"{time.perf_counter() - started_at:.4f}"


def _last_failed_observation(
    observations: List[AgentObservation],
) -> AgentObservation | None:
    for observation in reversed(observations):
        if observation.status == "failed":
            return observation
    return None


def _emit_runtime_progress(
    event_sink: Optional[RuntimeEventSink],
    event_type: str,
    **fields: Any,
) -> None:
    if event_sink is None:
        return
    payload = {"type": event_type}
    payload.update(
        {
            key: value
            for key, value in fields.items()
            if not _is_empty_progress_field(value)
        }
    )
    event_sink(payload)


def _is_empty_progress_field(value: Any) -> bool:
    return value is None or value == ""
