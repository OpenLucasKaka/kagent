from self_correcting_langgraph_agent.core.planning import (
    normalize_fault_plan,
    plan_errors,
    validate_plan_steps,
)


def test_validate_plan_steps_reports_tool_support():
    validations = validate_plan_steps(["calculate 2 + 3", "search the web"])

    assert validations == [
        {
            "step": "calculate 2 + 3",
            "supported": "true",
            "tool": "calculate_sum",
        },
        {
            "step": "search the web",
            "supported": "false",
            "tool": "",
        },
    ]


def test_plan_errors_prioritizes_empty_plan_and_limits():
    assert plan_errors([], max_steps=3) == ["empty plan"]
    assert plan_errors(["calculate 1 + 1", "calculate 2 + 2"], max_steps=1) == [
        "planned steps exceed max_steps"
    ]
    assert plan_errors(["search the web"], max_steps=3) == [
        "unsupported planned step: search the web"
    ]


def test_normalize_fault_plan_validates_fault_names_and_normalizes_steps():
    assert normalize_fault_plan({"  Calculate 2 + 3  ": ["wrong-answer"]}) == {
        "calculate 2 + 3": ["wrong-answer"]
    }
