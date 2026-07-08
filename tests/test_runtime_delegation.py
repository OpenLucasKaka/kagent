from __future__ import annotations

from kagent.providers.llm import SequentialFakeLLMProvider
from kagent.runtime import run_runtime_agent


def test_runtime_agent_can_delegate_bounded_child_task():
    provider = SequentialFakeLLMProvider(
        [
            (
                '{"actions":[{"id":"step-1","tool":"delegate_task",'
                '"input":{"goal":"summarize pilot risks","max_iterations":1},'
                '"reason":"delegate research subtask"}],'
                '"final_answer":"delegated risk summary"}'
            ),
            '{"actions":[],"final_answer":"Pilot risks: adoption, data quality."}',
        ]
    )

    result = run_runtime_agent(
        "plan internal pilot",
        provider=provider,
        max_iterations=1,
    )

    assert result["status"] == "done"
    assert result["observations"][0]["tool"] == "delegate_task"
    assert result["observations"][0]["output"]["status"] == "done"
    assert result["observations"][0]["output"]["answer"] == (
        "Pilot risks: adoption, data quality."
    )
    assert result["observations"][0]["output"]["child_iteration_count"] == "1"
    assert result["observations"][0]["output"]["child_observation_count"] == "0"
    assert len(result["observations"][0]["output"]["child_run_id"]) > 0
    assert "plans" not in result["observations"][0]["output"]


def test_runtime_delegate_task_rejects_nested_delegation_by_default():
    provider = SequentialFakeLLMProvider(
        [
            (
                '{"actions":[{"id":"step-1","tool":"delegate_task",'
                '"input":{"goal":"nested task","max_iterations":1},'
                '"reason":"delegate"}],"final_answer":"delegated once"}'
            ),
            (
                '{"actions":[{"id":"step-1","tool":"delegate_task",'
                '"input":{"goal":"too deep","max_iterations":1},'
                '"reason":"nested delegate"}]}'
            ),
        ]
    )

    result = run_runtime_agent(
        "delegate once",
        provider=provider,
        max_iterations=1,
    )

    assert result["status"] == "done"
    assert result["observations"][0]["status"] == "ok"
    assert result["observations"][0]["output"]["status"] == "failed"
    assert result["observations"][0]["output"]["error_code"] == "tool_not_found"
