from copy import deepcopy

from self_correcting_langgraph_agent.core.agent import AgentConfig, run_agent
from self_correcting_langgraph_agent.core.invariants import validate_run_invariants


def test_validate_run_invariants_accepts_recovered_trace():
    result = run_agent(
        "uppercase text in 'agent loop'",
        config=AgentConfig(max_steps=4, max_retries=2),
        fault_plan={"uppercase text in 'agent loop'": ["empty-answer"]},
    )

    assert validate_run_invariants(result) == []


def test_validate_run_invariants_reports_corrupted_step_count():
    result = run_agent(
        "calculate 2 + 3",
        config=AgentConfig(max_steps=4, max_retries=1),
    )
    corrupted = deepcopy(result)
    corrupted["current_step"] = 0

    assert validate_run_invariants(corrupted) == [
        "current_step does not match completed step_results",
        "done status does not match completed plan",
    ]


def test_validate_run_invariants_reports_missing_verification_record():
    result = run_agent(
        "calculate 2 + 3",
        config=AgentConfig(max_steps=4, max_retries=1),
    )
    corrupted = deepcopy(result)
    corrupted["verification_results"] = []

    assert validate_run_invariants(corrupted) == [
        "verifier event count does not match verification_results"
    ]


def test_validate_run_invariants_reports_retry_count_mismatch():
    result = run_agent(
        "calculate 2 + 3",
        config=AgentConfig(max_steps=4, max_retries=1),
        fault_plan={"calculate 2 + 3": ["wrong-answer"]},
    )
    corrupted = deepcopy(result)
    corrupted["retry_count"] = 0

    assert validate_run_invariants(corrupted) == [
        "retry_count does not match reflections"
    ]
