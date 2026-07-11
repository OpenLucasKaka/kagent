from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, TypedDict

from kagent.runtime.cancellation import RuntimeCancellationToken
from kagent.runtime.policy import RuntimePolicy
from kagent.runtime.redaction import redact_runtime_text
from kagent.runtime.steering import RuntimeSteeringBuffer
from kagent.runtime.tools import RuntimeToolSpec

_CHECKPOINT_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
)

RuntimeEventSink = Callable[[Dict[str, Any]], None]


class RuntimeGraphState(TypedDict, total=False):
    goal: str
    run_id: str
    max_iterations: int
    approved_action_ids: List[str]
    metadata: Dict[str, str]
    tags: List[str]
    started_at: str
    initial_events: List[Dict[str, Any]]
    initial_hook_failure_count: int
    initial_planner: Dict[str, Any]
    initial_progress_events: List[Dict[str, Any]]
    initial_progress_event_sink_failure_count: int
    initial_action_prepared: Dict[str, Any]
    initial_action_phase: Dict[str, Any]
    initial_action_outcome: Dict[str, Any]
    result: Dict[str, Any]
    graph_phases: List[Dict[str, str]]


class RuntimeGraphContext(TypedDict, total=False):
    goal: str
    provider: Any
    policy: RuntimePolicy
    tools: Dict[str, RuntimeToolSpec]
    cancellation_token: RuntimeCancellationToken
    steering_buffer: RuntimeSteeringBuffer
    event_sink: RuntimeEventSink
    hooks: List[Any]
    runtime_workspace_dir: str
    redis_url: str
    milvus_url: str
    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str
    embedding_timeout_seconds: float
    embedding_max_retries: int
    embedding_retry_backoff_seconds: float
    external_backend_timeout_seconds: float
    stream_answers: bool
    planner_plan_cache: Dict[str, Dict[str, Any]]
    prepared_action_cache: Dict[str, Dict[str, Any]]
    executing_action_cache: Dict[str, Dict[str, Any]]


def checkpoint_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_runtime_text(value)
    if isinstance(value, dict):
        return {
            redact_runtime_text(str(key)): checkpoint_safe_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [checkpoint_safe_value(item) for item in value]
    return f"[unsupported {type(value).__name__}]"


def checkpoint_plan_projection(value: Any, *, key: str = "") -> tuple[Any, bool]:
    if key and any(part in key.lower() for part in _CHECKPOINT_SECRET_KEY_PARTS):
        return "[REDACTED]", True
    if value is None or isinstance(value, (bool, int, float)):
        return value, False
    if isinstance(value, str):
        redacted = redact_runtime_text(value)
        return redacted, redacted != value
    if isinstance(value, dict):
        projection: Dict[str, Any] = {}
        changed = False
        for raw_key, item in value.items():
            projected_key = str(raw_key)
            projected_item, item_changed = checkpoint_plan_projection(
                item,
                key=projected_key,
            )
            projection[projected_key] = projected_item
            changed = changed or item_changed
        return projection, changed
    if isinstance(value, (list, tuple)):
        projection = []
        changed = False
        for item in value:
            projected_item, item_changed = checkpoint_plan_projection(item)
            projection.append(projected_item)
            changed = changed or item_changed
        return projection, changed
    return f"[unsupported {type(value).__name__}]", True


def append_graph_phase(
    phases: List[Dict[str, str]] | None,
    node: str,
    started_at: str,
    started_timer: float,
) -> List[Dict[str, str]]:
    return [
        *(phases or []),
        {
            "node": node,
            "status": "ok",
            **timing_fields(started_at, started_timer),
        },
    ]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def timing_fields(started_at: str, started_timer: float) -> Dict[str, str]:
    return {
        "started_at": started_at,
        "completed_at": utc_timestamp(),
        "duration_seconds": duration_since(started_timer),
    }


def duration_since(started_at: float) -> str:
    return f"{time.perf_counter() - started_at:.4f}"
