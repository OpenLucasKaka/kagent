from __future__ import annotations

import json
from concurrent.futures import TimeoutError
from typing import Any, Dict, Tuple

from kagent.integrations.audit import KafkaRestAuditHook
from kagent.providers.llm import (
    FakeLLMProvider,
    LLMProviderConfig,
    OpenAICompatibleProvider,
    SequentialFakeLLMProvider,
)
from kagent.runtime import run_runtime_agent
from kagent.runtime.policy import RuntimePolicy
from kagent.service import errors as service_errors
from kagent.service.errors import failure_payload
from kagent.service.run import run_with_timeout
from kagent.service.runtime import ServiceConfig
from kagent.service.runtime_approval import (
    validate_approved_action_ids,
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
    try:
        allowed_tools = _service_config.runtime_allowed_tools_for_subject(auth_subject)
        policy = (
            RuntimePolicy(allowed_tools=set(allowed_tools))
            if allowed_tools is not None
            else RuntimePolicy()
        )
        result = run_with_timeout(
            lambda: run_runtime_agent(
                goal,
                provider=provider,
                policy=policy,
                max_iterations=max_iterations,
                approved_action_ids=set(approved_action_ids),
                metadata=metadata,
                tags=tags,
                hooks=_runtime_hooks(_service_config),
                runtime_workspace_dir=_service_config.runtime_workspace_dir,
            ),
            timeout_seconds=_service_config.run_timeout_seconds,
        )
    except TimeoutError:
        return 504, failure_payload(
            service_errors.AGENT_RUN_TIMEOUT,
            "agent run timed out",
        )
    if auth_subject:
        result["auth_subject"] = auth_subject
    if _service_config.trace_dir:
        try:
            result["trace_path"] = persist_trace(result, _service_config.trace_dir)
        except OSError as exc:
            return 500, failure_payload(
                service_errors.TRACE_PERSISTENCE_FAILED,
                f"could not persist trace: {exc}",
            )
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
