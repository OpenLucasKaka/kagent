"""kagent LangGraph agent package."""

import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _source_tree_version() -> str:
    for parent in Path(__file__).resolve().parents:
        pyproject_path = parent / "pyproject.toml"
        if not pyproject_path.exists():
            continue
        pyproject = pyproject_path.read_text(encoding="utf-8")
        if 'name = "kagent"' not in pyproject:
            continue
        match = re.search(r'(?m)^version = "([^"]+)"$', pyproject)
        if match:
            return match.group(1)
    return ""


try:
    __version__ = _source_tree_version() or version("kagent")
except PackageNotFoundError:
    __version__ = "0.1.6"

__all__ = [
    "AgentConfig",
    "AgentStatus",
    "FakeLLMProvider",
    "LLMProviderConfig",
    "ProviderKind",
    "__version__",
    "agent_topology",
    "build_agent_graph",
    "detect_provider_kind",
    "evaluate_agent",
    "preview_plan",
    "registered_evaluation_cases",
    "registered_tool_metadata",
    "registered_tool_names",
    "runtime_topology",
    "run_agent",
    "run_runtime_agent",
    "summarize_run",
]


def __getattr__(name):
    if name in {
        "AgentConfig",
        "AgentStatus",
        "agent_topology",
        "build_agent_graph",
        "preview_plan",
        "run_agent",
    }:
        from kagent.core import agent

        return getattr(agent, name)
    if name in {"evaluate_agent", "registered_evaluation_cases"}:
        from kagent.eval import evaluator

        return getattr(evaluator, name)
    if name in {
        "FakeLLMProvider",
        "LLMProviderConfig",
        "ProviderKind",
        "detect_provider_kind",
    }:
        from kagent.providers import llm_provider

        return getattr(llm_provider, name)
    if name == "run_runtime_agent":
        from kagent.runtime import run_runtime_agent

        return run_runtime_agent
    if name == "runtime_topology":
        from kagent.runtime import runtime_topology

        return runtime_topology
    if name == "summarize_run":
        from kagent.core.summary import summarize_run

        return summarize_run
    if name in {"registered_tool_metadata", "registered_tool_names"}:
        from kagent.core import tools

        return getattr(tools, name)
    raise AttributeError(name)
