from uuid import UUID

import pytest

from self_correcting_langgraph_agent.core.agent import (
    AgentConfig,
    AgentStatus,
    build_agent_graph,
    preview_plan,
    run_agent,
)


def test_graph_reaches_done_for_a_supported_goal():
    result = run_agent(
        "calculate 2 + 3",
        config=AgentConfig(max_steps=4, max_retries=1),
    )

    assert result["status"] == AgentStatus.DONE
    assert result["answer"] == "5"
    assert result["verified"] is True
    assert result["verification_results"] == [
        {
            "step": "calculate 2 + 3",
            "actual": "5",
            "expected": "5",
            "passed": "true",
            "retry": "0",
        }
    ]
    assert result["current_step"] == 1
    assert [event["node"] for event in result["events"]] == [
        "planner",
        "executor",
        "verifier",
    ]


def test_run_agent_records_run_metadata_for_observability():
    result = run_agent(
        "calculate 2 + 3",
        config=AgentConfig(max_steps=4, max_retries=1),
    )

    UUID(result["run_id"])
    assert result["started_at"].endswith("Z")
    assert result["completed_at"].endswith("Z")
    assert float(result["duration_seconds"]) >= 0


def test_agent_config_can_be_loaded_from_environment_mapping():
    config = AgentConfig.from_env(
        {
            "SELF_CORRECTING_MAX_STEPS": "3",
            "SELF_CORRECTING_MAX_RETRIES": "4",
        }
    )

    assert config == AgentConfig(max_steps=3, max_retries=4)


def test_agent_config_reports_invalid_environment_values():
    with pytest.raises(ValueError, match="SELF_CORRECTING_MAX_STEPS must be an integer"):
        AgentConfig.from_env({"SELF_CORRECTING_MAX_STEPS": "many"})


def test_preview_plan_reports_supported_steps_without_execution():
    preview = preview_plan(
        "calculate 2 + 3 then subtract 10 - 4",
        config=AgentConfig(max_steps=4, max_retries=1),
    )

    assert preview == {
        "status": "ready",
        "goal": "calculate 2 + 3 then subtract 10 - 4",
        "plan": ["calculate 2 + 3", "subtract 10 - 4"],
        "plan_validations": [
            {
                "step": "calculate 2 + 3",
                "supported": "true",
                "tool": "calculate_sum",
            },
            {
                "step": "subtract 10 - 4",
                "supported": "true",
                "tool": "subtract_numbers",
            },
        ],
        "errors": [],
    }


def test_preview_plan_reports_unsupported_steps_without_execution():
    preview = preview_plan(
        "calculate 2 + 3 then search the web",
        config=AgentConfig(max_steps=4, max_retries=1),
    )

    assert preview["status"] == "failed"
    assert preview["errors"] == ["unsupported planned step: search the web"]
    assert preview["plan_validations"][-1] == {
        "step": "search the web",
        "supported": "false",
        "tool": "",
    }


def test_graph_self_corrects_after_a_bad_first_execution():
    result = run_agent(
        "calculate 2 + 3",
        config=AgentConfig(max_steps=4, max_retries=2),
        fault_plan={"calculate 2 + 3": ["wrong-answer"]},
    )

    assert result["status"] == AgentStatus.DONE
    assert result["answer"] == "5"
    assert result["retry_count"] == 1
    assert [event["node"] for event in result["events"]] == [
        "planner",
        "executor",
        "verifier",
        "reflector",
        "executor",
        "verifier",
    ]
    assert result["reflection_notes"] == [
        "executor returned an unverifiable answer; retry with stricter arithmetic"
    ]
    assert result["reflections"] == [
        {
            "step": "calculate 2 + 3",
            "actual": "6",
            "expected": "5",
            "retry": "1",
            "reason": "answer did not match verifier expectation",
        }
    ]
    assert result["verification_results"] == [
        {
            "step": "calculate 2 + 3",
            "actual": "6",
            "expected": "5",
            "passed": "false",
            "retry": "0",
        },
        {
            "step": "calculate 2 + 3",
            "actual": "5",
            "expected": "5",
            "passed": "true",
            "retry": "1",
        },
    ]


def test_run_agent_normalizes_fault_plan_steps():
    result = run_agent(
        "calculate 2 + 3",
        config=AgentConfig(max_steps=4, max_retries=2),
        fault_plan={"  Calculate   2 + 3  ": ["wrong-answer"]},
    )

    assert result["status"] == AgentStatus.DONE
    assert result["retry_count"] == 1
    assert result["reflections"][-1]["actual"] == "6"


def test_run_agent_rejects_unknown_fault_names():
    with pytest.raises(ValueError, match="unsupported fault: typo"):
        run_agent(
            "calculate 2 + 3",
            config=AgentConfig(max_steps=4, max_retries=2),
            fault_plan={"calculate 2 + 3": ["typo"]},
        )


