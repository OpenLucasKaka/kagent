from __future__ import annotations

from self_correcting_langgraph_agent.core.state import AgentState


def record_node_event(state: AgentState, node: str) -> None:
    state["events"].append(
        {
            "node": node,
            "status": state["status"].value,
            "retry_count": state["retry_count"],
            "step_retry_count": state.get("step_retry_count", 0),
        }
    )


def record_execution_attempt(
    state: AgentState,
    step: str,
    tool: str,
    output: str,
    fault: str,
) -> None:
    state["execution_attempts"].append(
        {
            "step": step,
            "tool": tool,
            "output": output,
            "fault": fault,
            "retry": str(state["step_retry_count"]),
        }
    )


def copy_agent_state(state: AgentState) -> AgentState:
    copied = dict(state)
    copied["plan"] = list(state.get("plan", []))
    copied["plan_validations"] = [
        dict(item) for item in state.get("plan_validations", [])
    ]
    copied["step_results"] = list(state.get("step_results", []))
    copied["tool_calls"] = [dict(item) for item in state.get("tool_calls", [])]
    copied["execution_attempts"] = [
        dict(item) for item in state.get("execution_attempts", [])
    ]
    copied["errors"] = list(state.get("errors", []))
    copied["events"] = [dict(item) for item in state.get("events", [])]
    copied["reflection_notes"] = list(state.get("reflection_notes", []))
    copied["reflections"] = [dict(item) for item in state.get("reflections", [])]
    copied["verification_results"] = [
        dict(item) for item in state.get("verification_results", [])
    ]
    copied["fault_plan"] = {
        key: list(value) for key, value in state.get("fault_plan", {}).items()
    }
    copied["fault_counters"] = dict(state.get("fault_counters", {}))
    return copied
