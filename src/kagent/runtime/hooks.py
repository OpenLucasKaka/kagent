from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Protocol


@dataclass(frozen=True)
class RuntimeHookDecision:
    status: str
    reason: str = ""

    @classmethod
    def allow(cls) -> "RuntimeHookDecision":
        return cls(status="allowed")

    @classmethod
    def deny(cls, reason: str) -> "RuntimeHookDecision":
        return cls(status="denied", reason=reason or "runtime hook denied execution")


class RuntimeHook(Protocol):
    def on_run_start(self, context: Dict[str, Any]) -> None:
        ...

    def before_tool(self, context: Dict[str, Any]) -> RuntimeHookDecision:
        ...

    def after_tool(self, context: Dict[str, Any]) -> None:
        ...

    def on_run_end(self, context: Dict[str, Any]) -> None:
        ...


class RuntimeHookChain:
    def __init__(self, hooks: Iterable[Any] = ()) -> None:
        self._hooks = tuple(hooks)

    def __bool__(self) -> bool:
        return bool(self._hooks)

    def on_run_start(self, context: Dict[str, Any]) -> None:
        for hook in self._hooks:
            handler = getattr(hook, "on_run_start", None)
            if callable(handler):
                handler(dict(context))

    def before_tool(self, context: Dict[str, Any]) -> RuntimeHookDecision:
        for hook in self._hooks:
            handler = getattr(hook, "before_tool", None)
            if not callable(handler):
                continue
            decision = handler(dict(context))
            if decision is None:
                continue
            if not isinstance(decision, RuntimeHookDecision):
                raise ValueError("runtime hook before_tool must return RuntimeHookDecision")
            if decision.status == "denied":
                return decision
            if decision.status != "allowed":
                raise ValueError("runtime hook decision status must be allowed or denied")
        return RuntimeHookDecision.allow()

    def after_tool(self, context: Dict[str, Any]) -> None:
        for hook in self._hooks:
            handler = getattr(hook, "after_tool", None)
            if callable(handler):
                handler(dict(context))

    def on_run_end(self, context: Dict[str, Any]) -> None:
        for hook in self._hooks:
            handler = getattr(hook, "on_run_end", None)
            if callable(handler):
                handler(dict(context))
