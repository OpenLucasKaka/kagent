from kagent.runtime.action_graph import (
    execute_action_graph_node,
    mark_action_graph_node,
    prepare_action_graph_node,
)
from kagent.runtime.checkpoint_state import (
    RuntimeGraphContext,
    RuntimeGraphState,
    checkpoint_plan_projection,
    checkpoint_safe_value,
)


def test_single_action_graph_nodes_live_outside_runtime_agent_module():
    assert prepare_action_graph_node.__module__ == "kagent.runtime.action_graph"
    assert mark_action_graph_node.__module__ == "kagent.runtime.action_graph"
    assert execute_action_graph_node.__module__ == "kagent.runtime.action_graph"


def test_checkpoint_state_module_owns_durable_graph_contracts():
    assert RuntimeGraphState.__module__ == "kagent.runtime.checkpoint_state"
    assert RuntimeGraphContext.__module__ == "kagent.runtime.checkpoint_state"
    assert checkpoint_safe_value({"value": object()}) == {
        "value": "[unsupported object]"
    }
    projected, changed = checkpoint_plan_projection(
        {"input": {"api_key": "secret-value"}}
    )
    assert projected == {"input": {"api_key": "[REDACTED]"}}
    assert changed is True
