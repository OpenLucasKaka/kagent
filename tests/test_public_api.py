import json
from pathlib import Path

from kagent import (
    FakeLLMProvider,
    LLMProviderConfig,
    ProviderKind,
    __version__,
    agent_topology,
    detect_provider_kind,
    evaluate_agent,
    registered_evaluation_cases,
    registered_tool_metadata,
    run_runtime_agent,
    runtime_topology,
    summarize_run,
)


def test_public_api_exports_package_version():
    package_version = json.loads(Path("package.json").read_text())["version"]

    assert __version__ == package_version


def test_public_api_exports_agent_topology():
    assert agent_topology()["nodes"] == [
        "planner",
        "executor",
        "verifier",
        "reflector",
    ]


def test_public_api_exports_runtime_topology():
    assert runtime_topology() == {
        "runtime_engine": "langgraph",
        "entry_point": "prepare",
        "terminal": "END",
        "nodes": [
            "prepare",
            "planner",
            "prepare_action",
            "mark_action_executing",
            "execute_action",
            "runtime_loop",
            "finalize",
        ],
        "edges": [
            "prepare -> planner",
            "planner -> prepare_action | runtime_loop",
            "prepare_action -> mark_action_executing | runtime_loop",
            "mark_action_executing -> execute_action | runtime_loop",
            "execute_action -> runtime_loop",
            "runtime_loop -> finalize",
            "finalize -> END",
        ],
        "loop": (
            "planner checkpoints the first plan; directly allowed single actions "
            "use action checkpoints; runtime_loop handles remaining execution and "
            "replanning"
        ),
        "runtime_loop_nodes": [
            "planner",
            "plan_parser",
            "policy",
            "executor",
            "observation",
            "replan_or_finish",
        ],
        "execution_flow": [
            "cli_goal_input",
            "provider_and_memory_context",
            "langgraph_prepare",
            "langgraph_planner",
            "langgraph_prepare_action",
            "policy",
            "langgraph_mark_action_executing",
            "langgraph_execute_action",
            "executor",
            "observation",
            "replan_or_finish",
            "langgraph_finalize",
            "cli_render",
        ],
    }


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
        '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"}}],'
        '"final_answer":"captured hello"}'
    )

    result = run_runtime_agent("capture hello", provider=provider)

    assert result["status"] == "done"
    assert LLMProviderConfig.from_env({}).redacted_snapshot()["llm_provider"] == "unconfigured"


def test_public_api_exports_provider_kind_helpers():
    assert ProviderKind.DEEPSEEK.value == "deepseek"
    assert detect_provider_kind("https://api.deepseek.com/v1") == ProviderKind.DEEPSEEK
