from __future__ import annotations

import json
from hashlib import sha256
from typing import Any, Dict, Tuple

from self_correcting_langgraph_agent.runtime import RUNTIME_TRACE_TYPE
from self_correcting_langgraph_agent.runtime.policy import RuntimePolicy
from self_correcting_langgraph_agent.runtime.tools import default_runtime_tools
from self_correcting_langgraph_agent.service.runtime import ServiceConfig
from self_correcting_langgraph_agent.utils.json_output import json_ready


def execute_runtime_policy_request(
    service_config: ServiceConfig,
    *,
    request_auth_subject: str = "",
    request_auth_is_admin: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    default_allowed_tools = _sorted_tuple(RuntimePolicy().allowed_tools)
    global_allowed_tools = _sorted_tuple(service_config.runtime_allowed_tools)
    subject_allowed_tools = _subject_allowed_tools(
        service_config,
        request_auth_subject=request_auth_subject,
        request_auth_is_admin=request_auth_is_admin,
    )
    effective_allowed_tools, effective_policy_source = _effective_policy(
        service_config,
        request_auth_subject=request_auth_subject,
        default_allowed_tools=default_allowed_tools,
        global_allowed_tools=global_allowed_tools,
    )
    effective_tool_policy = _effective_tool_policy(effective_allowed_tools)
    return 200, json_ready(
        {
            "trace_type": RUNTIME_TRACE_TYPE,
            "auth_subject": request_auth_subject,
            "is_admin": str(request_auth_is_admin).lower(),
            "default_allowed_tools": list(default_allowed_tools),
            "global_allowed_tools": list(global_allowed_tools),
            "subject_policy_count": str(
                len(service_config.runtime_allowed_tools_by_subject)
            ),
            "subject_allowed_tools": subject_allowed_tools,
            "effective_allowed_tools": list(effective_allowed_tools),
            "effective_policy_source": effective_policy_source,
            "effective_tool_policy": effective_tool_policy,
            "effective_tool_policy_sha256": _policy_sha256(
                effective_tool_policy
            ),
        }
    )


def _subject_allowed_tools(
    service_config: ServiceConfig,
    *,
    request_auth_subject: str,
    request_auth_is_admin: bool,
) -> Dict[str, list[str]]:
    subjects = service_config.runtime_allowed_tools_by_subject
    if request_auth_is_admin:
        return {
            subject: list(_sorted_tuple(tools))
            for subject, tools in sorted(subjects.items())
        }
    if request_auth_subject in subjects:
        return {
            request_auth_subject: list(
                _sorted_tuple(subjects[request_auth_subject])
            )
        }
    return {}


def _effective_policy(
    service_config: ServiceConfig,
    *,
    request_auth_subject: str,
    default_allowed_tools: tuple[str, ...],
    global_allowed_tools: tuple[str, ...],
) -> tuple[tuple[str, ...], str]:
    subject_allowed_tools = service_config.runtime_allowed_tools_by_subject.get(
        request_auth_subject,
    )
    if subject_allowed_tools is not None:
        return _sorted_tuple(subject_allowed_tools), "subject"
    if global_allowed_tools:
        return global_allowed_tools, "global"
    return default_allowed_tools, "default"


def _sorted_tuple(values: Any) -> tuple[str, ...]:
    if not values:
        return ()
    return tuple(sorted(str(value) for value in values if str(value).strip()))


def _effective_tool_policy(
    effective_allowed_tools: tuple[str, ...],
) -> list[dict[str, str]]:
    allowed_tools = set(effective_allowed_tools)
    return [
        {
            "name": name,
            "allowed": str(name in allowed_tools).lower(),
            "approval_required": str(name not in allowed_tools).lower(),
        }
        for name in sorted(default_runtime_tools())
    ]


def _policy_sha256(policy: list[dict[str, str]]) -> str:
    payload = json.dumps(policy, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()
