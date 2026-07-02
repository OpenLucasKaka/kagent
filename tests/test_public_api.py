from self_correcting_langgraph_agent import (
    FakeLLMProvider,
    LLMProviderConfig,
    __version__,
    agent_topology,
    evaluate_agent,
    registered_evaluation_cases,
    registered_tool_metadata,
    run_runtime_agent,
    summarize_run,
)


def test_public_api_exports_package_version():
    assert __version__ == "0.1.0"


def test_public_api_exports_agent_topology():
    assert agent_topology()["nodes"] == [
        "planner",
        "executor",
        "verifier",
        "reflector",
    ]


def test_public_api_exports_evaluator_entrypoint():
    report = evaluate_agent(case_name="subtraction_tool_success")

    assert report["passed"] == 1
    assert report["failed"] == 0


def test_public_api_exports_evaluator_case_metadata():
    cases = registered_evaluation_cases()

    assert cases[0] == {"name": "multi_step_success", "category": "workflow"}


def test_public_api_exports_tool_metadata():
    metadata = registered_tool_metadata()

    assert metadata[0]["name"] == "calculate_sum"
    assert metadata[-1]["name"] == "uppercase_text"


def test_public_api_exports_run_summary_helper():
    summary = summarize_run(
        {
            "status": "done",
            "answer": "5",
            "events": [{"node": "planner"}, {"node": "executor"}],
            "tool_calls": [{"tool": "calculate_sum"}],
            "verification_results": [{"passed": "true"}],
        }
    )

    assert summary["status"] == "done"
    assert summary["tool_names"] == ["calculate_sum"]


def test_public_api_exports_runtime_agent_entrypoint():
    provider = FakeLLMProvider(
        '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"}}]}'
    )

    result = run_runtime_agent("capture hello", provider=provider)

    assert result["status"] == "done"
    assert LLMProviderConfig.from_env({}).redacted_snapshot()["llm_provider"] == "unconfigured"
