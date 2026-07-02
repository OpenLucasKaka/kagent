from __future__ import annotations

import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from langgraph.graph import END, StateGraph

from self_correcting_langgraph_agent.core.normalization import (
    plan_goal as _plan_goal,
)
from self_correcting_langgraph_agent.core.planning import (
    normalize_fault_plan,
    plan_errors,
    validate_plan_steps,
)
from self_correcting_langgraph_agent.core.state import AgentConfig, AgentState, AgentStatus
from self_correcting_langgraph_agent.core.tools import execute_step, expected_answer
from self_correcting_langgraph_agent.core.trace import (
    copy_agent_state,
    record_execution_attempt,
    record_node_event,
)


def build_agent_graph(config: AgentConfig):
    graph = StateGraph(AgentState)
    graph.add_node("planner", _planner)
    graph.add_node("executor", _executor)
    graph.add_node("verifier", _verifier)
    graph.add_node("reflector", _reflector)
    graph.set_entry_point("planner")
    graph.add_conditional_edges(
        "planner",
        _route_after_planner,
        {
            "execute": "executor",
            "end": END,
        },
    )
    graph.add_edge("executor", "verifier")
    graph.add_conditional_edges(
        "verifier",
        _route_after_verifier,
        {
            "execute": "executor",
            "reflect": "reflector",
            "end": END,
        },
    )
    graph.add_edge("reflector", "executor")
    return graph.compile(name=f"self-correcting-agent-{config.max_steps}-{config.max_retries}")


def agent_topology() -> Dict[str, List[str]]:
    return {
        "nodes": ["planner", "executor", "verifier", "reflector"],
        "edges": [
            "planner -> executor",
            "executor -> verifier",
            "verifier -> reflector",
            "reflector -> executor",
            "verifier -> executor",
            "verifier -> END",
            "planner -> END",
        ],
    }


def run_agent(
    goal: str,
    *,
    config: Optional[AgentConfig] = None,
    fault_plan: Optional[Dict[str, List[str]]] = None,
) -> AgentState:
    active_config = config or AgentConfig()
    run_id = str(uuid4())
    started_at = _utc_timestamp()
    started_timer = time.perf_counter()
    initial_state: AgentState = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": "",
        "duration_seconds": "0.0000",
        "goal": goal,
        "config": asdict(active_config),
        "plan": [],
        "plan_validations": [],
        "current_step": 0,
        "answer": None,
        "step_results": [],
        "tool_calls": [],
        "execution_attempts": [],
        "verified": False,
        "retry_count": 0,
        "step_retry_count": 0,
        "status": AgentStatus.RUNNING,
        "errors": [],
        "events": [],
        "fault_plan": normalize_fault_plan(fault_plan or {}),
        "fault_counters": {},
        "reflection_notes": [],
        "reflections": [],
        "verification_results": [],
    }
    graph = build_agent_graph(active_config)
    final_state = graph.invoke(initial_state)
    final_state["run_id"] = run_id
    final_state["started_at"] = started_at
    final_state["completed_at"] = _utc_timestamp()
    final_state["duration_seconds"] = f"{time.perf_counter() - started_timer:.4f}"
    return final_state


def preview_plan(
    goal: str,
    *,
    config: Optional[AgentConfig] = None,
) -> Dict[str, Any]:
    active_config = config or AgentConfig()
    plan = _plan_goal(goal)
    plan_validations = validate_plan_steps(plan)
    errors = plan_errors(plan, active_config.max_steps)

    return {
        "status": "failed" if errors else "ready",
        "goal": goal,
        "plan": plan,
        "plan_validations": plan_validations,
        "errors": errors,
    }


def _planner(state: AgentState) -> AgentState:
    next_state = copy_agent_state(state)
    next_state["plan"] = _plan_goal(next_state["goal"])
    next_state["plan_validations"] = validate_plan_steps(next_state["plan"])
    next_state["current_step"] = 0
    errors = plan_errors(next_state["plan"], next_state["config"]["max_steps"])
    if errors:
        next_state["status"] = AgentStatus.FAILED
        next_state["errors"].extend(errors)
    else:
        next_state["status"] = AgentStatus.RUNNING
    record_node_event(next_state, "planner")
    return next_state


