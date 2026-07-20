import json
from pathlib import Path

from kagent import (
    FakeLLMProvider,
    LLMProviderConfig,
    ProviderKind,
    __version__,
    run_runtime_agent,
    runtime_topology,
)


def test_public_api_exports_package_version():
    package_version = json.loads(Path("package.json").read_text())["version"]

    assert __version__ == package_version


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
