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
    __version__ = "0.1.10"

__all__ = [
    "FakeLLMProvider",
    "LLMProviderConfig",
    "ProviderKind",
    "__version__",
    "runtime_topology",
    "run_runtime_agent",
]


def __getattr__(name):
    if name in {
        "FakeLLMProvider",
        "LLMProviderConfig",
        "ProviderKind",
    }:
        from kagent.providers import llm_provider

        return getattr(llm_provider, name)
    if name == "run_runtime_agent":
        from kagent.runtime import run_runtime_agent

        return run_runtime_agent
    if name == "runtime_topology":
        from kagent.runtime import runtime_topology

        return runtime_topology
    raise AttributeError(name)
