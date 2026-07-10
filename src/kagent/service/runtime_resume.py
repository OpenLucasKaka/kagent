from __future__ import annotations

import json
from concurrent.futures import TimeoutError
from datetime import datetime, timezone
from typing import Any, Dict, Tuple
from uuid import uuid4

from kagent.integrations.audit import KafkaRestProgressEventSink
from kagent.providers.llm import FakeLLMProvider
from kagent.runtime import (
    RuntimeCancellationToken,
    build_resumable_plan,
    run_runtime_agent,
)
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
    running_runtime_trace,
)
from kagent.service.runtime_resume_claim import (
    RuntimeResumeClaimConflict,
    claim_runtime_resume,
    complete_runtime_resume_claim,
    release_runtime_resume_claim,
)
from kagent.service.runtime_status import is_runtime_trace
from kagent.service.trace_store import (
    load_trace_by_run_id,
    persist_trace,
)
from kagent.utils.json_output import json_ready

_TRACE_READ_ERRORS = (OSError, ValueError)


def execute_runtime_resume_request(
    body: bytes,
    service_config: ServiceConfig,
    auth_subject: str = "",
    *,
    request_auth_is_admin: bool = False,
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
    if not service_config.trace_dir:
        return 400, failure_payload(
            service_errors.INVALID_AGENT_CONFIG,
            "trace_dir is required for runtime resume",
        )
    run_id = str(payload.get("run_id", ""))
    if not run_id.strip():
        return 400, failure_payload(service_errors.INVALID_REQUEST_BODY, "run_id is required")
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
    if max_iterations > service_config.runtime_max_iterations:
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

    try:
        previous_trace = load_trace_by_run_id(run_id, service_config.trace_dir)
    except _TRACE_READ_ERRORS:
        return 500, failure_payload(
            service_errors.TRACE_READ_FAILED,
            "runtime run trace could not be read",
        )
    if previous_trace is None or not is_runtime_trace(previous_trace):
        return 404, failure_payload(service_errors.NOT_FOUND, "runtime run trace not found")
    previous_auth_subject = str(previous_trace.get("auth_subject", ""))
    owner_auth_subject = previous_auth_subject or auth_subject
    if (
        auth_subject
        and not request_auth_is_admin
        and owner_auth_subject != auth_subject
    ):
        return 404, failure_payload(service_errors.NOT_FOUND, "runtime run trace not found")
    previous_status = str(previous_trace.get("status", ""))
    if previous_status in {"resuming", "resumed"}:
        return 409, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "runtime run approval is already being resumed",
        )
    if previous_status != "requires_approval" or not isinstance(
        previous_trace.get("pending_approval"),
        dict,
    ):
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "runtime run is not waiting for approval",
        )
    pending_approval = previous_trace["pending_approval"]
    pending_action_id = str(pending_approval.get("id", ""))
    if not pending_action_id.strip():
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "runtime run trace is missing pending approval action id",
        )
    if pending_action_id not in approved_action_ids:
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "approved_action_ids must include the pending approval action id",
        )
    if any(action_id != pending_action_id for action_id in approved_action_ids):
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "approved_action_ids must contain only the pending approval action id",
        )
    goal = str(previous_trace.get("goal", ""))
    plan = previous_trace.get("plan")
    if not goal.strip() or not isinstance(plan, dict):
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "runtime run trace is missing resumable plan state",
        )
    resumable_plan = build_resumable_plan(plan, pending_approval)
    if resumable_plan is None:
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "runtime run trace is missing pending approval action plan",
        )

    registry = active_run_registry or ActiveRunRegistry()
    resumed_run_id = str(uuid4())
    claim_id = str(uuid4())
    try:
        claim_runtime_resume(
            trace_dir=service_config.trace_dir,
            run_id=run_id,
            pending_action_id=pending_action_id,
            claim_id=claim_id,
            resumed_run_id=resumed_run_id,
            claimed_by_auth_subject=auth_subject,
            runtime_instance_id=registry.instance_id,
        )
    except RuntimeResumeClaimConflict as exc:
        return 409, failure_payload(service_errors.INVALID_REQUEST_BODY, str(exc))
    except (OSError, ValueError) as exc:
        return 500, failure_payload(
            service_errors.TRACE_PERSISTENCE_FAILED,
            f"could not claim runtime approval: {exc}",
        )

    cancellation_token = RuntimeCancellationToken()
    approved_at = _utc_timestamp()
    initial_trace = running_runtime_trace(
        run_id=resumed_run_id,
        goal=goal,
        max_iterations=max_iterations,
        auth_subject=owner_auth_subject,
        resumed_from_run_id=run_id,
        runtime_instance_id=registry.instance_id,
    )
    initial_trace["approved_at"] = approved_at
    if auth_subject:
        initial_trace["resumed_by_auth_subject"] = auth_subject
        initial_trace["approved_by_auth_subject"] = auth_subject
    if isinstance(previous_trace.get("metadata"), dict):
        initial_trace["metadata"] = dict(previous_trace["metadata"])
    if isinstance(previous_trace.get("tags"), list):
        initial_trace["tags"] = list(previous_trace["tags"])

    trace_path = ""
    release_worker_slot = None
    try:
        trace_path = persist_trace(initial_trace, service_config.trace_dir)
        allowed_tools = service_config.runtime_allowed_tools_for_subject(owner_auth_subject)
        policy = (
            RuntimePolicy(allowed_tools=set(allowed_tools))
            if allowed_tools is not None
            else RuntimePolicy()
        )
        release_worker_slot = (
            execution_slot_lease.transfer()
            if execution_slot_lease is not None
            else None
        )
        registry.register(
            resumed_run_id,
            owner_auth_subject,
            cancellation_token,
            release=release_worker_slot,
        )
    except (OSError, ValueError) as exc:
        if release_worker_slot is not None:
            release_worker_slot()
        try:
            release_runtime_resume_claim(
                trace_dir=service_config.trace_dir,
                run_id=run_id,
                claim_id=claim_id,
            )
        except (OSError, ValueError):
            pass
        return 500, failure_payload(
            service_errors.TRACE_PERSISTENCE_FAILED,
            f"could not initialize resumed runtime run: {exc}",
        )
    except Exception:
        if release_worker_slot is not None:
            release_worker_slot()
        try:
            release_runtime_resume_claim(
                trace_dir=service_config.trace_dir,
                run_id=run_id,
                claim_id=claim_id,
            )
        except (OSError, ValueError):
            pass
        return 500, failure_payload(service_errors.AGENT_RUN_FAILED, "agent run failed")

    def execute_runtime_worker() -> Dict[str, Any]:
        try:
            result = run_runtime_agent(
                goal,
                provider=FakeLLMProvider(json.dumps(resumable_plan, sort_keys=True)),
                run_id=resumed_run_id,
                cancellation_token=cancellation_token,
                policy=policy,
                max_iterations=max_iterations,
                event_sink=_runtime_event_sink(service_config),
                approved_action_ids=set(approved_action_ids),
                runtime_workspace_dir=service_config.runtime_workspace_dir,
                redis_url=service_config.redis_url,
                milvus_url=service_config.milvus_url,
                embedding_base_url=service_config.embedding_base_url,
                embedding_api_key=service_config.embedding_api_key,
                embedding_model=service_config.embedding_model,
                embedding_timeout_seconds=service_config.embedding_timeout_seconds,
                embedding_max_retries=service_config.embedding_max_retries,
                embedding_retry_backoff_seconds=(
                    service_config.embedding_retry_backoff_seconds
                ),
                external_backend_timeout_seconds=(
                    service_config.external_backend_timeout_seconds
                ),
            )
            result["run_id"] = resumed_run_id
            if owner_auth_subject:
                result["auth_subject"] = owner_auth_subject
            if auth_subject:
                result["resumed_by_auth_subject"] = auth_subject
                result["approved_by_auth_subject"] = auth_subject
            result["approved_at"] = approved_at
            if isinstance(previous_trace.get("metadata"), dict):
                result["metadata"] = dict(previous_trace["metadata"])
            if isinstance(previous_trace.get("tags"), list):
                result["tags"] = list(previous_trace["tags"])
            result["resumed_from_run_id"] = run_id
            if registry.result_may_persist(resumed_run_id):
                result["trace_path"] = persist_trace(result, service_config.trace_dir)
            elif trace_path:
                result["trace_path"] = trace_path
            return result
        except Exception as exc:
            if registry.result_may_persist(resumed_run_id):
                try:
                    persist_failed_runtime_trace(
                        run_id=resumed_run_id,
                        trace_dir=service_config.trace_dir,
                        error_code=service_errors.AGENT_RUN_FAILED,
                        error=f"agent run failed: {exc}",
                    )
                except (OSError, ValueError):
                    pass
            raise

    def cancel_timed_out_worker() -> None:
        active_run = registry.mark_timed_out(
            resumed_run_id,
            reason="runtime run timed out",
        )
        if active_run is None:
            return
        try:
            persist_cancelled_runtime_trace(
                run_id=resumed_run_id,
                trace_dir=service_config.trace_dir,
                active_run=active_run,
                error_code=service_errors.AGENT_RUN_TIMEOUT,
                error="agent run timed out",
            )
        except (OSError, ValueError):
            pass

    def complete_resumed_worker() -> None:
        try:
            complete_runtime_resume_claim(
                trace_dir=service_config.trace_dir,
                run_id=run_id,
                claim_id=claim_id,
                resumed_run_id=resumed_run_id,
            )
        except (OSError, ValueError):
            pass
        finally:
            registry.complete(resumed_run_id)

    try:
        result = run_with_timeout(
            execute_runtime_worker,
            timeout_seconds=service_config.run_timeout_seconds,
            on_timeout=cancel_timed_out_worker,
            on_complete=complete_resumed_worker,
        )
    except TimeoutError:
        timeout_payload = failure_payload(
            service_errors.AGENT_RUN_TIMEOUT,
            "agent run timed out",
        )
        timeout_payload["run_id"] = resumed_run_id
        timeout_payload["resumed_from_run_id"] = run_id
        if trace_path:
            timeout_payload["trace_path"] = trace_path
        return 504, timeout_payload
    except Exception:
        failure = failure_payload(service_errors.AGENT_RUN_FAILED, "agent run failed")
        failure["run_id"] = resumed_run_id
        failure["resumed_from_run_id"] = run_id
        if trace_path:
            failure["trace_path"] = trace_path
        return 500, failure
    return 200, json_ready(result)


def _runtime_event_sink(config: ServiceConfig):
    if not config.kafka_audit_url:
        return None
    return KafkaRestProgressEventSink(
        url=config.kafka_audit_url,
        topic=config.kafka_audit_topic,
        timeout_seconds=config.external_backend_timeout_seconds,
        fail_closed=True,
    )


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
