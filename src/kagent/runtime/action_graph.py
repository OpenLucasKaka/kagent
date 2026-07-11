from __future__ import annotations

import copy
import json
import time
from typing import Any, Dict, List
from uuid import uuid4

from kagent.runtime.checkpoint_state import (
    RuntimeGraphContext,
    RuntimeGraphState,
    append_graph_phase,
    checkpoint_plan_projection,
    checkpoint_safe_value,
    timing_fields,
    utc_timestamp,
)
from kagent.runtime.policy import RuntimePolicy
from kagent.runtime.presentation import project_runtime_presentation
from kagent.runtime.tools import default_runtime_tools, execute_runtime_tool
from kagent.runtime.types import AgentObservation, parse_agent_plan


def route_after_planner(state: RuntimeGraphState) -> str:
    planner = state.get("initial_planner")
    if not isinstance(planner, dict) or planner.get("status") != "ok":
        return "runtime_loop"
    plan = planner.get("plan")
    actions = plan.get("actions") if isinstance(plan, dict) else None
    return (
        "prepare_action"
        if isinstance(actions, list) and len(actions) == 1
        else "runtime_loop"
    )


def route_after_prepare_action(state: RuntimeGraphState) -> str:
    prepared = state.get("initial_action_prepared")
    if isinstance(prepared, dict) and prepared.get("status") == "prepared":
        return "mark_action_executing"
    return "runtime_loop"


def route_after_mark_action(state: RuntimeGraphState) -> str:
    phase = state.get("initial_action_phase")
    if (
        not state.get("initial_action_outcome")
        and isinstance(phase, dict)
        and phase.get("status") == "executing"
    ):
        return "execute_action"
    return "runtime_loop"


def _planner_plan_for_action(
    state: RuntimeGraphState,
    context: RuntimeGraphContext,
) -> tuple[Dict[str, Any] | None, str]:
    planner = state.get("initial_planner")
    if not isinstance(planner, dict) or planner.get("status") != "ok":
        return None, "planner checkpoint is missing plan state"
    run_id = str(state.get("run_id", ""))
    cache_entry = (context.get("planner_plan_cache") or {}).get(run_id)
    if (
        isinstance(cache_entry, dict)
        and cache_entry.get("token") == planner.get("plan_cache_token")
        and isinstance(cache_entry.get("plan"), dict)
    ):
        return copy.deepcopy(cache_entry["plan"]), ""
    plan = planner.get("plan")
    if planner.get("plan_redacted"):
        return None, (
            "planner checkpoint contains sensitive tool input; "
            "the original in-memory plan is unavailable"
        )
    if not isinstance(plan, dict):
        return None, "planner checkpoint is missing plan state"
    return copy.deepcopy(plan), ""


def _ensure_runtime_tools(context: RuntimeGraphContext) -> None:
    if "tools" in context:
        return
    context["tools"] = default_runtime_tools(
        runtime_workspace_dir=context.get("runtime_workspace_dir", ""),
        redis_url=context.get("redis_url", ""),
        milvus_url=context.get("milvus_url", ""),
        embedding_base_url=context.get("embedding_base_url", ""),
        embedding_api_key=context.get("embedding_api_key", ""),
        embedding_model=context.get("embedding_model", ""),
        embedding_timeout_seconds=context.get("embedding_timeout_seconds", 30.0),
        embedding_max_retries=context.get("embedding_max_retries", 2),
        embedding_retry_backoff_seconds=context.get(
            "embedding_retry_backoff_seconds",
            0.25,
        ),
        external_backend_timeout_seconds=context.get(
            "external_backend_timeout_seconds",
            2.0,
        ),
    )