def test_graph_self_corrects_after_an_empty_first_execution():
    result = run_agent(
        "uppercase text in 'agent loop'",
        config=AgentConfig(max_steps=4, max_retries=2),
        fault_plan={"uppercase text in 'agent loop'": ["empty-answer"]},
    )

    assert result["status"] == AgentStatus.DONE
    assert result["answer"] == "AGENT LOOP"
    assert result["retry_count"] == 1
    assert result["reflection_notes"] == [
        "executor returned an empty answer; retry the same planned step"
    ]
    assert result["reflections"] == [
        {
            "step": "uppercase text in 'agent loop'",
            "actual": "",
            "expected": "AGENT LOOP",
            "retry": "1",
            "reason": "answer was empty",
        }
    ]
    assert result["verification_results"] == [
        {
            "step": "uppercase text in 'agent loop'",
            "actual": "",
            "expected": "AGENT LOOP",
            "passed": "false",
            "retry": "0",
        },
        {
            "step": "uppercase text in 'agent loop'",
            "actual": "AGENT LOOP",
            "expected": "AGENT LOOP",
            "passed": "true",
            "retry": "1",
        },
    ]
    assert result["execution_attempts"] == [
        {
            "step": "uppercase text in 'agent loop'",
            "tool": "",
            "output": "",
            "fault": "empty-answer",
            "retry": "0",
        },
        {
            "step": "uppercase text in 'agent loop'",
            "tool": "uppercase_text",
            "output": "AGENT LOOP",
            "fault": "",
            "retry": "1",
        },
    ]


def test_graph_self_corrects_after_a_transient_tool_error():
    result = run_agent(
        "reverse text in 'Agent Loop'",
        config=AgentConfig(max_steps=4, max_retries=2),
        fault_plan={"reverse text in 'Agent Loop'": ["tool-error"]},
    )

    assert result["status"] == AgentStatus.DONE
    assert result["answer"] == "pooL tnegA"
    assert result["retry_count"] == 1
    assert result["errors"] == []
    assert result["reflection_notes"] == [
        "tool execution failed; retry the same planned step"
    ]
    assert result["reflections"] == [
        {
            "step": "reverse text in 'Agent Loop'",
            "actual": "TOOL_ERROR",
            "expected": "pooL tnegA",
            "retry": "1",
            "reason": "tool execution failed",
        }
    ]
    assert result["execution_attempts"] == [
        {
            "step": "reverse text in 'Agent Loop'",
            "tool": "",
            "output": "TOOL_ERROR",
            "fault": "tool-error",
            "retry": "0",
        },
        {
            "step": "reverse text in 'Agent Loop'",
            "tool": "reverse_text",
            "output": "pooL tnegA",
            "fault": "",
            "retry": "1",
        },
    ]


def test_graph_stops_when_retry_budget_is_exhausted():
    result = run_agent(
        "calculate 2 + 3",
        config=AgentConfig(max_steps=5, max_retries=1),
        fault_plan={"calculate 2 + 3": ["wrong-answer", "wrong-answer"]},
    )

    assert result["status"] == AgentStatus.FAILED
    assert result["verified"] is False
    assert result["retry_count"] == 1
    assert result["errors"][-1] == "retry budget exhausted"


def test_build_agent_graph_returns_a_compiled_langgraph():
    graph = build_agent_graph(AgentConfig())

    assert callable(getattr(graph, "invoke"))


def test_graph_completes_multiple_planned_steps():
    result = run_agent(
        "calculate 2 + 3 then calculate 4 + 5",
        config=AgentConfig(max_steps=4, max_retries=1),
    )

    assert result["status"] == AgentStatus.DONE
    assert result["current_step"] == 2
    assert result["answer"] == "9"
    assert result["step_results"] == ["5", "9"]
    assert result["plan_validations"] == [
        {
            "step": "calculate 2 + 3",
            "supported": "true",
            "tool": "calculate_sum",
        },
        {
            "step": "calculate 4 + 5",
            "supported": "true",
            "tool": "calculate_sum",
        },
    ]
    assert [event["node"] for event in result["events"]] == [
        "planner",
        "executor",
        "verifier",
        "executor",
        "verifier",
    ]


def test_graph_gives_each_planned_step_its_own_retry_budget():
    result = run_agent(
        "calculate 2 + 3 then uppercase text in 'agent loop'",
        config=AgentConfig(max_steps=4, max_retries=1),
        fault_plan={
            "calculate 2 + 3": ["wrong-answer"],
            "uppercase text in 'agent loop'": ["empty-answer"],
        },
    )

    assert result["status"] == AgentStatus.DONE
    assert result["retry_count"] == 2
    assert result["step_retry_count"] == 0
    assert result["step_results"] == ["5", "AGENT LOOP"]
    assert [item["retry"] for item in result["verification_results"]] == [
        "0",
        "1",
        "0",
        "1",
    ]


