from __future__ import annotations

import json
from concurrent.futures import TimeoutError
from typing import Any, Dict, Tuple
from uuid import uuid4

from kagent.integrations.audit import KafkaRestAuditHook, KafkaRestProgressEventSink
from kagent.providers.llm import (
    FakeLLMProvider,
    LLMProviderConfig,
    OpenAICompatibleProvider,
    SequentialFakeLLMProvider,
)
from kagent.runtime import RuntimeCancellationToken, run_runtime_agent
from kagent.runtime.policy import RuntimePolicy
from kagent.service import errors as service_errors
from kagent.service.active_runs import ActiveRunRegistry, ExecutionSlotLease
from kagent.service.errors import failure_payload
from kagent.service.run import run_with_timeout
from kagent.service.runtime import ServiceConfig
from kagent.service.runtime_approval import (
    validate_approved_action_ids,
)
from kagent.service.runtime_lifecycle import (
    persist_cancelled_runtime_trace,
    persist_failed_runtime_trace,
    persist_runtime_worker_result,
    persisted_runtime_cancellation_probe,
    running_runtime_trace,
)
from kagent.service.runtime_metadata import (
    validate_runtime_metadata,
    validate_runtime_tags,
)
from kagent.service.trace_store import persist_trace
from kagent.utils.json_output import json_ready


def execute_runtime_run_request(
    body: bytes,
    _service_config: ServiceConfig,
    auth_subject: str = "",
    *,
    active_run_registry: ActiveRunRegistry | None = None,
    execution_slot_lease: ExecutionSlotLease | None = None,
) -> Tuple[int, Dict[str, Any]]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return 400, failure_payload(service_errors.INVALID_JSON, f"invalid JSON: {exc}")
    if not isinstance(payload, dict):
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "request body must be a JSON object",
        )
    goal = str(payload.get("goal", ""))
    if not goal.strip():
        return 400, failure_payload(service_errors.MISSING_GOAL, "goal is required")
    if len(goal) > _service_config.max_goal_chars:
        return 413, failure_payload(
            service_errors.GOAL_TOO_LARGE,
            "goal exceeds max_goal_chars",
        )
    max_iterations = payload.get("max_iterations", 1)
    if (
        not isinstance(max_iterations, int)
        or isinstance(max_iterations, bool)
        or max_iterations < 1
    ):
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "max_iterations must be an integer greater than or equal to 1",
        )
    if max_iterations > _service_config.runtime_max_iterations:
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "max_iterations exceeds runtime_max_iterations",
        )
    approved_action_ids_payload = payload.get("approved_action_ids", [])
    approved_action_ids, approval_error = validate_approved_action_ids(
        approved_action_ids_payload
    )
    if approval_error:
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            approval_error,
        )
    metadata, metadata_error = validate_runtime_metadata(payload.get("metadata"))
    if metadata_error:
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            metadata_error,
        )
    tags, tags_error = validate_runtime_tags(payload.get("tags"))
    if tags_error:
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            tags_error,
        )
    plan_payload = payload.get("plan")
    plan_sequence_payload = payload.get("plan_sequence")
    if plan_payload is not None and plan_sequence_payload is not None:
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "plan and plan_sequence are mutually exclusive",
        )
    if approved_action_ids and plan_payload is None and plan_sequence_payload is None:
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "approved_action_ids require plan or plan_sequence; use /runtime/resume "
            "to approve live provider actions",
        )
    planned_action_ids = _planned_action_ids(plan_payload, plan_sequence_payload)
    if approved_action_ids and planned_action_ids is not None:
        missing_approved_ids = [
            action_id
            for action_id in approved_action_ids
            if action_id not in planned_action_ids
        ]
        if missing_approved_ids:
            return 400, failure_payload(
                service_errors.INVALID_REQUEST_BODY,
                "approved_action_ids must reference planned action ids: "
                + ", ".join(missing_approved_ids),
            )
    if plan_payload is not None:
        if not isinstance(plan_payload, dict):
            return 400, failure_payload(
                service_errors.INVALID_REQUEST_BODY,
                "plan must be a JSON object",
            )
        provider = FakeLLMProvider(json.dumps(plan_payload, sort_keys=True))
    elif plan_sequence_payload is not None:
        if not isinstance(plan_sequence_payload, list) or not plan_sequence_payload:
            return 400, failure_payload(
                service_errors.INVALID_REQUEST_BODY,
                "plan_sequence must be a non-empty array of JSON objects",
            )
        if any(not isinstance(item, dict) for item in plan_sequence_payload):
            return 400, failure_payload(
                service_errors.INVALID_REQUEST_BODY,
                "plan_sequence must be a non-empty array of JSON objects",
            )
        provider = SequentialFakeLLMProvider(
            [json.dumps(item, sort_keys=True) for item in plan_sequence_payload]
        )
    else:
        try:
            provider = OpenAICompatibleProvider(LLMProviderConfig.from_sources())
        except ValueError as exc:
            return 400, failure_payload(service_errors.INVALID_AGENT_CONFIG, str(exc))
    allowed_tools = _service_config.runtime_allowed_tools_for_subject(auth_subject)
    policy = (
        RuntimePolicy(allowed_tools=set(allowed_tools))
        if allowed_tools is not None
        else RuntimePolicy()
    )
    run_id = str(uuid4())
    cancellation_token = RuntimeCancellationToken(
        external_cancellation_probe=(
            lambda: persisted_runtime_cancellation_probe(
                run_id=run_id,
                trace_dir=_service_config.trace_dir,
            )
            if _service_config.trace_dir
            else None
        )
    )
    registry = active_run_registry or ActiveRunRegistry()
    trace_path = ""
    if _service_config.trace_dir:
        initial_trace = running_runtime_trace(
            run_id=run_id,
            goal=goal,
            max_iterations=max_iterations,
            auth_subject=auth_subject,
            runtime_instance_id=registry.instance_id,
        )
        try:
            trace_path = persist_trace(initial_trace, _service_config.trace_dir)
        except OSError as exc:
            return 500, failure_payload(
                service_errors.TRACE_PERSISTENCE_FAILED,
                f"could not persist trace: {exc}",
            )
    release_worker_slot = (
        execution_slot_lease.transfer() if execution_slot_lease is not None else None
    )
    try:
        registry.register(
            run_id,
            auth_subject,
            cancellation_token,
            release=release_worker_slot,
        )
    except Exception:
        if release_worker_slot is not None:
            release_worker_slot()
        raise

    def execute_runtime_worker() -> Dict[str, Any]:
        try:
            result = run_runtime_agent(
                goal,
                provider=provider,
                run_id=run_id,
                cancellation_token=cancellation_token,
                policy=policy,
                max_iterations=max_iterations,
                approved_action_ids=set(approved_action_ids),
                metadata=metadata,
                tags=tags,
                event_sink=_runtime_event_sink(_service_config),
                hooks=_runtime_hooks(_service_config),
                runtime_workspace_dir=_service_config.runtime_workspace_dir,
                redis_url=_service_config.redis_url,
                milvus_url=_service_config.milvus_url,
                embedding_base_url=_service_config.embedding_base_url,
                embedding_api_key=_service_config.embedding_api_key,
                embedding_model=_service_config.embedding_model,
                embedding_timeout_seconds=_service_config.embedding_timeout_seconds,
                embedding_max_retries=_service_config.embedding_max_retries,
                embedding_retry_backoff_seconds=(
                    _service_config.embedding_retry_backoff_seconds
                ),
                external_backend_timeout_seconds=(
                    _service_config.external_backend_timeout_seconds
                ),
            )
            result["run_id"] = run_id
            if auth_subject:
                result["auth_subject"] = auth_subject
            if _service_config.trace_dir:
                result = persist_runtime_worker_result(
                    run_id=run_id,
                    trace_dir=_service_config.trace_dir,
                    result=result,
                    persist_trace_fn=persist_trace,
                )
            return result
        except Exception as exc:
            if _service_config.trace_dir:
                try:
                    persist_failed_runtime_trace(
                        run_id=run_id,
                        trace_dir=_service_config.trace_dir,
                        error_code=service_errors.AGENT_RUN_FAILED,
                        error=f"agent run failed: {exc}",
                    )
                except (OSError, ValueError):
                    pass
            raise

    def cancel_timed_out_worker() -> None:
        active_run = registry.mark_timed_out(
            run_id,
            reason="runtime run timed out",
        )
        if active_run is None or not _service_config.trace_dir:
            return
        try:
            persist_cancelled_runtime_trace(
                run_id=run_id,
                trace_dir=_service_config.trace_dir,
                active_run=active_run,
                error_code=service_errors.AGENT_RUN_TIMEOUT,
                error="agent run timed out",
            )
        except (OSError, ValueError):
            return

    try:
        result = run_with_timeout(
            execute_runtime_worker,
            timeout_seconds=_service_config.run_timeout_seconds,
            on_timeout=cancel_timed_out_worker,
            on_complete=lambda: registry.complete(run_id),
        )
    except TimeoutError:
        timeout_payload = failure_payload(
            service_errors.AGENT_RUN_TIMEOUT,
            "agent run timed out",
        )
        timeout_payload["run_id"] = run_id
        if trace_path:
            timeout_payload["trace_path"] = trace_path
        return 504, timeout_payload
    except Exception:
        failure = failure_payload(service_errors.AGENT_RUN_FAILED, "agent run failed")
        failure["run_id"] = run_id
        if trace_path:
            failure["trace_path"] = trace_path
        return 500, failure
    return 200, json_ready(result)