def _executor(state: AgentState) -> AgentState:
    next_state = copy_agent_state(state)
    step = _current_step(next_state)
    if step is None:
        next_state["status"] = AgentStatus.FAILED
        next_state["errors"].append("no executable step")
        record_node_event(next_state, "executor")
        return next_state

    fault = _consume_fault(next_state, step)
    if fault == "wrong-answer":
        next_state["answer"] = "6"
        record_execution_attempt(next_state, step, "", "6", fault)
    elif fault == "empty-answer":
        next_state["answer"] = ""
        record_execution_attempt(next_state, step, "", "", fault)
    elif fault == "tool-error":
        next_state["answer"] = "TOOL_ERROR"
        record_execution_attempt(next_state, step, "", "TOOL_ERROR", fault)
    else:
        execution = execute_step(step)
        if execution is None:
            next_state["answer"] = None
            next_state["errors"].append(f"unsupported step: {step}")
            record_execution_attempt(next_state, step, "", "None", "")
        else:
            next_state["answer"] = execution["output"]
            next_state["tool_calls"].append(execution)
            record_execution_attempt(
                next_state,
                step,
                execution["tool"],
                execution["output"],
                "",
            )

    record_node_event(next_state, "executor")
    return next_state


def _verifier(state: AgentState) -> AgentState:
    next_state = copy_agent_state(state)
    step = _current_step(next_state)
    expected = expected_answer(step)
    next_state["verified"] = bool(expected is not None and next_state.get("answer") == expected)
    next_state["verification_results"].append(
        {
            "step": step or "",
            "actual": str(next_state.get("answer")),
            "expected": str(expected),
            "passed": str(next_state["verified"]).lower(),
            "retry": str(next_state["step_retry_count"]),
        }
    )

    if next_state["verified"]:
        if next_state.get("answer") is not None:
            next_state["step_results"].append(next_state["answer"])
        next_state["current_step"] = next_state["current_step"] + 1
        next_state["step_retry_count"] = 0
        if next_state["current_step"] >= len(next_state.get("plan", [])):
            next_state["status"] = AgentStatus.DONE
        else:
            next_state["status"] = AgentStatus.RUNNING
    elif next_state["step_retry_count"] >= next_state["config"]["max_retries"]:
        next_state["status"] = AgentStatus.FAILED
        next_state["errors"].append("retry budget exhausted")
    else:
        next_state["status"] = AgentStatus.RUNNING

    record_node_event(next_state, "verifier")
    return next_state


def _reflector(state: AgentState) -> AgentState:
    next_state = copy_agent_state(state)
    next_state["retry_count"] = next_state["retry_count"] + 1
    next_state["step_retry_count"] = next_state["step_retry_count"] + 1
    step = _current_step(next_state)
    actual = str(next_state.get("answer"))
    reason = _reflection_reason(actual)
    next_state["reflection_notes"].append(_reflection_note(reason))
    next_state["reflections"].append(
        {
            "step": step or "",
            "actual": actual,
            "expected": str(expected_answer(step)),
            "retry": str(next_state["step_retry_count"]),
            "reason": reason,
        }
    )
    record_node_event(next_state, "reflector")
    return next_state


def _route_after_planner(state: AgentState) -> str:
    if state["status"] == AgentStatus.FAILED:
        return "end"
    return "execute"


def _route_after_verifier(state: AgentState) -> str:
    if state["status"] in {AgentStatus.DONE, AgentStatus.FAILED}:
        return "end"
    if state.get("verified"):
        return "execute"
    return "reflect"


def _current_step(state: AgentState) -> Optional[str]:
    plan = state.get("plan", [])
    current_step = state.get("current_step", 0)
    if current_step < 0 or current_step >= len(plan):
        return None
    return plan[current_step]


def _consume_fault(state: AgentState, step: str) -> Optional[str]:
    fault_plan = state.get("fault_plan", {})
    faults = fault_plan.get(step, [])
    counters = state.setdefault("fault_counters", {})
    index = counters.get(step, 0)
    counters[step] = index + 1
    if index >= len(faults):
        return None
    return faults[index]


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _reflection_reason(actual: str) -> str:
    if actual == "":
        return "answer was empty"
    if actual == "TOOL_ERROR":
        return "tool execution failed"
    return "answer did not match verifier expectation"


def _reflection_note(reason: str) -> str:
    if reason == "answer was empty":
        return "executor returned an empty answer; retry the same planned step"
    if reason == "tool execution failed":
        return "tool execution failed; retry the same planned step"
    return "executor returned an unverifiable answer; retry with stricter arithmetic"
