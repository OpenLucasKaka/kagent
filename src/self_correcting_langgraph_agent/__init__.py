"""Self-correcting LangGraph agent package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("self-correcting-langgraph-agent")
except PackageNotFoundError:
    __version__ = "0.1.0"

__all__ = [
    "AgentConfig",
    "AgentStatus",
    "FakeLLMProvider",
    "LLMProviderConfig",
    "__version__",
    "agent_topology",
    "build_agent_graph",
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
        from self_correcting_langgraph_agent.core import agent

        return getattr(agent, name)
    if name in {"evaluate_agent", "registered_evaluation_cases"}:
        from self_correcting_langgraph_agent.eval import evaluator

        return getattr(evaluator, name)
    if name in {"FakeLLMProvider", "LLMProviderConfig"}:
        from self_correcting_langgraph_agent.providers import llm_provider

        return getattr(llm_provider, name)
    if name == "run_runtime_agent":
        from self_correcting_langgraph_agent.runtime import run_runtime_agent

        return run_runtime_agent
    if name == "summarize_run":
        from self_correcting_langgraph_agent.core.summary import summarize_run

        return summarize_run
    if name in {"registered_tool_metadata", "registered_tool_names"}:
        from self_correcting_langgraph_agent.core import tools

        return getattr(tools, name)
    raise AttributeError(name)