def _runtime_hooks(config: ServiceConfig) -> list[Any]:
    hooks: list[Any] = []
    if config.kafka_audit_url:
        hooks.append(
            KafkaRestAuditHook(
                url=config.kafka_audit_url,
                topic=config.kafka_audit_topic,
                timeout_seconds=config.external_backend_timeout_seconds,
            )
        )
    return hooks


def _runtime_event_sink(config: ServiceConfig):
    if not config.kafka_audit_url:
        return None
    return KafkaRestProgressEventSink(
        url=config.kafka_audit_url,
        topic=config.kafka_audit_topic,
        timeout_seconds=config.external_backend_timeout_seconds,
        fail_closed=True,
    )


def _planned_action_ids(
    plan_payload: Any,
    plan_sequence_payload: Any,
) -> set[str] | None:
    plan_payloads = []
    if isinstance(plan_payload, dict):
        plan_payloads.append(plan_payload)
    if isinstance(plan_sequence_payload, list):
        plan_payloads.extend(
            item for item in plan_sequence_payload if isinstance(item, dict)
        )
    if not plan_payloads:
        return None
    action_ids = set()
    inspected_actions = False
    for item in plan_payloads:
        actions = item.get("actions")
        if not isinstance(actions, list):
            continue
        inspected_actions = True
        for action in actions:
            if not isinstance(action, dict):
                continue
            action_id = action.get("id")
            if isinstance(action_id, str) and action_id.strip() == action_id:
                action_ids.add(action_id)
    if not inspected_actions:
        return None
    return action_ids
