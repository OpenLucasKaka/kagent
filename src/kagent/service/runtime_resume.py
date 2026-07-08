from __future__ import annotations

import json
from concurrent.futures import TimeoutError
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from kagent.integrations.audit import KafkaRestProgressEventSink
from kagent.providers.llm import FakeLLMProvider
from kagent.runtime import run_runtime_agent
from kagent.runtime.policy import RuntimePolicy
from kagent.service import errors as service_errors
from kagent.service.errors import failure_payload
from kagent.service.run import run_with_timeout
from kagent.service.runtime import ServiceConfig
from kagent.service.runtime_approval import (
    validate_approved_action_ids,
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
    if previous_trace.get("status") != "requires_approval" or not isinstance(
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
    resumable_plan = _pending_approval_plan(plan, pending_approval)
    if resumable_plan is None:
        return 400, failure_payload(
            service_errors.INVALID_REQUEST_BODY,
            "runtime run trace is missing pending approval action plan",
        )

    try:
        allowed_tools = service_config.runtime_allowed_tools_for_subject(owner_auth_subject)
        policy = (
            RuntimePolicy(allowed_tools=set(allowed_tools))
            if allowed_tools is not None
            else RuntimePolicy()
        )
        result = run_with_timeout(
            lambda: run_runtime_agent(
                goal,
                provider=FakeLLMProvider(json.dumps(resumable_plan, sort_keys=True)),
                policy=policy,
                max_iterations=max_iterations,
                event_sink=_runtime_event_sink(service_config),
                approved_action_ids=set(approved_action_ids),
                runtime_workspace_dir=service_config.runtime_workspace_dir,
                redis_url=service_config.redis_url,
                milvus_url=service_config.milvus_url,
                external_backend_timeout_seconds=(
                    service_config.external_backend_timeout_seconds
                ),
            ),
            timeout_seconds=service_config.run_timeout_seconds,
        )
    except TimeoutError:
        return 504, failure_payload(
            service_errors.AGENT_RUN_TIMEOUT,
            "agent run timed out",
        )
    if owner_auth_subject:
        result["auth_subject"] = owner_auth_subject
    if auth_subject:
        result["resumed_by_auth_subject"] = auth_subject
        result["approved_by_auth_subject"] = auth_subject
    result["approved_at"] = _utc_timestamp()
    if isinstance(previous_trace.get("metadata"), dict):
        result["metadata"] = dict(previous_trace["metadata"])
    if isinstance(previous_trace.get("tags"), list):
        result["tags"] = list(previous_trace["tags"])
    result["resumed_from_run_id"] = run_id
    try:
        result["trace_path"] = persist_trace(result, service_config.trace_dir)
    except OSError as exc:
        return 500, failure_payload(
            service_errors.TRACE_PERSISTENCE_FAILED,
            f"could not persist trace: {exc}",
        )
    return 200, json_ready(result)


def _pending_approval_plan(
    plan: Dict[str, Any],
    pending_approval: Dict[str, Any],
) -> Dict[str, Any] | None:
    pending_action_id = str(pending_approval.get("id", ""))
    actions = plan.get("actions")
    if not isinstance(actions, list):
        return None
    matching_actions = [
        action
        for action in actions
        if isinstance(action, dict) and action.get("id") == pending_action_id
    ]
    if len(matching_actions) != 1:
        return None
    matching_action = matching_actions[0]
    if matching_action != pending_approval:
        return None
    pending_action = dict(matching_action)
    # Dependencies from earlier actions were already satisfied in the persisted run.
    pending_action.pop("depends_on", None)
    resumable_plan: Dict[str, Any] = {"actions": [pending_action]}
    final_answer = plan.get("final_answer")
    if isinstance(final_answer, str) and final_answer:
        resumable_plan["final_answer"] = final_answer
    return resumable_plan


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
