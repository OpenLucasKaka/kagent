from __future__ import annotations

import pytest

from kagent.runtime.task_state import TaskStateMachine
from kagent.runtime.tools import default_runtime_tools, execute_runtime_tool


def test_task_state_machine_accepts_valid_lifecycle_transition():
    machine = TaskStateMachine()

    transition = machine.transition("pending", "start")

    assert transition == {
        "previous_state": "pending",
        "event": "start",
        "state": "in_progress",
    }


def test_task_state_machine_rejects_invalid_transition():
    machine = TaskStateMachine()

    with pytest.raises(ValueError, match="invalid task transition"):
        machine.transition("done", "start")


def test_task_transition_tool_returns_structured_transition():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "task_transition",
        {"state": "in_progress", "event": "block"},
        action_id="step-1",
    )

    assert observation.status == "ok"
    assert observation.output == {
        "previous_state": "in_progress",
        "event": "block",
        "state": "blocked",
    }
