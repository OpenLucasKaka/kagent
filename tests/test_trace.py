from self_correcting_langgraph_agent.core.state import AgentStatus
from self_correcting_langgraph_agent.core.trace import (
    copy_agent_state,
    record_execution_attempt,
    record_node_event,
)


def test_copy_agent_state_isolates_nested_trace_collections():
    state = {
        "plan": ["calculate 2 + 3"],
        "plan_validations": [{"step": "calculate 2 + 3"}],
        "step_results": ["5"],
        "tool_calls": [{"tool": "calculate_sum"}],
        "execution_attempts": [{"step": "calculate 2 + 3"}],
        "errors": ["old"],
        "events": [{"node": "planner"}],
        "reflection_notes": ["note"],
        "reflections": [{"reason": "answer was empty"}],
        "verification_results": [{"passed": "true"}],
        "fault_plan": {"calculate 2 + 3": ["wrong-answer"]},
        "fault_counters": {"calculate 2 + 3": 1},
    }

    copied = copy_agent_state(state)

    copied["plan"].append("subtract 10 - 4")
    copied["events"][0]["node"] = "executor"
    copied["fault_plan"]["calculate 2 + 3"].append("empty-answer")

    assert state["plan"] == ["calculate 2 + 3"]
    assert state["events"] == [{"node": "planner"}]
    assert state["fault_plan"] == {"calculate 2 + 3": ["wrong-answer"]}


def test_record_node_event_appends_serializable_runtime_snapshot():
    state = {
        "events": [],
        "status": AgentStatus.RUNNING,
        "retry_count": 1,
        "step_retry_count": 2,
    }

    record_node_event(state, "verifier")

    assert state["events"] == [
        {
            "node": "verifier",
            "status": "running",
            "retry_count": 1,
            "step_retry_count": 2,
        }
    ]


def test_record_execution_attempt_appends_retry_context():
    state = {"execution_attempts": [], "step_retry_count": 1}

    record_execution_attempt(
        state,
        step="calculate 2 + 3",
        tool="calculate_sum",
        output="5",
        fault="",
    )

    assert state["execution_attempts"] == [
        {
            "step": "calculate 2 + 3",
            "tool": "calculate_sum",
            "output": "5",
            "fault": "",
            "retry": "1",
        }
    ]
