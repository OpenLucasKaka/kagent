from self_correcting_langgraph_agent.core.agent import AgentConfig, run_agent
from self_correcting_langgraph_agent.core.summary import summarize_run


def test_summarize_run_compacts_successful_trace():
    result = run_agent(
        "calculate 2 + 3 then count words in 'ship small reliable agents'",
        config=AgentConfig(max_steps=4, max_retries=1),
    )

    assert summarize_run(result) == {
        "status": "done",
        "answer": "4",
        "run_id": result["run_id"],
        "started_at": result["started_at"],
        "completed_at": result["completed_at"],
        "duration_seconds": result["duration_seconds"],
        "planned_steps": "2",
        "completed_steps": "2",
        "retry_count": "0",
        "failed_verifications": "0",
        "recovered": "false",
        "reflection_reasons": [],
        "reflection_reason_counts": {},
        "tool_call_count": "2",
        "tool_names": ["calculate_sum", "count_words"],
        "node_counts": {
            "executor": "2",
            "planner": "1",
            "verifier": "2",
        },
        "faults": [],
        "errors": [],
    }


def test_summarize_run_surfaces_recovery_signal():
    result = run_agent(
        "uppercase text in 'agent loop'",
        config=AgentConfig(max_steps=4, max_retries=2),
        fault_plan={"uppercase text in 'agent loop'": ["empty-answer"]},
    )

    summary = summarize_run(result)

    assert summary["status"] == "done"
    assert summary["retry_count"] == "1"
    assert summary["failed_verifications"] == "1"
    assert summary["recovered"] == "true"
    assert summary["reflection_reasons"] == ["answer was empty"]
    assert summary["reflection_reason_counts"] == {"answer was empty": "1"}
    assert summary["tool_call_count"] == "1"
    assert summary["faults"] == ["empty-answer"]
