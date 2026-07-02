from __future__ import annotations

import json
from concurrent.futures import TimeoutError
from typing import Any, Dict, Tuple

from self_correcting_langgraph_agent.providers.llm import (
    FakeLLMProvider,
    LLMProviderConfig,
    OpenAICompatibleProvider,
    SequentialFakeLLMProvider,
)
from self_correcting_langgraph_agent.runtime import run_runtime_agent
from self_correcting_langgraph_agent.runtime.policy import RuntimePolicy
from self_correcting_langgraph_agent.service import errors as service_errors
from self_correcting_langgraph_agent.service.errors import failure_payload
from self_correcting_langgraph_agent.service.run import run_with_timeout
from self_correcting_langgraph_agent.service.runtime import ServiceConfig
from self_correcting_langgraph_agent.service.runtime_approval import (
    validate_approved_action_ids,
)
from self_correcting_langgraph_agent.service.runtime_metadata import (
    validate_runtime_metadata,
    validate_runtime_tags,
)
from self_correcting_langgraph_agent.service.trace_store import persist_trace
from self_correcting_langgraph_agent.utils.json_output import json_ready


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
            provider = OpenAICompatibleProvider(LLMProviderConfig.from_env())
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
