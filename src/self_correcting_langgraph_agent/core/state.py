from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from os import environ
from typing import Any, Dict, List, Mapping, Optional, TypedDict


class AgentStatus(str, Enum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class AgentConfig:
    max_steps: int = 6
    max_retries: int = 2

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "AgentConfig":
        source = env if env is not None else environ
        return cls(
            max_steps=_env_int(source, "SELF_CORRECTING_MAX_STEPS", cls.max_steps),
            max_retries=_env_int(
                source,
                "SELF_CORRECTING_MAX_RETRIES",
                cls.max_retries,
            ),
        )

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")


class AgentState(TypedDict, total=False):
    run_id: str
    started_at: str
    completed_at: str
    duration_seconds: str
    goal: str
    config: Dict[str, int]
    plan: List[str]
    plan_validations: List[Dict[str, str]]
    current_step: int
    answer: Optional[str]
    step_results: List[str]
    tool_calls: List[Dict[str, str]]
    execution_attempts: List[Dict[str, str]]
    verified: bool
    retry_count: int
    step_retry_count: int
    status: AgentStatus
    errors: List[str]
    events: List[Dict[str, Any]]
    fault_plan: Dict[str, List[str]]
    fault_counters: Dict[str, int]
    reflection_notes: List[str]
    reflections: List[Dict[str, str]]
    verification_results: List[Dict[str, str]]


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name)
    if value in {None, ""}:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
