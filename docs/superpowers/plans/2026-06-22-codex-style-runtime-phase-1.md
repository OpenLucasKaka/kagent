# Codex-Style Runtime Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first production-safe Codex-style agent runtime vertical slice: LLM-compatible planning, structured agent actions, policy-gated tool execution, traces, and service/CLI discovery without breaking the existing deterministic agent.

**Architecture:** Keep the existing deterministic LangGraph agent and `/run` API stable. Add a separate runtime layer with provider, plan, tool, policy, and trace boundaries that can run with a fake provider in tests and an OpenAI-compatible provider in real deployments. Expose the new runtime through focused Python APIs first, then CLI/service surfaces after the core is verified.

**Tech Stack:** Python 3.9, stdlib `urllib.request` for OpenAI-compatible HTTP calls, LangGraph project conventions, pytest, Ruff, existing service metrics and documentation gates.

---

## File Structure

- Create `src/self_correcting_langgraph_agent/llm_provider.py`
  - Owns provider config, fake provider, OpenAI-compatible request/response handling, redacted config snapshots, and JSON extraction errors.
- Create `src/self_correcting_langgraph_agent/runtime_types.py`
  - Owns `AgentAction`, `AgentPlan`, `AgentObservation`, `AgentRuntimeResult`, and parsing helpers.
- Create `src/self_correcting_langgraph_agent/runtime_tools.py`
  - Owns generic tool registry independent of regex deterministic tools.
- Create `src/self_correcting_langgraph_agent/runtime_policy.py`
  - Owns allow/deny/requires-approval decisions before tool execution.
- Create `src/self_correcting_langgraph_agent/runtime.py`
  - Owns `run_runtime_agent(goal, provider, policy)` orchestration for phase 1.
- Modify `src/self_correcting_langgraph_agent/__init__.py`
  - Export stable runtime APIs after tests prove behavior.
- Modify `docs/architecture.md`, `README.md`, `docs/operations.md`, and `docs/iteration_log.md`
  - Document the new runtime layer and provider environment variables.

## Task 1: Provider Configuration And Fake Provider

**Files:**
- Create: `src/self_correcting_langgraph_agent/llm_provider.py`
- Test: `tests/test_llm_provider.py`

- [ ] **Step 1: Write failing provider tests**

```python
from self_correcting_langgraph_agent.llm_provider import (
    FakeLLMProvider,
    LLMProviderConfig,
)


def test_provider_config_reads_openai_compatible_environment_without_exposing_key():
    config = LLMProviderConfig.from_env(
        {
            "SELF_CORRECTING_LLM_BASE_URL": "https://llm.example/v1",
            "SELF_CORRECTING_LLM_API_KEY": "secret-key",
            "SELF_CORRECTING_LLM_MODEL": "agent-model",
            "SELF_CORRECTING_LLM_TIMEOUT_SECONDS": "12.5",
        }
    )

    assert config.base_url == "https://llm.example/v1"
    assert config.model == "agent-model"
    assert config.timeout_seconds == 12.5
    assert config.redacted_snapshot() == {
        "llm_provider": "openai_compatible",
        "llm_base_url": "https://llm.example/v1",
        "llm_model": "agent-model",
        "llm_api_key_configured": "true",
        "llm_timeout_seconds": "12.5",
    }
    assert "secret-key" not in str(config.redacted_snapshot())


def test_fake_llm_provider_returns_configured_text_response():
    provider = FakeLLMProvider('{"actions": []}')

    assert provider.complete("system", "user") == '{"actions": []}'
    assert provider.calls == [{"system": "system", "user": "user"}]
```

- [ ] **Step 2: Run provider tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_llm_provider.py`

Expected: import failure for `self_correcting_langgraph_agent.llm_provider`.

- [ ] **Step 3: Implement provider config and fake provider**

Implement:

```python
@dataclass(frozen=True)
class LLMProviderConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "LLMProviderConfig": ...
    def redacted_snapshot(self) -> Dict[str, str]: ...


class FakeLLMProvider:
    def __init__(self, response_text: str) -> None: ...
    def complete(self, system: str, user: str) -> str: ...
```

- [ ] **Step 4: Run provider tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_llm_provider.py`

Expected: all tests pass.

## Task 2: Runtime Plan Types

**Files:**
- Create: `src/self_correcting_langgraph_agent/runtime_types.py`
- Test: `tests/test_runtime_types.py`

- [ ] **Step 1: Write failing plan parser tests**

```python
import pytest

from self_correcting_langgraph_agent.runtime_types import parse_agent_plan


def test_parse_agent_plan_accepts_strict_action_json():
    plan = parse_agent_plan(
        '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"},"reason":"capture"}]}'
    )

    assert plan.actions[0].id == "step-1"
    assert plan.actions[0].tool == "note"
    assert plan.actions[0].input == {"text": "hello"}
    assert plan.actions[0].reason == "capture"


def test_parse_agent_plan_rejects_missing_action_tool():
    with pytest.raises(ValueError, match="action tool is required"):
        parse_agent_plan('{"actions":[{"id":"step-1","input":{}}]}')
```