def test_graph_fails_fast_when_planned_steps_exceed_budget():
    result = run_agent(
        "calculate 1 + 1 then calculate 2 + 2",
        config=AgentConfig(max_steps=1, max_retries=1),
    )

    assert result["status"] == AgentStatus.FAILED
    assert result["errors"] == ["planned steps exceed max_steps"]


def test_graph_fails_fast_when_goal_has_no_steps():
    result = run_agent(
        "   ",
        config=AgentConfig(max_steps=4, max_retries=1),
    )

    assert result["status"] == AgentStatus.FAILED
    assert result["errors"] == ["empty plan"]
    assert [event["node"] for event in result["events"]] == ["planner"]


def test_graph_fails_fast_when_planner_finds_unsupported_steps():
    result = run_agent(
        "calculate 1 + 1 then search the web",
        config=AgentConfig(max_steps=4, max_retries=2),
    )

    assert result["status"] == AgentStatus.FAILED
    assert result["errors"] == ["unsupported planned step: search the web"]
    assert result["retry_count"] == 0
    assert result["plan_validations"] == [
        {
            "step": "calculate 1 + 1",
            "supported": "true",
            "tool": "calculate_sum",
        },
        {
            "step": "search the web",
            "supported": "false",
            "tool": "",
        },
    ]
    assert [event["node"] for event in result["events"]] == ["planner"]


def test_graph_uses_text_tool_for_word_count_goals():
    result = run_agent(
        "count words in 'hello brave new world'",
        config=AgentConfig(max_steps=3, max_retries=1),
    )

    assert result["status"] == AgentStatus.DONE
    assert result["answer"] == "4"
    assert result["step_results"] == ["4"]
    assert result["tool_calls"] == [
        {
            "tool": "count_words",
            "input": "hello brave new world",
            "output": "4",
        }
    ]


def test_graph_counts_empty_text_as_zero_words():
    result = run_agent(
        "count words in ''",
        config=AgentConfig(max_steps=3, max_retries=1),
    )

    assert result["status"] == AgentStatus.DONE
    assert result["answer"] == "0"
    assert result["step_results"] == ["0"]


def test_graph_uses_text_tool_for_uppercase_goals():
    result = run_agent(
        "uppercase text in 'agent loop'",
        config=AgentConfig(max_steps=3, max_retries=1),
    )

    assert result["status"] == AgentStatus.DONE
    assert result["answer"] == "AGENT LOOP"
    assert result["step_results"] == ["AGENT LOOP"]
    assert result["tool_calls"] == [
        {
            "tool": "uppercase_text",
            "input": "agent loop",
            "output": "AGENT LOOP",
        }
    ]


def test_graph_uppercases_empty_text():
    result = run_agent(
        "uppercase text in ''",
        config=AgentConfig(max_steps=3, max_retries=1),
    )

    assert result["status"] == AgentStatus.DONE
    assert result["answer"] == ""
    assert result["step_results"] == [""]


def test_graph_preserves_quoted_text_in_tool_audit():
    result = run_agent(
        "  Uppercase   Text in 'Agent Loop'  ",
        config=AgentConfig(max_steps=3, max_retries=1),
    )

    assert result["status"] == AgentStatus.DONE
    assert result["answer"] == "AGENT LOOP"
    assert result["plan"] == ["uppercase text in 'Agent Loop'"]
    assert result["tool_calls"] == [
        {
            "tool": "uppercase_text",
            "input": "Agent Loop",
            "output": "AGENT LOOP",
        }
    ]


def test_graph_uses_multiplication_tool():
    result = run_agent(
        "multiply 6 * 7",
        config=AgentConfig(max_steps=3, max_retries=1),
    )

    assert result["status"] == AgentStatus.DONE
    assert result["answer"] == "42"
    assert result["tool_calls"] == [
        {
            "tool": "multiply_numbers",
            "input": "multiply 6 * 7",
            "output": "42",
        }
    ]


def test_graph_uses_reverse_text_tool_with_original_case():
    result = run_agent(
        "Reverse Text in 'Agent Loop'",
        config=AgentConfig(max_steps=3, max_retries=1),
    )

    assert result["status"] == AgentStatus.DONE
    assert result["answer"] == "pooL tnegA"
    assert result["tool_calls"] == [
        {
            "tool": "reverse_text",
            "input": "Agent Loop",
            "output": "pooL tnegA",
        }
    ]


def test_graph_uses_lowercase_text_tool_with_original_case():
    result = run_agent(
        "Lowercase Text in 'Agent Loop'",
        config=AgentConfig(max_steps=3, max_retries=1),
    )

    assert result["status"] == AgentStatus.DONE
    assert result["answer"] == "agent loop"
    assert result["tool_calls"] == [
        {
            "tool": "lowercase_text",
            "input": "Agent Loop",
            "output": "agent loop",
        }
    ]