def prepare_action_graph_node(
    state: RuntimeGraphState,
    runtime: Any,
) -> RuntimeGraphState:
    started_at = utc_timestamp()
    started_timer = time.perf_counter()
    context: RuntimeGraphContext = runtime.context or {}
    _ensure_runtime_tools(context)
    if context.get("hooks"):
        return {
            "initial_action_prepared": {"status": "legacy"},
            "graph_phases": append_graph_phase(
                state.get("graph_phases"),
                "prepare_action",
                started_at,
                started_timer,
            ),
        }
    plan_payload, plan_error = _planner_plan_for_action(state, context)
    if plan_payload is None:
        return {
            "initial_action_outcome": _failed_initial_action_outcome(
                action_id="",
                tool="planner",
                error_code="planner_checkpoint_sensitive_input",
                error=plan_error,
                started_at=started_at,
                started_timer=started_timer,
            ),
            "initial_action_prepared": {"status": "failed"},
            "graph_phases": append_graph_phase(
                state.get("graph_phases"),
                "prepare_action",
                started_at,
                started_timer,
            ),
        }
    plan = parse_agent_plan(json.dumps(plan_payload, ensure_ascii=False))
    if len(plan.actions) != 1 or plan.actions[0].depends_on:
        return {
            "initial_action_prepared": {"status": "legacy"},
            "graph_phases": append_graph_phase(
                state.get("graph_phases"),
                "prepare_action",
                started_at,
                started_timer,
            ),
        }
    action = plan.actions[0]
    cancellation_token = context.get("cancellation_token")
    if cancellation_token is not None and cancellation_token.is_cancelled():
        return {
            "initial_action_prepared": {"status": "legacy"},
            "graph_phases": append_graph_phase(
                state.get("graph_phases"),
                "prepare_action",
                started_at,
                started_timer,
            ),
        }
    steering_buffer = context.get("steering_buffer")
    if steering_buffer is not None and steering_buffer.pending():
        return {
            "initial_action_prepared": {"status": "legacy"},
            "graph_phases": append_graph_phase(
                state.get("graph_phases"),
                "prepare_action",
                started_at,
                started_timer,
            ),
        }
    resolved_input = copy.deepcopy(action.input)
    active_policy = context.get("policy") or RuntimePolicy()
    policy_started_at = utc_timestamp()
    policy_timer = time.perf_counter()
    decision = active_policy.authorize(action.tool, resolved_input)
    if decision.status != "allowed":
        return {
            "initial_action_prepared": {"status": "legacy"},
            "graph_phases": append_graph_phase(
                state.get("graph_phases"),
                "prepare_action",
                started_at,
                started_timer,
            ),
        }
    policy_event = {
        "node": "policy",
        "action_id": action.id,
        "tool": action.tool,
        "status": "allowed",
        "reason": decision.reason,
        "iteration": "1",
        **timing_fields(policy_started_at, policy_timer),
    }
    progress_events, sink_failures = _append_checkpoint_progress(
        state,
        context,
        {
            "type": "policy_completed",
            "iteration": "1",
            "node": "policy",
            "action_id": action.id,
            "tool": action.tool,
            "status": "allowed",
            "reason": decision.reason,
            "duration_seconds": policy_event["duration_seconds"],
        },
    )
    projected_input, input_redacted = checkpoint_plan_projection(resolved_input)
    projected_action, action_redacted = checkpoint_plan_projection(action.to_dict())
    cache_token = str(uuid4())
    prepared_cache = context.setdefault("prepared_action_cache", {})
    prepared_cache[str(state.get("run_id", ""))] = {
        "token": cache_token,
        "action": action.to_dict(),
        "input": resolved_input,
    }
    return {
        "initial_events": [*(state.get("initial_events") or []), policy_event],
        "initial_progress_events": progress_events,
        "initial_progress_event_sink_failure_count": sink_failures,
        "initial_action_prepared": {
            "status": "prepared",
            "action": projected_action,
            "input": projected_input,
            "input_redacted": input_redacted or action_redacted,
            "cache_token": cache_token,
        },
        "graph_phases": append_graph_phase(
            state.get("graph_phases"),
            "prepare_action",
            started_at,
            started_timer,
        ),
    }