- [ ] **Step 2: Run parser tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_runtime_types.py`

Expected: import failure for `runtime_types`.

- [ ] **Step 3: Implement dataclasses and strict parser**

Implement `AgentAction`, `AgentPlan`, and `parse_agent_plan(text: str) -> AgentPlan`.
Reject non-object JSON, missing `actions`, non-list actions, missing `id`, missing `tool`, and non-object `input`.

- [ ] **Step 4: Run parser tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_runtime_types.py`

Expected: all tests pass.

## Task 3: Tool Runtime And Policy Gate

**Files:**
- Create: `src/self_correcting_langgraph_agent/runtime_tools.py`
- Create: `src/self_correcting_langgraph_agent/runtime_policy.py`
- Test: `tests/test_runtime_tools.py`

- [ ] **Step 1: Write failing tool/policy tests**

```python
from self_correcting_langgraph_agent.runtime_policy import RuntimePolicy
from self_correcting_langgraph_agent.runtime_tools import default_runtime_tools, execute_runtime_tool


def test_note_tool_returns_structured_observation():
    observation = execute_runtime_tool(
        default_runtime_tools(),
        "note",
        {"text": "remember this"},
    )

    assert observation.status == "ok"
    assert observation.output == {"text": "remember this"}


def test_policy_blocks_disallowed_tool_before_execution():
    decision = RuntimePolicy(allowed_tools={"note"}).authorize("http_request", {"url": "http://x"})

    assert decision.status == "denied"
    assert decision.reason == "tool_not_allowed"
```

- [ ] **Step 2: Run tool tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_runtime_tools.py`

Expected: import failure for runtime tool modules.

- [ ] **Step 3: Implement runtime tool registry and policy**

Implement:
- `RuntimeToolSpec(name, description, handler)`
- `RuntimeObservation(status, output, error_code, error)`
- `default_runtime_tools()` with `note`, `transform_text`
- `execute_runtime_tool(registry, tool_name, input_payload)`
- `RuntimePolicy(allowed_tools)` returning `PolicyDecision(status, reason)`

- [ ] **Step 4: Run tool tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_runtime_tools.py`

Expected: all tests pass.

## Task 4: Runtime Orchestrator Vertical Slice

**Files:**
- Create: `src/self_correcting_langgraph_agent/runtime.py`
- Test: `tests/test_runtime.py`
- Modify: `src/self_correcting_langgraph_agent/__init__.py`

- [ ] **Step 1: Write failing runtime orchestration tests**

```python
from self_correcting_langgraph_agent.llm_provider import FakeLLMProvider
from self_correcting_langgraph_agent.runtime import run_runtime_agent


def test_runtime_agent_runs_fake_llm_plan_through_policy_and_tools():
    provider = FakeLLMProvider(
        '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"},"reason":"capture"}]}'
    )

    result = run_runtime_agent("capture hello", provider=provider)

    assert result["status"] == "done"
    assert result["plan"]["actions"][0]["tool"] == "note"
    assert result["observations"][0]["status"] == "ok"
    assert result["events"][0]["node"] == "planner"


def test_runtime_agent_reports_policy_denial_as_requires_approval():
    provider = FakeLLMProvider(
        '{"actions":[{"id":"step-1","tool":"http_request","input":{"url":"https://example.com"},"reason":"fetch"}]}'
    )

    result = run_runtime_agent("fetch site", provider=provider)

    assert result["status"] == "requires_approval"
    assert result["observations"][0]["error_code"] == "tool_not_allowed"
```

- [ ] **Step 2: Run runtime tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_runtime.py`

Expected: import failure for `runtime`.

- [ ] **Step 3: Implement orchestrator**

Implement `run_runtime_agent(goal, provider, policy=None, tools=None) -> Dict[str, Any]`.
Prompt the provider for strict JSON, parse the plan, authorize each action, execute allowed tools, append planner/policy/executor events, and return `done`, `failed`, or `requires_approval`.

- [ ] **Step 4: Export runtime API**

Add package exports for `run_runtime_agent`, `LLMProviderConfig`, and `FakeLLMProvider`.

- [ ] **Step 5: Run runtime tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_runtime.py tests/test_public_api.py`

Expected: all tests pass.

## Task 5: Documentation And Gates

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/operations.md`
- Modify: `docs/iteration_log.md`
- Test: existing docs tests plus new assertions if needed

- [ ] **Step 1: Document phase 1 runtime**

Document:
- The deterministic `/run` path remains stable.
- The new runtime layer supports fake provider testing.
- OpenAI-compatible env vars are `SELF_CORRECTING_LLM_BASE_URL`, `SELF_CORRECTING_LLM_API_KEY`, `SELF_CORRECTING_LLM_MODEL`, `SELF_CORRECTING_LLM_TIMEOUT_SECONDS`.
- API keys are never written to config snapshots or traces.

- [ ] **Step 2: Run docs and full checks**

Run:

```sh
.venv/bin/python -m pytest tests/test_docs.py tests/test_operations_docs.py tests/test_public_api.py
scripts/run_checks.sh
```

Expected: all checks pass.

## Self-Review

- Spec coverage: This plan covers phase 1 only: provider abstraction, strict plan parsing, runtime tools, policy gate, orchestration, public API, docs, and gates.
- Placeholder scan: No TBD/TODO placeholders remain.
- Type consistency: Provider, plan, observation, policy, and runtime names are consistent across tasks.
- Scope note: Service endpoint integration is intentionally deferred until the Python API vertical slice is stable; this prevents breaking the existing production `/run` API while the runtime core lands.
