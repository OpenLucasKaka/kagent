from __future__ import annotations

import json
import re
import time
import warnings
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, TypedDict
from uuid import uuid4

from kagent.runtime.context import RuntimeContextManager
from kagent.runtime.hooks import RuntimeHookChain
from kagent.runtime.metadata import (
    validate_runtime_metadata,
    validate_runtime_tags,
)
from kagent.runtime.policy import RuntimePolicy
from kagent.runtime.redaction import redact_runtime_payload
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
    "Use optional depends_on with prior action IDs when one action depends on earlier output.\n"
    "Use open_app to open a local macOS application by application name. "
    "Use open_url to open a browser page; use http_request only to fetch URL "
    "content as an observation.\n"
    "Use list_files and read_file to observe workspace state before changing "
    "workspace files with apply_patch.\n"
    "Use delegate_task to hand off a bounded independent subtask to a child "
    "kagent runtime; keep delegated goals specific and self-contained.\n"
    "Use skill_list and skill_get when the task may benefit from installed "
    "runtime skills or reusable operating procedures.\n"
    "Use memory_put and memory_get for configured Redis short-term memory. "
    "Use memory_remember and memory_recall for configured text-based long-term "
    "semantic memory. Use memory_upsert and memory_search only when you have "
    "explicit embedding vectors.\n"
    "Use shell_command for bounded non-interactive local CLI checks; it is "
    "policy-gated and may require explicit approval before execution.\n"
    "If the latest previous observation failed, do not return final_answer with "
    "empty actions; either plan recovery actions or leave the run failed.\n"
    'If the goal is complete, return {"actions":[]}.'
)

RUNTIME_TRACE_TYPE = "codex_runtime"
MAX_PLANNER_OBSERVATION_STRING_CHARS = 500
RuntimeEventSink = Callable[[Dict[str, Any]], None]


class RuntimeGraphState(TypedDict, total=False):
    goal: str
    provider: Any
    policy: RuntimePolicy
    tools: Dict[str, RuntimeToolSpec]
    max_iterations: int
    approved_action_ids: Set[str]
    metadata: Dict[str, str]
    tags: List[str]
    event_sink: RuntimeEventSink
    hooks: List[Any]
    runtime_workspace_dir: str
    redis_url: str
    milvus_url: str
    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str
    embedding_timeout_seconds: float
    external_backend_timeout_seconds: float
    stream_answers: bool
    result: Dict[str, Any]
    graph_phases: List[Dict[str, str]]


