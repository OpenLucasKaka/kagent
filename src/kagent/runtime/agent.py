from __future__ import annotations

import copy
import json
import re
import time
import warnings
from contextlib import nullcontext
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

import kagent.runtime.checkpoint_state as checkpoint_state
from kagent.runtime.action_graph import (
    execute_action_graph_node,
    mark_action_graph_node,
    prepare_action_graph_node,
    route_after_mark_action,
    route_after_planner,
    route_after_prepare_action,
)
from kagent.runtime.cancellation import RuntimeCancellationToken
from kagent.runtime.context import RuntimeContextManager
from kagent.runtime.hooks import RuntimeHookChain
from kagent.runtime.metadata import (
    validate_runtime_metadata,
    validate_runtime_tags,
)
from kagent.runtime.policy import RuntimePolicy
from kagent.runtime.presentation import (
    project_runtime_presentation,
    project_runtime_start_presentation,
)
from kagent.runtime.redaction import redact_runtime_payload, redact_runtime_text
from kagent.runtime.steering import RuntimeSteeringBuffer
from kagent.runtime.steps import derive_runtime_steps
from kagent.runtime.tools import (
    RuntimeToolSpec,
    default_runtime_tools,
    execute_runtime_tool,
    runtime_tool_metadata,
)
from kagent.runtime.types import (
    MAX_ACTION_REASON_CHARS,
    MAX_PLAN_ACTIONS,
    MAX_PLAN_FINAL_ANSWER_CHARS,
    AgentObservation,
    parse_agent_plan,
)

RuntimeEventSink = checkpoint_state.RuntimeEventSink
RuntimeGraphContext = checkpoint_state.RuntimeGraphContext
RuntimeGraphState = checkpoint_state.RuntimeGraphState
_append_graph_phase = checkpoint_state.append_graph_phase
_checkpoint_plan_projection = checkpoint_state.checkpoint_plan_projection
_checkpoint_safe_value = checkpoint_state.checkpoint_safe_value
_duration_since = checkpoint_state.duration_since
_timing_fields = checkpoint_state.timing_fields
_utc_timestamp = checkpoint_state.utc_timestamp

_SYSTEM_PROMPT = (
    """You are a production agent planner.
Your product identity is "kagent", a non-coding automation agent that runs
inside the user's current CLI or service process.
Never answer user identity, deployment, ownership, or hosting questions as if
you are the underlying model provider. Do not claim to be Qwen, ChatGPT,
Claude, or any other model brand unless the user explicitly asks about the
configured provider. In user-facing answers, do not expose provider details
unless the user explicitly asks about provider configuration.
Do not compare kagent to another assistant, coding tool, or runtime brand in
user-facing answers. Describe kagent directly.
Return strict JSON only with this shape:
{"actions":[{"id":"step-1","tool":"note","input":{"text":"..."},"reason":"..."}],
"final_answer":"..."}
Use only tools that are available to you.
"""
    f"Return at most {MAX_PLAN_ACTIONS} actions in one plan.\n"
    f"Keep action reason at most {MAX_ACTION_REASON_CHARS} characters.\n"
    f"Keep final_answer at most {MAX_PLAN_FINAL_ANSWER_CHARS} characters; "
    "use artifact for long-form deliverables.\n"
    "Use optional depends_on with prior action IDs when one action depends on earlier output. "
    "Reference dependency output inside input with "
    '{"$from_action":"step-1","pointer":"/field"}; pointer is a JSON Pointer.\n'
    "Use open_app to open a local macOS application by application name. "
    "Use open_url to open a browser page; use http_request only to fetch URL "
    "content as an observation.\n"
    "Use list_files and read_file to observe workspace state before changing "
    "workspace files with apply_patch.\n"
    "Use patch_history before revert_patch. Revert only when the user requests "
    "undo or rollback, and pass the exact checkpoint ID and paths returned by "
    "patch_history so the reviewed change receives approval.\n"
    "Use delegate_task to hand off a bounded independent subtask to a child "
    "kagent runtime; keep delegated goals specific and self-contained.\n"
    "Use skill_list and skill_get when the task may benefit from installed "
    "runtime skills or reusable operating procedures.\n"
    "Use memory_put and memory_get for configured Redis short-term memory. "
    "Use memory_remember and memory_recall for configured text-based long-term "
    "semantic memory. Use memory_upsert and memory_search only when you have "
    "explicit embedding vectors.\n"
    "Use workspace_history and workspace_diff when reviewing virtual workspace changes, "
    "policy drafts, reports, logs, or persisted working assets.\n"
    "Use workspace_restore only when the user requests rollback, after reading "
    "history or diff, and pass the reviewed current and revision SHA-256 values.\n"
    "Use shell_command for bounded non-interactive local CLI checks; it is "
    "policy-gated and may require explicit approval before execution.\n"
    "Never use shell_command for curl, wget, or other network requests; use "
    "http_request for network content.\n"
    "Do not use note merely to compose an answer; when no external action is "
    "needed, return an action-free final_answer directly.\n"
    "When returning actions, omit final_answer because their results are not yet "
    "available. Do not repeat completed actions from previous observations. After "
    "the work is complete, return an action-free final_answer that tells the user "
    "what was handled, what was done, and the actual result.\n"
    "Answer only the current user request. Do not offer unrelated follow-up tasks "
    "or end with generic invitations to ask for more help. Do not mention prior "
    "requests unless the current user message asks about them.\n"
    "If the latest previous observation failed, do not return final_answer with "
    "empty actions; either plan recovery actions or leave the run failed.\n"
    'If the goal is complete, return {"actions":[],"final_answer":"..."} '
    "with a direct user-facing answer."
)

_FINAL_RESPONSE_SYSTEM_PROMPT = """You are kagent's final response writer.
Return strict JSON only with this shape:
{"actions":[],"final_answer":"..."}
Use the completed tool observations to write final_answer. Do not plan, request,
or repeat any tool action. Never include unrelated follow-up tasks, generic
invitations to ask for more help, or prior requests unless the current user
message asks about them. Be concise and preserve important result values."""

RUNTIME_TRACE_TYPE = "codex_runtime"
MAX_PLANNER_OBSERVATION_STRING_CHARS = 500
MAX_STEERING_APPLIED_PER_RUN = 8


def build_runtime_graph(
    *,
    checkpointer: Any = None,
    interrupt_after: List[str] | None = None,
):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            from langchain_core._api.deprecation import (
                suppress_langchain_deprecation_warning,
            )
        except ImportError:
            suppress_langchain_deprecation_warning = nullcontext
        with suppress_langchain_deprecation_warning():
            from langgraph.graph import END, StateGraph

    graph = StateGraph(RuntimeGraphState, context_schema=RuntimeGraphContext)
    graph.add_node("prepare", _runtime_prepare_graph_node)
    graph.add_node("planner", _runtime_planner_graph_node)
    graph.add_node("prepare_action", prepare_action_graph_node)
    graph.add_node("mark_action_executing", mark_action_graph_node)
    graph.add_node("execute_action", execute_action_graph_node)
    graph.add_node("runtime_loop", _runtime_loop_graph_node)
    graph.add_node("finalize", _runtime_finalize_graph_node)
    graph.set_entry_point("prepare")
    graph.add_edge("prepare", "planner")
    graph.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "prepare_action": "prepare_action",
            "runtime_loop": "runtime_loop",
        },
    )
    graph.add_conditional_edges(
        "prepare_action",
        route_after_prepare_action,
        {
            "mark_action_executing": "mark_action_executing",
            "runtime_loop": "runtime_loop",
        },
    )
    graph.add_conditional_edges(
        "mark_action_executing",
        route_after_mark_action,
        {
            "execute_action": "execute_action",
            "runtime_loop": "runtime_loop",
        },
    )
    graph.add_edge("execute_action", "runtime_loop")
    graph.add_edge("runtime_loop", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_after=interrupt_after,
        name="kagent-runtime",
    )