def mark_action_graph_node(
    state: RuntimeGraphState,
    runtime: Any,
) -> RuntimeGraphState:
    started_at = utc_timestamp()
    started_timer = time.perf_counter()
    context: RuntimeGraphContext = runtime.context or {}
    run_id = str(state.get("run_id", ""))
    prepared = state.get("initial_action_prepared") or {}
    cancellation_token = context.get("cancellation_token")
    steering_buffer = context.get("steering_buffer")
    if (
        cancellation_token is not None and cancellation_token.is_cancelled()
    ) or (steering_buffer is not None and steering_buffer.pending()):
        prepared_cache = context.get("prepared_action_cache")
        if isinstance(prepared_cache, dict):
            prepared_cache.pop(run_id, None)
        return {
            "initial_action_phase": {"status": "legacy"},
            "graph_phases": append_graph_phase(
                state.get("graph_phases"),
                "mark_action_executing",
                started_at,
                started_timer,
            ),
        }
    cache_entry = (context.get("prepared_action_cache") or {}).get(run_id)
    if not (
        isinstance(cache_entry, dict)
        and cache_entry.get("token") == prepared.get("cache_token")
        and isinstance(cache_entry.get("action"), dict)
        and isinstance(cache_entry.get("input"), dict)
    ):
        outcome = _failed_initial_action_outcome(
            action_id=str((prepared.get("action") or {}).get("id", "")),
            tool=str((prepared.get("action") or {}).get("tool", "")),
            error_code="planner_checkpoint_sensitive_input",
            error="prepared action input is unavailable",
            started_at=started_at,
            started_timer=started_timer,
        )
        observation = outcome["observation"]
        checkpoint_event = {
            "node": "checkpoint",
            "action_id": observation["action_id"],
            "tool": observation["tool"],
            "status": "failed",
            "error_code": observation["error_code"],
            "started_at": observation["started_at"],
            "completed_at": observation["completed_at"],
            "duration_seconds": observation["duration_seconds"],
        }
        return {
            "initial_action_outcome": outcome,
            "initial_events": [
                *(state.get("initial_events") or []),
                checkpoint_event,
            ],
            "graph_phases": append_graph_phase(
                state.get("graph_phases"),
                "mark_action_executing",
                started_at,
                started_timer,
            ),
        }
    execution_token = str(uuid4())
    executing_cache = context.setdefault("executing_action_cache", {})
    executing_cache[run_id] = {
        "token": execution_token,
        "action": copy.deepcopy(cache_entry["action"]),
        "input": copy.deepcopy(cache_entry["input"]),
    }
    context["prepared_action_cache"].pop(run_id, None)
    return {
        "initial_action_phase": {
            "status": "executing",
            "action_id": str(cache_entry["action"].get("id", "")),
            "tool": str(cache_entry["action"].get("tool", "")),
            "execution_token": execution_token,
        },
        "graph_phases": append_graph_phase(
            state.get("graph_phases"),
            "mark_action_executing",
            started_at,
            started_timer,
        ),
    }


