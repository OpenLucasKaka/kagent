from __future__ import annotations

from typing import Any, Dict

from kagent.providers.llm import FakeLLMProvider
from kagent.runtime import run_runtime_agent
from kagent.runtime.hooks import RuntimeHookDecision


class RecordingHook:
    def __init__(self) -> None:
        self.events: list[tuple[str, Dict[str, Any]]] = []

    def on_run_start(self, context: Dict[str, Any]) -> None:
        self.events.append(("run_start", context))

    def before_tool(self, context: Dict[str, Any]) -> RuntimeHookDecision:
        self.events.append(("before_tool", context))
        return RuntimeHookDecision.allow()

    def after_tool(self, context: Dict[str, Any]) -> None:
        self.events.append(("after_tool", context))

    def on_run_end(self, context: Dict[str, Any]) -> None:
        self.events.append(("run_end", context))


class DenyNoteHook:
    def before_tool(self, context: Dict[str, Any]) -> RuntimeHookDecision:
        if context["tool"] == "note":
            return RuntimeHookDecision.deny("note is disabled by test hook")
        return RuntimeHookDecision.allow()


class FailingLifecycleHook:
    def on_run_start(self, _context: Dict[str, Any]) -> None:
        raise RuntimeError("audit start unavailable")

    def after_tool(self, _context: Dict[str, Any]) -> None:
        raise RuntimeError("audit after unavailable")

    def on_run_end(self, _context: Dict[str, Any]) -> None:
        raise RuntimeError("audit end unavailable")


class FailingBeforeToolHook:
    def before_tool(self, _context: Dict[str, Any]) -> RuntimeHookDecision:
        raise RuntimeError("permission hook unavailable")


def test_runtime_hooks_observe_run_and_tool_lifecycle():
    hook = RecordingHook()
    provider = FakeLLMProvider(
        '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"},'
        '"reason":"capture"}],"final_answer":"captured hello"}'
    )

    result = run_runtime_agent(
        "capture hello",
        provider=provider,
        hooks=[hook],
    )

    assert result["status"] == "done"
    assert [name for name, _context in hook.events] == [
        "run_start",
        "before_tool",
        "after_tool",
        "run_end",
    ]
    assert hook.events[0][1]["goal"] == "capture hello"
    assert hook.events[1][1]["action_id"] == "step-1"
    assert hook.events[1][1]["tool"] == "note"
    assert hook.events[2][1]["observation"]["status"] == "ok"
    assert hook.events[3][1]["status"] == "done"


def test_runtime_hook_can_deny_tool_before_execution():
    provider = FakeLLMProvider(
        '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"},'
        '"reason":"capture"}],"final_answer":"captured hello"}'
    )

    result = run_runtime_agent(
        "capture hello",
        provider=provider,
        hooks=[DenyNoteHook()],
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "runtime_hook_denied"
    assert result["error"] == "note is disabled by test hook"
    assert result["observations"][0]["tool"] == "note"
    assert result["observations"][0]["status"] == "failed"
    assert result["observations"][0]["error_code"] == "runtime_hook_denied"
    assert result["events"][2]["node"] == "hook"
    assert result["events"][2]["status"] == "denied"


def test_runtime_lifecycle_hook_failures_are_observable_without_failing_run():
    provider = FakeLLMProvider(
        '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"},'
        '"reason":"capture"}],"final_answer":"captured hello"}'
    )

    result = run_runtime_agent(
        "capture hello",
        provider=provider,
        hooks=[FailingLifecycleHook()],
    )

    assert result["status"] == "done"
    assert result["answer"] == "hello"
    assert result["hook_failure_count"] == "3"
    hook_failures = [
        event
        for event in result["events"]
        if event.get("node") == "hook" and event.get("status") == "failed"
    ]
    assert [event["stage"] for event in hook_failures] == [
        "on_run_start",
        "after_tool",
        "on_run_end",
    ]
    assert all(event["error_code"] == "runtime_hook_failed" for event in hook_failures)


def test_runtime_before_tool_hook_failure_is_structured_and_fail_closed():
    provider = FakeLLMProvider(
        '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"},'
        '"reason":"capture"}],"final_answer":"captured hello"}'
    )

    result = run_runtime_agent(
        "capture hello",
        provider=provider,
        hooks=[FailingBeforeToolHook()],
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "runtime_hook_failed"
    assert result["hook_failure_count"] == "1"
    assert result["observations"][0]["tool"] == "note"
    assert result["observations"][0]["status"] == "failed"
    assert result["observations"][0]["error_code"] == "runtime_hook_failed"
    assert result["events"][2]["node"] == "hook"
    assert result["events"][2]["stage"] == "before_tool"
    assert result["events"][2]["status"] == "failed"
