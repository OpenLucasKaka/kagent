"""kagent LangGraph agent package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kagent")
except PackageNotFoundError:
    __version__ = "0.1.0"

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
    if name == "summarize_run":
        from kagent.core.summary import summarize_run

        return summarize_run
    if name in {"registered_tool_metadata", "registered_tool_names"}:
        from kagent.core import tools

        return getattr(tools, name)
    raise AttributeError(name)