def execute_action_graph_node(
    state: RuntimeGraphState,
    runtime: Any,
) -> RuntimeGraphState:
    started_at = utc_timestamp()
    started_timer = time.perf_counter()
    context: RuntimeGraphContext = runtime.context or {}
    run_id = str(state.get("run_id", ""))
    phase = state.get("initial_action_phase") or {}
    cache_entry = (context.get("executing_action_cache") or {}).get(run_id)
    if not (
        isinstance(cache_entry, dict)
        and cache_entry.get("token") == phase.get("execution_token")
        and isinstance(cache_entry.get("action"), dict)
        and isinstance(cache_entry.get("input"), dict)
    ):
        outcome = _failed_initial_action_outcome(
            action_id=str(phase.get("action_id", "")),
            tool=str(phase.get("tool", "")),
            error_code="approval_execution_interrupted",
            error=(
                "action execution was interrupted; side-effect state is uncertain"
            ),
            started_at=started_at,
            started_timer=started_timer,
        )
        observation = outcome["observation"]
        executor_event = {
            "node": "executor",
            "action_id": observation["action_id"],
            "tool": observation["tool"],
            "status": "failed",
            "iteration": "1",
            "error_code": observation["error_code"],
            "started_at": observation["started_at"],
            "completed_at": observation["completed_at"],
            "duration_seconds": observation["duration_seconds"],
        }
        progress_events, sink_failures = _append_checkpoint_progress(
            state,
            context,
            {
                "type": "tool_completed",
                "iteration": "1",
                "node": "executor",
                "action_id": observation["action_id"],
                "tool": observation["tool"],
                "status": "failed",
                "error_code": observation["error_code"],
                "duration_seconds": observation["duration_seconds"],
            },
        )
        return {
            "initial_action_outcome": outcome,
            "initial_events": [*(state.get("initial_events") or []), executor_event],
            "initial_progress_events": progress_events,
            "initial_progress_event_sink_failure_count": sink_failures,
            "graph_phases": append_graph_phase(
                state.get("graph_phases"),
                "execute_action",
                started_at,
                started_timer,
            ),
        }
    cancellation_token = context.get("cancellation_token")
    steering_buffer = context.get("steering_buffer")
    if (
        cancellation_token is not None and cancellation_token.is_cancelled()
    ) or (steering_buffer is not None and steering_buffer.pending()):
        context["executing_action_cache"].pop(run_id, None)
        return {
            "initial_action_phase": {"status": "legacy"},
            "graph_phases": append_graph_phase(
                state.get("graph_phases"),
                "execute_action",
                started_at,
                started_timer,
            ),
        }
    context["executing_action_cache"].pop(run_id, None)
    planner_cache = context.get("planner_plan_cache")
    if isinstance(planner_cache, dict):
        planner_cache.pop(run_id, None)
    action = cache_entry["action"]
    action_id = str(action.get("id", ""))
    tool_name = str(action.get("tool", ""))
    progress_events, sink_failures = _append_checkpoint_progress(
        state,
        context,
        {
            "type": "tool_started",
            "iteration": "1",
            "node": "executor",
            "action_id": action_id,
            "tool": tool_name,
            "status": "started",
        },
    )
    observation = execute_runtime_tool(
        context.get("tools") or {},
        tool_name,
        cache_entry["input"],
        action_id=action_id,
    )
    executor_event = {
        "node": "executor",
        "action_id": action_id,
        "tool": tool_name,
        "status": observation.status,
        "iteration": "1",
        "started_at": observation.started_at,
        "completed_at": observation.completed_at,
        "duration_seconds": observation.duration_seconds,
    }
    presentation = project_runtime_presentation(
        tool_name,
        observation.status,
        observation.output,
    )
    progress_events, sink_failures = _append_checkpoint_progress_values(
        progress_events,
        sink_failures,
        state,
        context,
        {
            "type": "tool_completed",
            "iteration": "1",
            "node": "executor",
            "action_id": action_id,
            "tool": tool_name,
            "status": observation.status,
            "error_code": observation.error_code,
            "duration_seconds": observation.duration_seconds,
            "presentation": presentation or None,
        },
    )
    return {
        "initial_events": [*(state.get("initial_events") or []), executor_event],
        "initial_progress_events": progress_events,
        "initial_progress_event_sink_failure_count": sink_failures,
        "initial_action_outcome": {
            "status": observation.status,
            "observation": checkpoint_safe_value(observation.to_dict()),
            "should_replan": (
                observation.status != "ok" and state.get("max_iterations", 1) > 1
            ),
        },
        "graph_phases": append_graph_phase(
            state.get("graph_phases"),
            "execute_action",
            started_at,
            started_timer,
        ),
    }


def _failed_initial_action_outcome(
    *,
    action_id: str,
    tool: str,
    error_code: str,
    error: str,
    started_at: str,
    started_timer: float,
) -> Dict[str, Any]:
    timing = timing_fields(started_at, started_timer)
    return {
        "status": "failed",
        "observation": AgentObservation(
            action_id=action_id,
            tool=tool,
            status="failed",
            output={},
            error_code=error_code,
            error=error,
            started_at=started_at,
            completed_at=timing["completed_at"],
            duration_seconds=timing["duration_seconds"],
        ).to_dict(),
        "should_replan": False,
    }


def _append_checkpoint_progress(
    state: RuntimeGraphState,
    context: RuntimeGraphContext,
    event: Dict[str, Any],
) -> tuple[List[Dict[str, Any]], int]:
    return _append_checkpoint_progress_values(
        list(state.get("initial_progress_events") or []),
        state.get("initial_progress_event_sink_failure_count", 0),
        state,
        context,
        event,
    )


def _append_checkpoint_progress_values(
    progress_events: List[Dict[str, Any]],
    sink_failures: int,
    state: RuntimeGraphState,
    context: RuntimeGraphContext,
    event: Dict[str, Any],
) -> tuple[List[Dict[str, Any]], int]:
    event_with_run_id = {"run_id": str(state.get("run_id", "")), **event}
    progress_events.append(checkpoint_safe_value(event_with_run_id))
    event_sink = context.get("event_sink")
    if event_sink is not None:
        try:
            event_sink(event_with_run_id)
        except Exception:
            sink_failures += 1
    return progress_events, sink_failures
