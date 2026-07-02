from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

from self_correcting_langgraph_agent.providers.llm import LLMProviderConfig
from self_correcting_langgraph_agent.service import transport as service_transport
from self_correcting_langgraph_agent.service.contract import service_openapi
from self_correcting_langgraph_agent.service.errors import READINESS_FAILED
from self_correcting_langgraph_agent.service.runtime import (
    ServiceConfig,
    SqliteServiceIdempotencyCache,
)
from self_correcting_langgraph_agent.service.trace_store import (
    _ensure_owner_only_trace_dir,
    _write_owner_only_temporary_trace,
)


def readiness_payload(config: Optional[ServiceConfig] = None) -> Dict[str, Any]:
    active_config = config or ServiceConfig()
    checks = {
        "agent_config": _readiness_check(
            _check_agent_config,
            "agent_config_unavailable",
        ),
        "openapi": _readiness_check(service_openapi, "openapi_unavailable"),
        "tools": _readiness_check(_check_tools, "tools_unavailable"),
    }
    if active_config.trace_dir:
        checks["trace_persistence"] = _readiness_check(
            lambda: _check_trace_persistence(active_config.trace_dir),
            "trace_persistence_unavailable",
        )
    if active_config.idempotency_cache_path:
        checks["idempotency_cache_persistence"] = _readiness_check(
            lambda: _check_idempotency_cache_persistence(active_config),
            "idempotency_cache_unavailable",
        )
    failed_checks = [name for name, value in checks.items() if value != "ok"]
    status = "ready" if not failed_checks else "not_ready"
    payload = {"status": status, "checks": checks, "failed_checks": failed_checks}
    if failed_checks:
        payload["error_code"] = READINESS_FAILED
    return payload


def service_config_snapshot(config: ServiceConfig) -> Dict[str, str]:
    snapshot = {
        "host": config.host,
        "port": str(config.port),
        "max_request_bytes": str(config.max_request_bytes),
        "max_goal_chars": str(config.max_goal_chars),
        "auth_required": str(config.auth_required).lower(),
        "auth_subject_count": str(
            len(config.auth_tokens) + (1 if config.auth_token else 0)
        ),
        "rate_limit_per_minute": str(config.rate_limit_per_minute),
        "max_concurrent_runs": str(config.max_concurrent_runs),
        "idempotency_cache_size": str(config.idempotency_cache_size),
        "idempotency_cache_backend": (
            "sqlite" if config.idempotency_cache_path else "memory"
        ),
        "idempotency_cache_path_configured": (
            "true" if config.idempotency_cache_path else "false"
        ),
        "runtime_allowed_tools": _runtime_allowed_tools_snapshot(config),
        "runtime_allowed_tools_by_subject_count": str(
            len(config.runtime_allowed_tools_by_subject)
        ),
        "runtime_max_iterations": str(config.runtime_max_iterations),
        "runtime_pending_approval_stale_seconds": str(
            config.runtime_pending_approval_stale_seconds
        ),
        "allow_full_trace_response": str(config.allow_full_trace_response).lower(),
        "protect_diagnostics": str(config.protect_diagnostics).lower(),
        "trust_forwarded_for": str(config.trust_forwarded_for).lower(),
        "run_timeout_seconds": str(config.run_timeout_seconds),
        "request_timeout_seconds": str(config.request_timeout_seconds),
        "trace_persistence": "enabled" if config.trace_dir else "disabled",
    }
    snapshot.update(security_response_header_snapshot())
    snapshot.update(trace_permission_policy_snapshot())
    snapshot.update(llm_provider_snapshot())
    return snapshot


def trace_permission_policy_snapshot() -> Dict[str, str]:
    return {
        "trace_directory_permissions": "0700",
        "trace_file_permissions": "0600",
        "trace_probe_file_permissions": "0600",
    }


def llm_provider_snapshot() -> Dict[str, str]:
    return LLMProviderConfig.from_env().redacted_snapshot()


def security_response_header_snapshot() -> Dict[str, str]:
    return {
        "security_response_headers": "enabled",
        "cache_control_header": service_transport.CACHE_CONTROL_HEADER_VALUE,
        "content_security_policy_header": (
            service_transport.CONTENT_SECURITY_POLICY_HEADER_VALUE
        ),
        "referrer_policy_header": service_transport.REFERRER_POLICY_HEADER_VALUE,
        "x_frame_options_header": service_transport.X_FRAME_OPTIONS_HEADER_VALUE,
        "x_content_type_options_header": service_transport.NOSNIFF_HEADER_VALUE,
    }


def _runtime_allowed_tools_snapshot(config: ServiceConfig) -> str:
    if not config.runtime_allowed_tools:
        return "default"
    return ",".join(config.runtime_allowed_tools)


def _readiness_check(check: Callable[[], None], failure_code: str) -> str:
    try:
        check()
    except Exception:  # pragma: no cover - defensive readiness detail
        return f"failed: {failure_code}"
    return "ok"


def _check_agent_config() -> None:
    from self_correcting_langgraph_agent.core.state import AgentConfig

    AgentConfig()


def _check_tools() -> None:
    from self_correcting_langgraph_agent.core.tools import registered_tool_names

    if not registered_tool_names():
        raise RuntimeError("no tools registered")


def _check_trace_persistence(trace_dir: str) -> None:
    output_dir = Path(trace_dir)
    _ensure_owner_only_trace_dir(output_dir)
    probe_path = _write_owner_only_temporary_trace(
        output_dir,
        f"readiness-{uuid4().hex}.probe",
        "ok\n",
    )
    probe_path.unlink()


def _check_idempotency_cache_persistence(config: ServiceConfig) -> None:
    SqliteServiceIdempotencyCache(
        max_entries=config.idempotency_cache_size,
        database_path=config.idempotency_cache_path,
    ).snapshot()