def runtime_topology() -> Dict[str, List[str] | str]:
    return {
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


def run_runtime_agent(
    goal: str,
    *,
    provider: Any,
    run_id: str = "",
    cancellation_token: Optional[RuntimeCancellationToken] = None,
    steering_buffer: Optional[RuntimeSteeringBuffer] = None,
    policy: Optional[RuntimePolicy] = None,
    tools: Optional[Dict[str, RuntimeToolSpec]] = None,
    max_iterations: int = 1,
    approved_action_ids: Optional[Set[str]] = None,
    metadata: Optional[Dict[str, str]] = None,
    tags: Optional[List[str]] = None,
    event_sink: Optional[RuntimeEventSink] = None,
    hooks: Optional[List[Any]] = None,
    runtime_workspace_dir: str = "",
    redis_url: str = "",
    milvus_url: str = "",
    embedding_base_url: str = "",
    embedding_api_key: str = "",
    embedding_model: str = "",
    embedding_timeout_seconds: float = 30.0,
    embedding_max_retries: int = 2,
    embedding_retry_backoff_seconds: float = 0.25,
    external_backend_timeout_seconds: float = 2.0,
    stream_answers: bool = False,
    checkpointer: Any = None,
) -> Dict[str, Any]:
    if max_iterations < 1:
        raise ValueError("max_iterations must be at least 1")
    resolved_run_id = run_id.strip() or str(uuid4())
    normalized_metadata, metadata_error = validate_runtime_metadata(metadata)
    if metadata_error:
        raise ValueError(metadata_error)
    normalized_tags, tags_error = validate_runtime_tags(tags)
    if tags_error:
        raise ValueError(tags_error)
    graph = build_runtime_graph(checkpointer=checkpointer)
    state: RuntimeGraphState = {
        "goal": redact_runtime_text(goal),
        "run_id": resolved_run_id,
        "max_iterations": max_iterations,
        "approved_action_ids": sorted(approved_action_ids or set()),
        "metadata": normalized_metadata,
        "tags": [redact_runtime_text(tag) for tag in normalized_tags],
    }
    context: RuntimeGraphContext = {
        "goal": goal,
        "provider": provider,
        "runtime_workspace_dir": runtime_workspace_dir,
        "redis_url": redis_url,
        "milvus_url": milvus_url,
        "embedding_base_url": embedding_base_url,
        "embedding_api_key": embedding_api_key,
        "embedding_model": embedding_model,
        "embedding_timeout_seconds": embedding_timeout_seconds,
        "embedding_max_retries": embedding_max_retries,
        "embedding_retry_backoff_seconds": embedding_retry_backoff_seconds,
        "external_backend_timeout_seconds": external_backend_timeout_seconds,
        "stream_answers": stream_answers,
    }
    active_policy = policy or RuntimePolicy()

    def delegate_child(child_goal: str, child_max_iterations: int) -> Dict[str, Any]:
        return run_runtime_agent(
            child_goal,
            provider=provider,
            cancellation_token=cancellation_token,
            policy=active_policy,
            tools=default_runtime_tools(
                runtime_workspace_dir=runtime_workspace_dir,
                redis_url=redis_url,
                milvus_url=milvus_url,
                embedding_base_url=embedding_base_url,
                embedding_api_key=embedding_api_key,
                embedding_model=embedding_model,
                embedding_timeout_seconds=embedding_timeout_seconds,
                embedding_max_retries=embedding_max_retries,
                embedding_retry_backoff_seconds=embedding_retry_backoff_seconds,
                external_backend_timeout_seconds=external_backend_timeout_seconds,
                include_delegate_tool=False,
            ),
            max_iterations=child_max_iterations,
            metadata=normalized_metadata,
            tags=normalized_tags,
            runtime_workspace_dir=runtime_workspace_dir,
            redis_url=redis_url,
            milvus_url=milvus_url,
            embedding_base_url=embedding_base_url,
            embedding_api_key=embedding_api_key,
            embedding_model=embedding_model,
            embedding_timeout_seconds=embedding_timeout_seconds,
            embedding_max_retries=embedding_max_retries,
            embedding_retry_backoff_seconds=embedding_retry_backoff_seconds,
            external_backend_timeout_seconds=external_backend_timeout_seconds,
        )

    context["policy"] = active_policy
    context["tools"] = tools or default_runtime_tools(
        runtime_workspace_dir=runtime_workspace_dir,
        redis_url=redis_url,
        milvus_url=milvus_url,
        embedding_base_url=embedding_base_url,
        embedding_api_key=embedding_api_key,
        embedding_model=embedding_model,
        embedding_timeout_seconds=embedding_timeout_seconds,
        embedding_max_retries=embedding_max_retries,
        embedding_retry_backoff_seconds=embedding_retry_backoff_seconds,
        external_backend_timeout_seconds=external_backend_timeout_seconds,
        delegate_runner=delegate_child,
    )
    if cancellation_token is not None:
        context["cancellation_token"] = cancellation_token
    if steering_buffer is not None:
        context["steering_buffer"] = steering_buffer
    if event_sink is not None:
        context["event_sink"] = event_sink
    if hooks is not None:
        context["hooks"] = hooks
    config = {"configurable": {"thread_id": resolved_run_id}}
    if checkpointer is not None and checkpointer.get_tuple(config) is not None:
        raise ValueError("checkpoint thread already exists for run_id")
    final_state = graph.invoke(
        state,
        config=config,
        context=context,
    )
    result = final_state.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("runtime graph did not return a result")
    return result


def _runtime_prepare_graph_node(
    state: RuntimeGraphState,
    runtime: Any,
) -> RuntimeGraphState:
    started_at = _utc_timestamp()
    started_timer = time.perf_counter()
    if not runtime.context or "provider" not in runtime.context:
        raise ValueError("provider is required")
    context: RuntimeGraphContext = runtime.context
    initial_events: List[Dict[str, Any]] = []
    hook_failure_count = 0
    hooks = context.get("hooks") or []
    if hooks:
        hook_started_at = _utc_timestamp()
        hook_timer = time.perf_counter()
        try:
            RuntimeHookChain(hooks).on_run_start(
                {
                    "run_id": state.get("run_id", ""),
                    "goal": context.get("goal", state.get("goal", "")),
                    "started_at": started_at,
                    "metadata": state.get("metadata", {}),
                    "tags": state.get("tags", []),
                }
            )
        except Exception as exc:
            hook_failure_count = 1
            initial_events.append(
                {
                    "node": "hook",
                    "stage": "on_run_start",
                    "status": "failed",
                    "error_code": "runtime_hook_failed",
                    "error": redact_runtime_text(str(exc)),
                    **_timing_fields(hook_started_at, hook_timer),
                }
            )
    return {
        "started_at": started_at,
        "initial_events": initial_events,
        "initial_hook_failure_count": hook_failure_count,
        "graph_phases": _append_graph_phase(
            state.get("graph_phases"),
            "prepare",
            started_at,
            started_timer,
        )
    }


def _runtime_planner_graph_node(
    state: RuntimeGraphState,
    runtime: Any,
) -> RuntimeGraphState:
    graph_started_at = _utc_timestamp()
    graph_timer = time.perf_counter()
    context: RuntimeGraphContext = runtime.context or {}
    run_id = str(state.get("run_id", ""))
    cancellation_token = context.get("cancellation_token")
    if cancellation_token is not None and cancellation_token.is_cancelled():
        return {
            "initial_planner": {"status": "cancelled"},
            "initial_progress_events": [],
            "initial_progress_event_sink_failure_count": 0,
            "graph_phases": _append_graph_phase(
                state.get("graph_phases"),
                "planner",
                graph_started_at,
                graph_timer,
            ),
        }

    active_tools = context.get("tools") or default_runtime_tools(
        runtime_workspace_dir=context.get("runtime_workspace_dir", ""),
        redis_url=context.get("redis_url", ""),
        milvus_url=context.get("milvus_url", ""),
        embedding_base_url=context.get("embedding_base_url", ""),
        embedding_api_key=context.get("embedding_api_key", ""),
        embedding_model=context.get("embedding_model", ""),
        embedding_timeout_seconds=context.get("embedding_timeout_seconds", 30.0),
        embedding_max_retries=context.get("embedding_max_retries", 2),
        embedding_retry_backoff_seconds=context.get(
            "embedding_retry_backoff_seconds",
            0.25,
        ),
        external_backend_timeout_seconds=context.get(
            "external_backend_timeout_seconds",
            2.0,
        ),
    )
    context["tools"] = active_tools
    context.setdefault("policy", RuntimePolicy())
    progress_events: List[Dict[str, Any]] = []
    sink_failure_count = 0

    def emit_progress(event: Dict[str, Any]) -> None:
        nonlocal sink_failure_count
        event_with_run_id = {"run_id": run_id, **event}
        progress_events.append(event_with_run_id)
        event_sink = context.get("event_sink")
        if event_sink is not None:
            try:
                event_sink(event_with_run_id)
            except Exception:
                sink_failure_count += 1

    planner_started_at = _utc_timestamp()
    planner_timer = time.perf_counter()
    _emit_runtime_progress(
        emit_progress,
        "planner_started",
        iteration="1",
        node="planner",
        status="started",
    )
    try:
        plan_text, streamed = _complete_plan_text(
            context["provider"],
            _SYSTEM_PROMPT,
            _runtime_user_prompt(
                str(context.get("goal", state.get("goal", ""))),
                active_tools,
                [],
                context_manager=RuntimeContextManager(
                    max_string_chars=MAX_PLANNER_OBSERVATION_STRING_CHARS
                ),
            ),
            emit_progress=emit_progress,
            stream_answer=(
                context.get("stream_answers", False)
                and not _is_runtime_identity_question(
                    str(context.get("goal", state.get("goal", ""))).lower()
                )
                and not _is_runtime_deployment_question(
                    str(context.get("goal", state.get("goal", ""))).lower()
                )
            ),
        )
        plan = parse_agent_plan(plan_text)
        _require_final_answer_for_empty_actions(plan)
    except Exception as exc:
        error_code = _planner_failure_error_code(exc)
        timing = _timing_fields(planner_started_at, planner_timer)
        event = {
            "node": "planner",
            "status": "failed",
            "iteration": "1",
            **timing,
        }
        _emit_runtime_progress(
            emit_progress,
            "planner_failed",
            iteration="1",
            node="planner",
            status="failed",
            error_code=error_code,
            duration_seconds=timing["duration_seconds"],
        )
        return {
            "initial_events": [*(state.get("initial_events") or []), event],
            "initial_planner": {
                "status": "failed",
                "error_code": error_code,
                "error": redact_runtime_text(str(exc)),
                "started_at": planner_started_at,
                **timing,
            },
            "initial_progress_events": _checkpoint_safe_value(progress_events),
            "initial_progress_event_sink_failure_count": sink_failure_count,
            "graph_phases": _append_graph_phase(
                state.get("graph_phases"),
                "planner",
                graph_started_at,
                graph_timer,
            ),
        }

    timing = _timing_fields(planner_started_at, planner_timer)
    raw_plan = plan.to_dict()
    checkpoint_plan, plan_redacted = _checkpoint_plan_projection(raw_plan)
    plan_cache_token = str(uuid4())
    planner_plan_cache = context.setdefault("planner_plan_cache", {})
    planner_plan_cache[run_id] = {
        "token": plan_cache_token,
        "plan": copy.deepcopy(raw_plan),
    }
    event = {
        "node": "planner",
        "status": "ok",
        "action_count": str(len(plan.actions)),
        "iteration": "1",
        **timing,
    }
    _emit_runtime_progress(
        emit_progress,
        "planner_completed",
        iteration="1",
        node="planner",
        status="ok",
        action_count=str(len(plan.actions)),
        duration_seconds=timing["duration_seconds"],
    )
    return {
        "initial_events": [*(state.get("initial_events") or []), event],
        "initial_planner": {
            "status": "ok",
            "plan": checkpoint_plan,
            "plan_redacted": plan_redacted,
            "plan_cache_token": plan_cache_token,
            "answer_streamed": bool(streamed),
            "started_at": planner_started_at,
            **timing,
        },
        "initial_progress_events": _checkpoint_safe_value(progress_events),
        "initial_progress_event_sink_failure_count": sink_failure_count,
        "graph_phases": _append_graph_phase(
            state.get("graph_phases"),
            "planner",
            graph_started_at,
            graph_timer,
        ),
    }


def _runtime_loop_graph_node(
    state: RuntimeGraphState,
    runtime: Any,
) -> RuntimeGraphState:
    started_at = _utc_timestamp()
    started_timer = time.perf_counter()
    context: RuntimeGraphContext = runtime.context or {}
    initial_planner = copy.deepcopy(state.get("initial_planner"))
    initial_events = list(state.get("initial_events") or [])
    initial_action_outcome = copy.deepcopy(state.get("initial_action_outcome"))
    if (
        initial_action_outcome is None
        and initial_planner
        and initial_planner.get("status") == "ok"
    ):
        run_id = str(state.get("run_id", ""))
        cache_entry = (context.get("planner_plan_cache") or {}).get(run_id)
        expected_cache_token = str(initial_planner.get("plan_cache_token", ""))
        if (
            isinstance(cache_entry, dict)
            and cache_entry.get("token") == expected_cache_token
            and isinstance(cache_entry.get("plan"), dict)
        ):
            initial_planner["plan"] = copy.deepcopy(cache_entry["plan"])
        elif initial_planner.get("plan_redacted"):
            initial_planner = {
                "status": "failed",
                "error_code": "planner_checkpoint_sensitive_input",
                "error": (
                    "planner checkpoint contains sensitive tool input; "
                    "the original in-memory plan is unavailable"
                ),
                "started_at": initial_planner.get("started_at", started_at),
                "completed_at": _utc_timestamp(),
                "duration_seconds": "0.0000",
            }
            checkpoint_time = _utc_timestamp()
            initial_events.append(
                {
                    "node": "checkpoint",
                    "status": "failed",
                    "error_code": "planner_checkpoint_sensitive_input",
                    "started_at": checkpoint_time,
                    "completed_at": checkpoint_time,
                    "duration_seconds": "0.0000",
                }
            )
        if isinstance(context.get("planner_plan_cache"), dict):
            context["planner_plan_cache"].pop(run_id, None)
    elif initial_action_outcome is not None:
        planner_cache = context.get("planner_plan_cache")
        if isinstance(planner_cache, dict):
            planner_cache.pop(str(state.get("run_id", "")), None)
    result = _checkpoint_safe_value(
        _run_runtime_agent_loop(
            str(context.get("goal", state.get("goal", ""))),
            provider=context["provider"],
            run_id=state.get("run_id", ""),
            cancellation_token=context.get("cancellation_token"),
            steering_buffer=context.get("steering_buffer"),
            policy=context.get("policy"),
            tools=context.get("tools"),
            max_iterations=state.get("max_iterations", 1),
            approved_action_ids=set(state.get("approved_action_ids", [])),
            metadata=state.get("metadata"),
            tags=state.get("tags"),
            event_sink=context.get("event_sink"),
            hooks=context.get("hooks"),
            runtime_workspace_dir=context.get("runtime_workspace_dir", ""),
            redis_url=context.get("redis_url", ""),
            milvus_url=context.get("milvus_url", ""),
            embedding_base_url=context.get("embedding_base_url", ""),
            embedding_api_key=context.get("embedding_api_key", ""),
            embedding_model=context.get("embedding_model", ""),
            embedding_timeout_seconds=context.get(
                "embedding_timeout_seconds",
                30.0,
            ),
            embedding_max_retries=context.get("embedding_max_retries", 2),
            embedding_retry_backoff_seconds=context.get(
                "embedding_retry_backoff_seconds",
                0.25,
            ),
            external_backend_timeout_seconds=context.get(
                "external_backend_timeout_seconds",
                2.0,
            ),
            stream_answers=context.get("stream_answers", False),
            initial_planner=initial_planner,
            initial_events=initial_events,
            initial_progress_events=state.get("initial_progress_events"),
            initial_progress_event_sink_failure_count=state.get(
                "initial_progress_event_sink_failure_count",
                0,
            ),
            initial_hook_failure_count=state.get("initial_hook_failure_count", 0),
            started_at=state.get("started_at", ""),
            run_start_hook_completed=True,
            initial_action_outcome=initial_action_outcome,
        )
    )
    return {
        "result": result,
        "graph_phases": _append_graph_phase(
            state.get("graph_phases"),
            "runtime_loop",
            started_at,
            started_timer,
        ),
    }


def _observation_from_dict(payload: Dict[str, Any]) -> AgentObservation:
    return AgentObservation(
        action_id=str(payload.get("action_id", "")),
        tool=str(payload.get("tool", "")),
        status=str(payload.get("status", "failed")),
        output=(
            dict(payload["output"])
            if isinstance(payload.get("output"), dict)
            else {}
        ),
        error_code=str(payload.get("error_code", "")),
        error=str(payload.get("error", "")),
        started_at=str(payload.get("started_at", "")),
        completed_at=str(payload.get("completed_at", "")),
        duration_seconds=str(payload.get("duration_seconds", "0.0000")),
    )


def _runtime_finalize_graph_node(state: RuntimeGraphState) -> RuntimeGraphState:
    started_at = _utc_timestamp()
    started_timer = time.perf_counter()
    result = state.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("runtime loop did not return a result")
    result["runtime_engine"] = "langgraph"
    result["graph_phases"] = _append_graph_phase(
        state.get("graph_phases"),
        "finalize",
        started_at,
        started_timer,
    )
    return {"result": result}


def _run_runtime_agent_loop(
    goal: str,
    *,
    provider: Any,
    run_id: str = "",
    cancellation_token: Optional[RuntimeCancellationToken] = None,
    steering_buffer: Optional[RuntimeSteeringBuffer] = None,
    policy: Optional[RuntimePolicy] = None,
    tools: Optional[Dict[str, RuntimeToolSpec]] = None,
    max_iterations: int = 1,
    approved_action_ids: Optional[Set[str]] = None,
    metadata: Optional[Dict[str, str]] = None,
    tags: Optional[List[str]] = None,
    event_sink: Optional[RuntimeEventSink] = None,
    hooks: Optional[List[Any]] = None,
    runtime_workspace_dir: str = "",
    redis_url: str = "",
    milvus_url: str = "",
    embedding_base_url: str = "",
    embedding_api_key: str = "",
    embedding_model: str = "",
    embedding_timeout_seconds: float = 30.0,
    embedding_max_retries: int = 2,
    embedding_retry_backoff_seconds: float = 0.25,
    external_backend_timeout_seconds: float = 2.0,
    stream_answers: bool = False,
    initial_planner: Dict[str, Any] | None = None,
    initial_events: List[Dict[str, Any]] | None = None,
    initial_progress_events: List[Dict[str, Any]] | None = None,
    initial_progress_event_sink_failure_count: int = 0,
    initial_hook_failure_count: int = 0,
    started_at: str = "",
    run_start_hook_completed: bool = False,
    initial_action_outcome: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if max_iterations < 1:
        raise ValueError("max_iterations must be at least 1")
    normalized_metadata, metadata_error = validate_runtime_metadata(metadata)
    if metadata_error:
        raise ValueError(metadata_error)
    normalized_tags, tags_error = validate_runtime_tags(tags)
    if tags_error:
        raise ValueError(tags_error)
    run_id = run_id.strip() or str(uuid4())
    original_goal = goal
    events = list(initial_events or [])
    started_at = started_at or _utc_timestamp()
    started_timer = time.perf_counter()
    active_policy = policy or RuntimePolicy()

    def delegate_child(child_goal: str, child_max_iterations: int) -> Dict[str, Any]:
        return run_runtime_agent(
            child_goal,
            provider=provider,
            cancellation_token=cancellation_token,
            policy=active_policy,
            tools=default_runtime_tools(
                runtime_workspace_dir=runtime_workspace_dir,
                redis_url=redis_url,
                milvus_url=milvus_url,
                embedding_base_url=embedding_base_url,
                embedding_api_key=embedding_api_key,
                embedding_model=embedding_model,
                embedding_timeout_seconds=embedding_timeout_seconds,
                embedding_max_retries=embedding_max_retries,
                embedding_retry_backoff_seconds=embedding_retry_backoff_seconds,
                external_backend_timeout_seconds=external_backend_timeout_seconds,
                include_delegate_tool=False,
            ),
            max_iterations=child_max_iterations,
            metadata=normalized_metadata,
            tags=normalized_tags,
            runtime_workspace_dir=runtime_workspace_dir,
            redis_url=redis_url,
            milvus_url=milvus_url,
            embedding_base_url=embedding_base_url,
            embedding_api_key=embedding_api_key,
            embedding_model=embedding_model,
            embedding_timeout_seconds=embedding_timeout_seconds,
            embedding_max_retries=embedding_max_retries,
            embedding_retry_backoff_seconds=embedding_retry_backoff_seconds,
            external_backend_timeout_seconds=external_backend_timeout_seconds,
        )

    active_tools = tools or default_runtime_tools(
        runtime_workspace_dir=runtime_workspace_dir,
        redis_url=redis_url,
        milvus_url=milvus_url,
        embedding_base_url=embedding_base_url,
        embedding_api_key=embedding_api_key,
        embedding_model=embedding_model,
        embedding_timeout_seconds=embedding_timeout_seconds,
        embedding_max_retries=embedding_max_retries,
        embedding_retry_backoff_seconds=embedding_retry_backoff_seconds,
        external_backend_timeout_seconds=external_backend_timeout_seconds,
        delegate_runner=delegate_child,
    )
    active_approvals = set(approved_action_ids or set())
    consumed_approved_action_ids: Set[str] = set()
    status = "done"
    observations: List[AgentObservation] = []
    plans: List[Dict[str, Any]] = []
    latest_plan = {"actions": []}
    answer = ""
    final_answer_guardrail: Dict[str, str] = {}
    pending_approval: Dict[str, Any] = {}
    terminal_error_code = ""
    terminal_error = ""
    cancelled_at = ""
    cancel_reason = ""
    iteration_count = 0
    progress_events: List[Dict[str, Any]] = list(initial_progress_events or [])
    progress_event_sink_failure_count = initial_progress_event_sink_failure_count
    hook_failure_count = initial_hook_failure_count
    answer_streamed = bool(
        initial_planner and initial_planner.get("answer_streamed")
    )
    steering_applied_count = 0
    steering_iteration_budget_added = 0
    hook_chain = RuntimeHookChain(hooks or [])
    context_manager = RuntimeContextManager(
        max_string_chars=MAX_PLANNER_OBSERVATION_STRING_CHARS
    )
    initial_action_observation: AgentObservation | None = None
    if initial_action_outcome is not None:
        observation_payload = initial_action_outcome.get("observation")
        if isinstance(observation_payload, dict):
            initial_action_observation = _observation_from_dict(observation_payload)
            observations.append(initial_action_observation)

    def emit_progress(event: Dict[str, Any]) -> None:
        nonlocal progress_event_sink_failure_count
        event_with_run_id = {"run_id": run_id, **event}
        progress_events.append(event_with_run_id)
        if event_sink is not None:
            try:
                event_sink(event_with_run_id)
            except Exception:
                progress_event_sink_failure_count += 1

    def mark_cancelled() -> bool:
        nonlocal status, terminal_error_code, terminal_error
        nonlocal cancelled_at, cancel_reason
        if cancellation_token is None or not cancellation_token.is_cancelled():
            return False
        if status == "cancelled":
            return True
        token_snapshot = cancellation_token.snapshot()
        cancelled_at = token_snapshot["cancelled_at"] or _utc_timestamp()
        cancel_reason = token_snapshot["reason"]
        status = "cancelled"
        terminal_error_code = "run_cancelled"
        terminal_error = cancel_reason or "runtime run cancelled"
        event: Dict[str, Any] = {
            "node": "control",
            "status": "cancelled",
            "started_at": cancelled_at,
            "completed_at": cancelled_at,
            "duration_seconds": "0.0000",
        }
        if cancel_reason:
            event["reason"] = cancel_reason
        events.append(event)
        _emit_runtime_progress(
            emit_progress,
            "run_cancelled",
            node="control",
            status="cancelled",
            reason=cancel_reason,
        )
        return True

    def apply_pending_steering(boundary: str, iteration: str) -> bool:
        nonlocal goal, steering_applied_count
        if (
            steering_buffer is None
            or steering_applied_count >= MAX_STEERING_APPLIED_PER_RUN
        ):
            return False
        instruction, revision = steering_buffer.consume()
        if not instruction:
            return False
        goal = f"{goal}\n\nAdditional user instruction:\n{instruction}"
        steering_applied_count += 1
        timestamp = _utc_timestamp()
        events.append(
            {
                "node": "control",
                "status": "applied",
                "boundary": boundary,
                "iteration": iteration,
                "revision": revision,
                "started_at": timestamp,
                "completed_at": timestamp,
                "duration_seconds": "0.0000",
            }
        )
        _emit_runtime_progress(
            emit_progress,
            "steering_applied",
            node="control",
            status="applied",
            boundary=boundary,
            iteration=iteration,
            revision=revision,
        )
        return True

    def record_hook_failure(
        *,
        stage: str,
        exc: Exception,
        started_at: str,
        timer: float,
        iteration: str = "",
        action_id: str = "",
        tool: str = "",
        dependency_metadata: Dict[str, str] | None = None,
    ) -> None:
        nonlocal hook_failure_count
        hook_failure_count += 1
        event: Dict[str, Any] = {
            "node": "hook",
            "stage": stage,
            "status": "failed",
            "error_code": "runtime_hook_failed",
            "error": str(exc),
            **_timing_fields(started_at, timer),
        }
        if iteration:
            event["iteration"] = iteration
        if action_id:
            event["action_id"] = action_id
        if tool:
            event["tool"] = tool
        if dependency_metadata:
            event.update(dependency_metadata)
        events.append(event)

    if hook_chain and not run_start_hook_completed:
        hook_started_at = _utc_timestamp()
        hook_timer = time.perf_counter()
        try:
            hook_chain.on_run_start(
                {
                    "run_id": run_id,
                    "goal": goal,
                    "started_at": started_at,
                    "metadata": normalized_metadata,
                    "tags": normalized_tags,
                }
            )
        except Exception as exc:
            record_hook_failure(
                stage="on_run_start",
                exc=exc,
                started_at=hook_started_at,
                timer=hook_timer,
            )

    iteration_limit = max_iterations
    iteration = 0
    while iteration < iteration_limit:
        iteration += 1
        if mark_cancelled():
            break
        iteration_count = iteration
        iteration_label = str(iteration)
        use_initial_planner = iteration == 1 and initial_planner is not None
        if use_initial_planner:
            planner_status = str(initial_planner.get("status", ""))
            if planner_status == "cancelled":
                status = "cancelled"
                terminal_error_code = "run_cancelled"
                terminal_error = "runtime run cancelled"
                cancelled_at = _utc_timestamp()
                break
            planner_started_at = str(
                initial_planner.get("started_at", _utc_timestamp())
            )
            timing = {
                "completed_at": str(
                    initial_planner.get("completed_at", _utc_timestamp())
                ),
                "duration_seconds": str(
                    initial_planner.get("duration_seconds", "0.0000")
                ),
            }
            if planner_status == "failed":
                planner_error_code = str(
                    initial_planner.get("error_code", "invalid_plan")
                )
                planner_error = str(initial_planner.get("error", "planner failed"))
                observations.append(
                    AgentObservation(
                        action_id="",
                        tool="planner",
                        status="failed",
                        output={},
                        error_code=planner_error_code,
                        error=planner_error,
                        started_at=planner_started_at,
                        completed_at=timing["completed_at"],
                        duration_seconds=timing["duration_seconds"],
                    )
                )
                if iteration < iteration_limit:
                    continue
                status = "failed"
                break
            plan_payload = initial_planner.get("plan")
            if not isinstance(plan_payload, dict):
                raise RuntimeError("planner checkpoint is missing plan state")
            try:
                plan = parse_agent_plan(json.dumps(plan_payload, ensure_ascii=False))
                _require_final_answer_for_empty_actions(plan)
            except Exception as exc:
                planner_error_code = _planner_failure_error_code(exc)
                observations.append(
                    AgentObservation(
                        action_id="",
                        tool="planner",
                        status="failed",
                        output={},
                        error_code=planner_error_code,
                        error=str(exc),
                        started_at=planner_started_at,
                        completed_at=timing["completed_at"],
                        duration_seconds=timing["duration_seconds"],
                    )
                )
                if iteration < iteration_limit:
                    continue
                status = "failed"
                break
        else:
            user_prompt = _runtime_user_prompt(
                goal,
                active_tools,
                observations,
                context_manager=context_manager,
            )
            planner_started_at = _utc_timestamp()
            planner_timer = time.perf_counter()
            events.append(
                {
                    "node": "planner",
                    "status": "started",
                    "iteration": iteration_label,
                    "started_at": planner_started_at,
                }
            )
            _emit_runtime_progress(
                emit_progress,
                "planner_started",
                iteration=iteration_label,
                node="planner",
                status="started",
            )
            try:
                plan_text, streamed_this_plan = _complete_plan_text(
                    provider,
                    _SYSTEM_PROMPT,
                    user_prompt,
                    emit_progress=emit_progress,
                    stream_answer=(
                        stream_answers
                        and not observations
                        and not _is_runtime_identity_question(goal.lower())
                        and not _is_runtime_deployment_question(goal.lower())
                    ),
                )
                if mark_cancelled():
                    break
                answer_streamed = answer_streamed or streamed_this_plan
                plan = parse_agent_plan(plan_text)
                _require_final_answer_for_empty_actions(plan)
            except Exception as exc:
                if mark_cancelled():
                    break
                planner_error_code = _planner_failure_error_code(exc)
                timing = _timing_fields(planner_started_at, planner_timer)
                events[-1] = {
                    "node": "planner",
                    "status": "failed",
                    "iteration": iteration_label,
                    **timing,
                }
                observations.append(
                    AgentObservation(
                        action_id="",
                        tool="planner",
                        status="failed",
                        output={},
                        error_code=planner_error_code,
                        error=str(exc),
                        started_at=planner_started_at,
                        completed_at=timing["completed_at"],
                        duration_seconds=timing["duration_seconds"],
                    )
                )
                _emit_runtime_progress(
                    emit_progress,
                    "planner_failed",
                    iteration=iteration_label,
                    node="planner",
                    status="failed",
                    error_code=planner_error_code,
                    duration_seconds=timing["duration_seconds"],
                )
                if iteration < iteration_limit:
                    continue
                status = "failed"
                break
            events[-1] = {
                "node": "planner",
                "status": "ok",
                "action_count": str(len(plan.actions)),
                "iteration": iteration_label,
                **_timing_fields(planner_started_at, planner_timer),
            }
            _emit_runtime_progress(
                emit_progress,
                "planner_completed",
                iteration=iteration_label,
                node="planner",
                status="ok",
                action_count=str(len(plan.actions)),
                duration_seconds=events[-1]["duration_seconds"],
            )
        latest_plan = plan.to_dict()
        plans.append(latest_plan)
        if apply_pending_steering("after_planner", iteration_label):
            if steering_iteration_budget_added < MAX_STEERING_APPLIED_PER_RUN:
                iteration_limit += 1
                steering_iteration_budget_added += 1
            continue
        if not plan.actions:
            if _latest_observation_blocks_empty_final_answer(observations):
                status = "failed"
                final_answer_guardrail = _final_answer_guardrail(
                    "unresolved_failure_boundary"
                )
                break
            if plan.final_answer:
                answer, final_answer_guardrail = _runtime_final_answer(
                    goal,
                    plan.final_answer,
                )
            break

        should_replan = False
        iteration_observations: Dict[str, AgentObservation] = {}
        actions_to_execute = plan.actions
        if iteration == 1 and initial_action_outcome is not None:
            outcome_status = str(initial_action_outcome.get("status", "failed"))
            if (
                initial_action_observation is not None
                and initial_action_observation.action_id
            ):
                iteration_observations[initial_action_observation.action_id] = (
                    initial_action_observation
                )
            actions_to_execute = []
            if outcome_status == "cancelled":
                status = "cancelled"
                terminal_error_code = "run_cancelled"
                terminal_error = "runtime run cancelled"
                cancelled_at = _utc_timestamp()
            elif outcome_status != "ok":
                if initial_action_outcome.get("should_replan"):
                    should_replan = True
                else:
                    status = "failed"
        for action_index, action in enumerate(actions_to_execute):
            if mark_cancelled():
                break
            dependency_metadata = _action_dependency_event_metadata(
                action.depends_on,
                iteration_observations,
            )
            resolution_started_at = _utc_timestamp()
            resolution_timer = time.perf_counter()
            try:
                resolved_input = _resolve_dependency_input(
                    action.input,
                    action.depends_on,
                    iteration_observations,
                )
            except ValueError as exc:
                resolution_timing = _timing_fields(
                    resolution_started_at,
                    resolution_timer,
                )
                observation = AgentObservation(
                    action_id=action.id,
                    tool=action.tool,
                    status="failed",
                    output={},
                    error_code="dependency_resolution_failed",
                    error=str(exc),
                    started_at=resolution_started_at,
                    completed_at=resolution_timing["completed_at"],
                    duration_seconds=resolution_timing["duration_seconds"],
                )
                observations.append(observation)
                iteration_observations[action.id] = observation
                events.append(
                    {
                        "node": "executor",
                        "action_id": action.id,
                        "tool": action.tool,
                        "status": "failed",
                        "iteration": iteration_label,
                        **dependency_metadata,
                        **resolution_timing,
                    }
                )
                _emit_runtime_progress(
                    emit_progress,
                    "tool_completed",
                    iteration=iteration_label,
                    node="executor",
                    action_id=action.id,
                    tool=action.tool,
                    status="failed",
                    error_code="dependency_resolution_failed",
                    duration_seconds=resolution_timing["duration_seconds"],
                )
                status = "failed"
                break
            policy_started_at = _utc_timestamp()
            policy_timer = time.perf_counter()
            decision = active_policy.authorize(action.tool, resolved_input)
            approved_by_id = decision.status != "allowed" and action.id in active_approvals
            if approved_by_id:
                consumed_approved_action_ids.add(action.id)
            policy_status = (
                "approved"
                if approved_by_id
                else decision.status
            )
            events.append(
                {
                    "node": "policy",
                    "action_id": action.id,
                    "tool": action.tool,
                    "status": policy_status,
                    "reason": decision.reason,
                    "iteration": iteration_label,
                    **dependency_metadata,
                    **_timing_fields(policy_started_at, policy_timer),
                }
            )
            _emit_runtime_progress(
                emit_progress,
                "policy_completed",
                iteration=iteration_label,
                node="policy",
                action_id=action.id,
                tool=action.tool,
                status=policy_status,
                reason=decision.reason,
                duration_seconds=events[-1]["duration_seconds"],
            )
            if decision.status != "allowed" and action.id not in active_approvals:
                latest_plan["actions"][action_index]["input"] = copy.deepcopy(
                    resolved_input
                )
                materialization_failure: tuple[Any, ValueError] | None = None
                for later_index in range(action_index + 1, len(plan.actions)):
                    later_action = plan.actions[later_index]
                    try:
                        latest_plan["actions"][later_index]["input"] = (
                            _materialize_available_dependency_input(
                                later_action.input,
                                iteration_observations,
                            )
                        )
                    except ValueError as exc:
                        materialization_failure = (later_action, exc)
                        break
                if materialization_failure is not None:
                    failed_action, failure = materialization_failure
                    failure_started_at = _utc_timestamp()
                    failure_timing = _timing_fields(
                        failure_started_at,
                        time.perf_counter(),
                    )
                    failure_observation = AgentObservation(
                        action_id=failed_action.id,
                        tool=failed_action.tool,
                        status="failed",
                        output={},
                        error_code="dependency_resolution_failed",
                        error=str(failure),
                        started_at=failure_started_at,
                        completed_at=failure_timing["completed_at"],
                        duration_seconds=failure_timing["duration_seconds"],
                    )
                    observations.append(failure_observation)
                    events.append(
                        {
                            "node": "executor",
                            "action_id": failed_action.id,
                            "tool": failed_action.tool,
                            "status": "failed",
                            "iteration": iteration_label,
                            **_action_dependency_event_metadata(
                                failed_action.depends_on,
                                iteration_observations,
                            ),
                            **failure_timing,
                        }
                    )
                    status = "failed"
                    break
                pending_approval = {**action.to_dict(), "input": resolved_input}
                approval_started_at = _utc_timestamp()
                approval_timer = time.perf_counter()
                observations.append(
                    AgentObservation(
                        action_id=action.id,
                        tool=action.tool,
                        status="requires_approval",
                        output={},
                        error_code=decision.reason or "policy_denied",
                        error="tool execution requires approval",
                        started_at=approval_started_at,
                        completed_at=_utc_timestamp(),
                        duration_seconds=_duration_since(approval_timer),
                    )
                )
                _emit_runtime_progress(
                    emit_progress,
                    "approval_required",
                    iteration=iteration_label,
                    node="policy",
                    action_id=action.id,
                    tool=action.tool,
                    status="requires_approval",
                    reason=decision.reason or "policy_denied",
                )
                status = "requires_approval"
                break
            if hook_chain:
                hook_started_at = _utc_timestamp()
                hook_timer = time.perf_counter()
                try:
                    hook_decision = hook_chain.before_tool(
                        {
                            "run_id": run_id,
                            "goal": goal,
                            "iteration": iteration_label,
                            "action_id": action.id,
                            "tool": action.tool,
                            "input": resolved_input,
                            "reason": action.reason,
                            **dependency_metadata,
                        }
                    )
                except Exception as exc:
                    hook_timing = _timing_fields(hook_started_at, hook_timer)
                    record_hook_failure(
                        stage="before_tool",
                        exc=exc,
                        started_at=hook_started_at,
                        timer=hook_timer,
                        iteration=iteration_label,
                        action_id=action.id,
                        tool=action.tool,
                        dependency_metadata=dependency_metadata,
                    )
                    observations.append(
                        AgentObservation(
                            action_id=action.id,
                            tool=action.tool,
                            status="failed",
                            output={},
                            error_code="runtime_hook_failed",
                            error=str(exc),
                            started_at=hook_started_at,
                            completed_at=hook_timing["completed_at"],
                            duration_seconds=hook_timing["duration_seconds"],
                        )
                    )
                    status = "failed"
                    break
                hook_timing = _timing_fields(hook_started_at, hook_timer)
                events.append(
                    {
                        "node": "hook",
                        "action_id": action.id,
                        "tool": action.tool,
                        "status": hook_decision.status,
                        "reason": hook_decision.reason,
                        "iteration": iteration_label,
                        **dependency_metadata,
                        **hook_timing,
                    }
                )
                if hook_decision.status == "denied":
                    observations.append(
                        AgentObservation(
                            action_id=action.id,
                            tool=action.tool,
                            status="failed",
                            output={},
                            error_code="runtime_hook_denied",
                            error=hook_decision.reason,
                            started_at=hook_started_at,
                            completed_at=hook_timing["completed_at"],
                            duration_seconds=hook_timing["duration_seconds"],
                        )
                    )
                    status = "failed"
                    break
            if mark_cancelled():
                break
            start_presentation = project_runtime_start_presentation(
                action.tool,
                resolved_input,
            )
            _emit_runtime_progress(
                emit_progress,
                "tool_started",
                iteration=iteration_label,
                node="executor",
                action_id=action.id,
                tool=action.tool,
                status="started",
                presentation=start_presentation or None,
            )
            observation = execute_runtime_tool(
                active_tools,
                action.tool,
                resolved_input,
                action_id=action.id,
            )
            observations.append(observation)
            iteration_observations[action.id] = observation
            cancelled_after_tool = mark_cancelled()
            if hook_chain:
                hook_started_at = _utc_timestamp()
                hook_timer = time.perf_counter()
                try:
                    hook_chain.after_tool(
                        {
                            "run_id": run_id,
                            "goal": goal,
                            "iteration": iteration_label,
                            "action_id": action.id,
                            "tool": action.tool,
                            "input": resolved_input,
                            "observation": observation.to_dict(),
                            **dependency_metadata,
                        }
                    )
                except Exception as exc:
                    record_hook_failure(
                        stage="after_tool",
                        exc=exc,
                        started_at=hook_started_at,
                        timer=hook_timer,
                        iteration=iteration_label,
                        action_id=action.id,
                        tool=action.tool,
                        dependency_metadata=dependency_metadata,
                    )
            events.append(
                {
                    "node": "executor",
                    "action_id": action.id,
                    "tool": action.tool,
                    "status": observation.status,
                    "iteration": iteration_label,
                    **dependency_metadata,
                    "started_at": observation.started_at,
                    "completed_at": observation.completed_at,
                    "duration_seconds": observation.duration_seconds,
                }
            )
            presentation = project_runtime_presentation(
                action.tool,
                observation.status,
                observation.output,
            )
            _emit_runtime_progress(
                emit_progress,
                "tool_completed",
                iteration=iteration_label,
                node="executor",
                action_id=action.id,
                tool=action.tool,
                status=observation.status,
                error_code=observation.error_code,
                duration_seconds=observation.duration_seconds,
                presentation=presentation or None,
            )
            if cancelled_after_tool:
                break
            if apply_pending_steering("after_tool", iteration_label):
                if steering_iteration_budget_added < MAX_STEERING_APPLIED_PER_RUN:
                    iteration_limit += 1
                    steering_iteration_budget_added += 1
                should_replan = True
                break
            if observation.status != "ok":
                if iteration < iteration_limit:
                    should_replan = True
                else:
                    status = "failed"
                break
        if should_replan:
            continue
        if status != "done":
            break
        approved_action_completed = any(
            observation.status == "ok"
            and observation.action_id in active_approvals
            for observation in observations
        )
        if plan.final_answer or (
            iteration >= iteration_limit and approved_action_completed
        ):
            final_text, streamed_final = _complete_post_tool_answer(
                provider,
                goal,
                observations,
                context_manager=context_manager,
                emit_progress=emit_progress,
                stream_answer=stream_answers,
            )
            answer_streamed = answer_streamed or streamed_final
            answer, final_answer_guardrail = _runtime_final_answer(
                goal,
                final_text,
            )
            break
        if iteration >= iteration_limit:
            status = "failed"
            terminal_error_code = "iteration_budget_exhausted"
            terminal_error = (
                "iteration budget exhausted before the planner returned a final answer"
            )
            break

    result = {
        "trace_type": RUNTIME_TRACE_TYPE,
        "run_id": run_id,
        "status": status,
        "goal": original_goal,
        "started_at": started_at,
        "completed_at": _utc_timestamp(),
        "duration_seconds": _duration_since(started_timer),
        "iteration_count": str(iteration_count),
        "max_iterations": str(max_iterations),
        "iteration_budget_remaining": str(max(0, max_iterations - iteration_count)),
        "steering_applied_count": str(steering_applied_count),
        "steering_iteration_budget_added": str(steering_iteration_budget_added),
        "prompt_observation_compaction": context_manager.report(),
        "approved_action_count": str(len(consumed_approved_action_ids)),
        "approved_action_ids": sorted(consumed_approved_action_ids),
        "events": events,
        "progress_events": progress_events,
        "plan": latest_plan,
        "plans": plans,
        "observations": [observation.to_dict() for observation in observations],
    }
    result["steps"] = derive_runtime_steps(result)
    if answer:
        result["answer"] = answer
    if answer_streamed and answer:
        result["answer_streamed"] = "true"
    if normalized_metadata:
        result["metadata"] = normalized_metadata
    if normalized_tags:
        result["tags"] = normalized_tags
    provider_request = _llm_provider_request_diagnostics(provider)
    if provider_request:
        result["llm_provider_request"] = provider_request
    if final_answer_guardrail:
        result["final_answer_guardrail"] = final_answer_guardrail
    if pending_approval:
        result["pending_approval"] = pending_approval
    failed_observation = _last_failed_observation(observations)
    if status == "failed" and failed_observation is not None:
        result["error_code"] = failed_observation.error_code
        result["error"] = failed_observation.error
    elif status == "failed" and terminal_error_code:
        result["error_code"] = terminal_error_code
        result["error"] = terminal_error
    elif status == "cancelled":
        result["error_code"] = terminal_error_code
        result["error"] = terminal_error
        result["cancelled_at"] = cancelled_at or result["completed_at"]
        if cancel_reason:
            result["cancel_reason"] = cancel_reason
    _emit_runtime_progress(
        emit_progress,
        "run_completed",
        node="run",
        status=status,
        iteration_count=str(iteration_count),
        duration_seconds=result["duration_seconds"],
    )
    if progress_event_sink_failure_count:
        result["progress_event_sink_failure_count"] = str(
            progress_event_sink_failure_count
        )
    if hook_chain:
        hook_started_at = _utc_timestamp()
        hook_timer = time.perf_counter()
        try:
            hook_chain.on_run_end(
                {
                    "run_id": run_id,
                    "goal": goal,
                    "status": status,
                    "completed_at": result["completed_at"],
                    "duration_seconds": result["duration_seconds"],
                    "iteration_count": result["iteration_count"],
                }
            )
        except Exception as exc:
            record_hook_failure(
                stage="on_run_end",
                exc=exc,
                started_at=hook_started_at,
                timer=hook_timer,
            )
    if hook_failure_count:
        result["hook_failure_count"] = str(hook_failure_count)
    return redact_runtime_payload(result)


def _complete_plan_text(
    provider: Any,
    system_prompt: str,
    user_prompt: str,
    *,
    emit_progress: Callable[..., None],
    stream_answer: bool,
) -> tuple[str, bool]:
    stream_complete = getattr(provider, "stream_complete", None)
    if not stream_answer or not callable(stream_complete):
        return str(provider.complete(system_prompt, user_prompt)), False

    chunks: List[str] = []
    streamer = _DirectFinalAnswerStreamer(emit_progress)
    for chunk in stream_complete(system_prompt, user_prompt):
        text = str(chunk)
        chunks.append(text)
        streamer.feed(text)
    plan_text = "".join(chunks)
    return plan_text, streamer.finish()


def _complete_post_tool_answer(
    provider: Any,
    goal: str,
    observations: List[AgentObservation],
    *,
    context_manager: RuntimeContextManager,
    emit_progress: Callable[..., None],
    stream_answer: bool,
) -> tuple[str, bool]:
    current_goal = _current_user_message(goal)
    user_prompt = (
        "Goal:\n"
        + current_goal
        + "\n\nPrevious observations:\n"
        + json.dumps(
            [
                _planner_observation_payload(
                    observation,
                    context_manager=context_manager,
                )
                for observation in observations
            ],
            sort_keys=True,
        )
    )
    try:
        response_text = str(
            provider.complete(_FINAL_RESPONSE_SYSTEM_PROMPT, user_prompt)
        ).strip()
    except Exception:
        response_text = ""
    if response_text:
        try:
            response_plan = parse_agent_plan(response_text)
        except ValueError:
            final_text = ""
        else:
            final_text = (
                ""
                if response_plan.actions
                else response_plan.final_answer.strip()
            )
    else:
        final_text = ""
    if not final_text:
        final_text = _fallback_post_tool_answer(
            current_goal,
            observations,
            context_manager=context_manager,
        )
    if stream_answer:
        _emit_runtime_progress(
            emit_progress,
            "answer_started",
            node="finalizer",
            status="started",
        )
        _emit_runtime_progress(
            emit_progress,
            "answer_delta",
            node="finalizer",
            status="streaming",
            delta=final_text,
        )
        _emit_runtime_progress(
            emit_progress,
            "answer_completed",
            node="finalizer",
            status="done",
        )
    return final_text, stream_answer


def _fallback_post_tool_answer(
    goal: str,
    observations: List[AgentObservation],
    *,
    context_manager: RuntimeContextManager,
) -> str:
    chinese = re.search(r"[\u3400-\u9fff]", goal) is not None
    visible = [item for item in observations if item.status == "ok"] or observations
    tools = "、".join(item.tool for item in visible)
    results = [
        _observation_summary_result(
            observation,
            context_manager=context_manager,
        )
        for observation in visible
    ]
    if len(visible) == 1 and visible[0].tool == "note":
        return results[0]
    if len(visible) == 1:
        if chinese:
            return f"问题：{goal}\n执行：{tools}\n结果：{results[0]}"
        return f"Problem: {goal}\nAction: {tools}\nResult: {results[0]}"
    if chinese:
        lines = [f"问题：{goal}", f"执行：{tools}", "结果："]
    else:
        lines = [f"Problem: {goal}", f"Actions: {tools}", "Results:"]
    lines.extend(
        f"- {observation.tool}: {result}"
        for observation, result in zip(visible, results)
    )
    return "\n".join(lines)


def _observation_summary_result(
    observation: AgentObservation,
    *,
    context_manager: RuntimeContextManager,
) -> str:
    if observation.status != "ok":
        return observation.error or observation.error_code or observation.status
    presentation = project_runtime_presentation(
        observation.tool,
        observation.status,
        observation.output,
    )
    content = str(presentation.get("content", "")).strip()
    if content:
        return content
    for key in ("text", "body_text", "content", "stdout"):
        value = observation.output.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    detail = str(presentation.get("detail", "")).strip()
    if detail:
        return detail
    compacted = context_manager.compact_observation_output(observation.output)
    return json.dumps(compacted, ensure_ascii=False, sort_keys=True)


class _DirectFinalAnswerStreamer:
    _EMPTY_ACTIONS_RE = re.compile(r'"actions"\s*:\s*\[\s*\]')
    _FINAL_ANSWER_RE = re.compile(r'"final_answer"\s*:\s*"')

    def __init__(self, emit_progress: Callable[..., None]) -> None:
        self._emit_progress = emit_progress
        self._buffer = ""
        self._answer_start: int | None = None
        self._scan_index = 0
        self._started = False
        self._completed = False
        self._escape = False

    def feed(self, text: str) -> None:
        if self._completed:
            return
        self._buffer += text
        if self._answer_start is None:
            if not self._EMPTY_ACTIONS_RE.search(self._buffer):
                return
            answer_match = self._FINAL_ANSWER_RE.search(self._buffer)
            if answer_match is None:
                return
            self._answer_start = answer_match.end()
            self._scan_index = self._answer_start
        self._emit_available_answer()

    def finish(self) -> bool:
        if self._started and not self._completed:
            self._completed = True
            _emit_runtime_progress(
                self._emit_progress,
                "answer_completed",
                node="planner",
                status="done",
            )
        return self._started

    def _emit_available_answer(self) -> None:
        pieces: List[str] = []
        while self._scan_index < len(self._buffer):
            char = self._buffer[self._scan_index]
            self._scan_index += 1
            if self._escape:
                decoded = _decode_streamed_json_escape(char)
                if decoded is None:
                    continue
                pieces.append(decoded)
                self._escape = False
                continue
            if char == "\\":
                self._escape = True
                continue
            if char == '"':
                self._completed = True
                break
            pieces.append(char)
        if pieces:
            self._emit_delta("".join(pieces))
        if self._completed and self._started:
            _emit_runtime_progress(
                self._emit_progress,
                "answer_completed",
                node="planner",
                status="done",
            )

    def _emit_delta(self, delta: str) -> None:
        if not self._started:
            self._started = True
            _emit_runtime_progress(
                self._emit_progress,
                "answer_started",
                node="planner",
                status="started",
            )
        _emit_runtime_progress(
            self._emit_progress,
            "answer_delta",
            node="planner",
            status="streaming",
            delta=delta,
        )


def _decode_streamed_json_escape(char: str) -> str | None:
    escapes = {
        '"': '"',
        "\\": "\\",
        "/": "/",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
    }
    if char == "u":
        return None
    return escapes.get(char, char)


def _runtime_user_prompt(
    goal: str,
    tools: Dict[str, RuntimeToolSpec],
    observations: List[AgentObservation],
    *,
    context_manager: RuntimeContextManager,
) -> str:
    tool_payload = runtime_tool_metadata(tools)
    prompt = "Goal:\n" + goal + "\n\nAvailable tools:\n" + json.dumps(
        tool_payload,
        sort_keys=True,
    )
    if observations:
        prompt += "\n\nPrevious observations:\n" + json.dumps(
            [
                _planner_observation_payload(
                    observation,
                    context_manager=context_manager,
                )
                for observation in observations
            ],
            sort_keys=True,
        )
    return prompt


def _runtime_final_answer(goal: str, final_answer: str) -> tuple[str, Dict[str, str]]:
    goal_text = _current_user_message(goal).lower()
    answer_text = final_answer.lower()
    if _is_runtime_identity_question(goal_text) and _looks_like_model_identity(answer_text):
        return _runtime_identity_answer(), _final_answer_guardrail(
            "runtime_identity_boundary"
        )
    if _is_runtime_deployment_question(goal_text) and _looks_like_model_deployment(answer_text):
        return _runtime_deployment_answer(), _final_answer_guardrail(
            "runtime_deployment_boundary"
        )
    return final_answer, {}


def _current_user_message(goal: str) -> str:
    marker = "Current user message:\n"
    if marker not in goal:
        return goal
    current = goal.rsplit(marker, 1)[1].strip()
    return current or goal


def _final_answer_guardrail(reason: str) -> Dict[str, str]:
    return {
        "applied": "true",
        "reason": reason,
        "original_answer_omitted": "true",
    }


def _is_runtime_identity_question(goal_text: str) -> bool:
    identity_markers = (
        "你是谁",
        "你是什么",
        "你叫",
        "who are you",
        "what are you",
    )
    return any(marker in goal_text for marker in identity_markers)


def _is_runtime_deployment_question(goal_text: str) -> bool:
    deployment_markers = (
        "部署在哪",
        "部署在哪里",
        "运行在哪",
        "运行在哪里",
        "在哪里运行",
        "where are you deployed",
        "where do you run",
        "where are you running",
    )
    return any(marker in goal_text for marker in deployment_markers)


def _looks_like_model_identity(answer_text: str) -> bool:
    provider_markers = (
        "qwen",
        "通义千问",
        "阿里云研发",
        "阿里巴巴",
        "chatgpt",
        "openai",
        "claude",
        "anthropic",
        "gemini",
    )
    return any(marker in answer_text for marker in provider_markers)


def _looks_like_model_deployment(answer_text: str) -> bool:
    provider_deployment_markers = (
        "阿里云服务器",
        "阿里云",
        "云服务器",
        "model provider",
        "provider server",
        "openai servers",
        "anthropic servers",
    )
    return any(marker in answer_text for marker in provider_deployment_markers)


def _runtime_identity_answer() -> str:
    return (
        "我是 kagent，你的本地或内部自动化助手。"
        "我可以理解你的目标、规划步骤、调用已允许的工具，并把过程和结果整理给你。"
    )


def _runtime_deployment_answer() -> str:
    return (
        "我运行在你启动的终端或服务进程里。"
        "具体位置取决于你的运行环境，比如本机、容器、服务器或公司内部平台。"
    )


def _planner_observation_payload(
    observation: AgentObservation,
    *,
    context_manager: RuntimeContextManager,
) -> Dict[str, Any]:
    payload = observation.to_dict()
    payload["output"] = context_manager.compact_observation_output(
        payload.get("output")
    )
    return payload


def _action_dependency_event_metadata(
    depends_on: List[str],
    observations_by_action_id: Dict[str, AgentObservation],
) -> Dict[str, Any]:
    if not depends_on:
        return {}
    return {
        "depends_on": depends_on,
        "dependency_statuses": {
            action_id: observations_by_action_id[action_id].status
            for action_id in depends_on
            if action_id in observations_by_action_id
        },
    }


def _resolve_dependency_input(
    value: Any,
    depends_on: List[str],
    observations_by_action_id: Dict[str, AgentObservation],
) -> Dict[str, Any]:
    reference_count = [0]
    resolved = _resolve_dependency_value(
        value,
        set(depends_on),
        observations_by_action_id,
        reference_count=reference_count,
        depth=0,
    )
    if not isinstance(resolved, dict):
        raise ValueError("action input must resolve to an object")
    return resolved


def _materialize_available_dependency_input(
    value: Any,
    observations_by_action_id: Dict[str, AgentObservation],
) -> Any:
    if isinstance(value, list):
        return [
            _materialize_available_dependency_input(
                item,
                observations_by_action_id,
            )
            for item in value
        ]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    if "$from_action" in value:
        action_id = value["$from_action"]
        observation = observations_by_action_id.get(action_id)
        if observation is None:
            return copy.deepcopy(value)
        if observation.status != "ok":
            raise ValueError(f"dependency did not complete successfully: {action_id}")
        return copy.deepcopy(
            _resolve_json_pointer(
                observation.output,
                value["pointer"],
                action_id=action_id,
            )
        )
    return {
        key: _materialize_available_dependency_input(
            item,
            observations_by_action_id,
        )
        for key, item in value.items()
    }


def _resolve_dependency_value(
    value: Any,
    declared_dependencies: Set[str],
    observations_by_action_id: Dict[str, AgentObservation],
    *,
    reference_count: List[int],
    depth: int,
) -> Any:
    if depth > 20:
        raise ValueError("dependency input nesting exceeds 20 levels")
    if isinstance(value, list):
        return [
            _resolve_dependency_value(
                item,
                declared_dependencies,
                observations_by_action_id,
                reference_count=reference_count,
                depth=depth + 1,
            )
            for item in value
        ]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    if "$from_action" in value:
        if set(value) != {"$from_action", "pointer"}:
            raise ValueError(
                "dependency reference must contain only $from_action and pointer"
            )
        reference_count[0] += 1
        if reference_count[0] > 50:
            raise ValueError("action input contains more than 50 dependency references")
        action_id = value.get("$from_action")
        pointer = value.get("pointer")
        if not isinstance(action_id, str) or action_id not in declared_dependencies:
            raise ValueError("dependency reference must name a declared dependency")
        if not isinstance(pointer, str):
            raise ValueError("dependency reference pointer must be a string")
        observation = observations_by_action_id.get(action_id)
        if observation is None or observation.status != "ok":
            raise ValueError(f"dependency did not complete successfully: {action_id}")
        return copy.deepcopy(
            _resolve_json_pointer(observation.output, pointer, action_id=action_id)
        )
    return {
        key: _resolve_dependency_value(
            item,
            declared_dependencies,
            observations_by_action_id,
            reference_count=reference_count,
            depth=depth + 1,
        )
        for key, item in value.items()
    }


def _resolve_json_pointer(value: Any, pointer: str, *, action_id: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise ValueError("dependency reference pointer must be empty or start with /")
    current = value
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if index < len(current):
                current = current[index]
                continue
        raise ValueError(
            f"dependency pointer does not exist: {action_id}{pointer}"
        )
    return current


def _last_failed_observation(
    observations: List[AgentObservation],
) -> AgentObservation | None:
    for observation in reversed(observations):
        if observation.status == "failed":
            return observation
    return None


def _latest_observation_failed(observations: List[AgentObservation]) -> bool:
    return bool(observations and observations[-1].status == "failed")


def _latest_observation_blocks_empty_final_answer(
    observations: List[AgentObservation],
) -> bool:
    if not _latest_observation_failed(observations):
        return False
    latest = observations[-1]
    return not (latest.tool == "planner" and latest.error_code == "invalid_plan")


def _planner_failure_error_code(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "llm_provider_error"
    message = str(exc).lower()
    if message.startswith("llm provider "):
        return "llm_provider_error"
    if "llm provider request failed" in message:
        return "llm_provider_error"
    return "invalid_plan"


def _require_final_answer_for_empty_actions(plan: Any) -> None:
    if not plan.actions and not plan.final_answer:
        raise ValueError("final_answer is required when actions is empty")


def _llm_provider_request_diagnostics(provider: Any) -> Dict[str, str]:
    diagnostics_fn = getattr(provider, "request_diagnostics", None)
    if not callable(diagnostics_fn):
        return {}
    try:
        diagnostics = diagnostics_fn()
    except Exception:
        return {}
    if not isinstance(diagnostics, dict):
        return {}
    allowed_fields = {
        "attempt_count",
        "retry_count",
        "status",
        "stream",
        "duration_seconds",
        "error_type",
        "http_status",
        "retryable_reason",
    }
    return {
        key: str(diagnostics[key])
        for key in sorted(allowed_fields)
        if str(diagnostics.get(key, "")).strip()
    }


def _emit_runtime_progress(
    event_sink: Optional[RuntimeEventSink],
    event_type: str,
    **fields: Any,
) -> None:
    if event_sink is None:
        return
    payload = {"type": event_type}
    payload.update(
        {
            key: value
            for key, value in fields.items()
            if not _is_empty_progress_field(value)
        }
    )
    if event_type == "tool_started" and "presentation" in fields:
        payload["presentation"] = fields["presentation"]
    event_sink(payload)


def _is_empty_progress_field(value: Any) -> bool:
    return value is None or value == ""