def build_runtime_graph():
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

    graph = StateGraph(RuntimeGraphState)
    graph.add_node("prepare", _runtime_prepare_graph_node)
    graph.add_node("runtime_loop", _runtime_loop_graph_node)
    graph.add_node("finalize", _runtime_finalize_graph_node)
    graph.set_entry_point("prepare")
    graph.add_edge("prepare", "runtime_loop")
    graph.add_edge("runtime_loop", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(name="kagent-runtime")


def runtime_topology() -> Dict[str, List[str] | str]:
    return {
        "runtime_engine": "langgraph",
        "entry_point": "prepare",
        "terminal": "END",
        "nodes": ["prepare", "runtime_loop", "finalize"],
        "edges": [
            "prepare -> runtime_loop",
            "runtime_loop -> finalize",
            "finalize -> END",
        ],
        "loop": "runtime_loop handles bounded planner-policy-executor iterations",
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
            "planner",
            "plan_parser",
            "policy",
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
    external_backend_timeout_seconds: float = 2.0,
    stream_answers: bool = False,
) -> Dict[str, Any]:
    graph = build_runtime_graph()
    state: RuntimeGraphState = {
        "goal": goal,
        "provider": provider,
        "max_iterations": max_iterations,
        "runtime_workspace_dir": runtime_workspace_dir,
        "redis_url": redis_url,
        "milvus_url": milvus_url,
        "embedding_base_url": embedding_base_url,
        "embedding_api_key": embedding_api_key,
        "embedding_model": embedding_model,
        "embedding_timeout_seconds": embedding_timeout_seconds,
        "external_backend_timeout_seconds": external_backend_timeout_seconds,
        "stream_answers": stream_answers,
    }
    if policy is not None:
        state["policy"] = policy
    if tools is not None:
        state["tools"] = tools
    if approved_action_ids is not None:
        state["approved_action_ids"] = approved_action_ids
    if metadata is not None:
        state["metadata"] = metadata
    if tags is not None:
        state["tags"] = tags
    if event_sink is not None:
        state["event_sink"] = event_sink
    if hooks is not None:
        state["hooks"] = hooks
    final_state = graph.invoke(state)
    result = final_state.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("runtime graph did not return a result")
    return result


def _runtime_prepare_graph_node(state: RuntimeGraphState) -> RuntimeGraphState:
    started_at = _utc_timestamp()
    started_timer = time.perf_counter()
    if "provider" not in state:
        raise ValueError("provider is required")
    return {
        "graph_phases": _append_graph_phase(
            state.get("graph_phases"),
            "prepare",
            started_at,
            started_timer,
        )
    }


def _runtime_loop_graph_node(state: RuntimeGraphState) -> RuntimeGraphState:
    started_at = _utc_timestamp()
    started_timer = time.perf_counter()
    result = _run_runtime_agent_loop(
        str(state.get("goal", "")),
        provider=state["provider"],
        policy=state.get("policy"),
        tools=state.get("tools"),
        max_iterations=state.get("max_iterations", 1),
        approved_action_ids=state.get("approved_action_ids"),
        metadata=state.get("metadata"),
        tags=state.get("tags"),
        event_sink=state.get("event_sink"),
        hooks=state.get("hooks"),
        runtime_workspace_dir=state.get("runtime_workspace_dir", ""),
        redis_url=state.get("redis_url", ""),
        milvus_url=state.get("milvus_url", ""),
        embedding_base_url=state.get("embedding_base_url", ""),
        embedding_api_key=state.get("embedding_api_key", ""),
        embedding_model=state.get("embedding_model", ""),
        embedding_timeout_seconds=state.get("embedding_timeout_seconds", 30.0),
        external_backend_timeout_seconds=state.get(
            "external_backend_timeout_seconds",
            2.0,
        ),
        stream_answers=state.get("stream_answers", False),
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


def _append_graph_phase(
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
            **_timing_fields(started_at, started_timer),
        },
    ]


def _run_runtime_agent_loop(
    goal: str,
    *,
    provider: Any,
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
    external_backend_timeout_seconds: float = 2.0,
    stream_answers: bool = False,
) -> Dict[str, Any]:
    if max_iterations < 1:
        raise ValueError("max_iterations must be at least 1")
    normalized_metadata, metadata_error = validate_runtime_metadata(metadata)
    if metadata_error:
        raise ValueError(metadata_error)
    normalized_tags, tags_error = validate_runtime_tags(tags)
    if tags_error:
        raise ValueError(tags_error)
    run_id = str(uuid4())
    events = []
    started_at = _utc_timestamp()
    started_timer = time.perf_counter()
    active_policy = policy or RuntimePolicy()

    def delegate_child(child_goal: str, child_max_iterations: int) -> Dict[str, Any]:
        return run_runtime_agent(
            child_goal,
            provider=provider,
            policy=active_policy,
            tools=default_runtime_tools(
                runtime_workspace_dir=runtime_workspace_dir,
                redis_url=redis_url,
                milvus_url=milvus_url,
                embedding_base_url=embedding_base_url,
                embedding_api_key=embedding_api_key,
                embedding_model=embedding_model,
                embedding_timeout_seconds=embedding_timeout_seconds,
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
    iteration_count = 0
    progress_events: List[Dict[str, Any]] = []
    progress_event_sink_failure_count = 0
    answer_streamed = False
    hook_chain = RuntimeHookChain(hooks or [])
    context_manager = RuntimeContextManager(
        max_string_chars=MAX_PLANNER_OBSERVATION_STRING_CHARS
    )

    def emit_progress(event: Dict[str, Any]) -> None:
        nonlocal progress_event_sink_failure_count
        event_with_run_id = {"run_id": run_id, **event}
        progress_events.append(event_with_run_id)
        if event_sink is not None:
            try:
                event_sink(event_with_run_id)
            except Exception:
                progress_event_sink_failure_count += 1

    if hook_chain:
        hook_chain.on_run_start(
            {
                "run_id": run_id,
                "goal": goal,
                "started_at": started_at,
                "metadata": normalized_metadata,
                "tags": normalized_tags,
            }
        )

    for iteration in range(1, max_iterations + 1):
        iteration_count = iteration
        iteration_label = str(iteration)
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
            answer_streamed = answer_streamed or streamed_this_plan
            plan = parse_agent_plan(plan_text)
        except Exception as exc:
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
            if iteration < max_iterations:
                continue
            status = "failed"
            break
        latest_plan = plan.to_dict()
        plans.append(latest_plan)
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
        if not plan.actions:
            if _latest_observation_failed(observations):
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
        for action in plan.actions:
            policy_started_at = _utc_timestamp()
            policy_timer = time.perf_counter()
            decision = active_policy.authorize(action.tool, action.input)
            approved_by_id = decision.status != "allowed" and action.id in active_approvals
            if approved_by_id:
                consumed_approved_action_ids.add(action.id)
            policy_status = (
                "approved"
                if approved_by_id
                else decision.status
            )
            dependency_metadata = _action_dependency_event_metadata(
                action.depends_on,
                iteration_observations,
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
                pending_approval = action.to_dict()
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
                hook_decision = hook_chain.before_tool(
                    {
                        "run_id": run_id,
                        "goal": goal,
                        "iteration": iteration_label,
                        "action_id": action.id,
                        "tool": action.tool,
                        "input": action.input,
                        "reason": action.reason,
                        **dependency_metadata,
                    }
                )
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
            _emit_runtime_progress(
                emit_progress,
                "tool_started",
                iteration=iteration_label,
                node="executor",
                action_id=action.id,
                tool=action.tool,
                status="started",
            )
            observation = execute_runtime_tool(
                active_tools,
                action.tool,
                action.input,
                action_id=action.id,
            )
            observations.append(observation)
            iteration_observations[action.id] = observation
            if hook_chain:
                hook_chain.after_tool(
                    {
                        "run_id": run_id,
                        "goal": goal,
                        "iteration": iteration_label,
                        "action_id": action.id,
                        "tool": action.tool,
                        "input": action.input,
                        "observation": observation.to_dict(),
                        **dependency_metadata,
                    }
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
            )
            if observation.status != "ok":
                if iteration < max_iterations:
                    should_replan = True
                else:
                    status = "failed"
                break
        if should_replan:
            continue
        if status != "done":
            break
        if plan.final_answer:
            answer, final_answer_guardrail = _runtime_final_answer(
                goal,
                plan.final_answer,
            )
            break
        if iteration >= max_iterations:
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
        "goal": goal,
        "started_at": started_at,
        "completed_at": _utc_timestamp(),
        "duration_seconds": _duration_since(started_timer),
        "iteration_count": str(iteration_count),
        "max_iterations": str(max_iterations),
        "iteration_budget_remaining": str(max(0, max_iterations - iteration_count)),
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
    goal_text = goal.lower()
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


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timing_fields(started_at: str, started_timer: float) -> Dict[str, str]:
    return {
        "started_at": started_at,
        "completed_at": _utc_timestamp(),
        "duration_seconds": _duration_since(started_timer),
    }


def _duration_since(started_at: float) -> str:
    return f"{time.perf_counter() - started_at:.4f}"


def _last_failed_observation(
    observations: List[AgentObservation],
) -> AgentObservation | None:
    for observation in reversed(observations):
        if observation.status == "failed":
            return observation
    return None


def _latest_observation_failed(observations: List[AgentObservation]) -> bool:
    return bool(observations and observations[-1].status == "failed")


def _planner_failure_error_code(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "llm_provider_error"
    message = str(exc).lower()
    if message.startswith("llm provider "):
        return "llm_provider_error"
    if "llm provider request failed" in message:
        return "llm_provider_error"
    return "invalid_plan"


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
    event_sink(payload)


def _is_empty_progress_field(value: Any) -> bool:
    return value is None or value == ""
