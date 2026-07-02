from __future__ import annotations

import time
from typing import Any, Callable, Dict, Mapping, Optional, Tuple
from urllib.parse import urlparse

from self_correcting_langgraph_agent.service import (
    errors as service_errors,
)
from self_correcting_langgraph_agent.service import (
    run as service_run,
)
from self_correcting_langgraph_agent.service import (
    runtime_cancel as service_runtime_cancel,
)
from self_correcting_langgraph_agent.service import (
    runtime_policy as service_runtime_policy,
)
from self_correcting_langgraph_agent.service import (
    runtime_resume as service_runtime_resume,
)
from self_correcting_langgraph_agent.service import (
    runtime_run as service_runtime_run,
)
from self_correcting_langgraph_agent.service import (
    runtime_status as service_runtime_status,
)
from self_correcting_langgraph_agent.service import (
    safety as service_safety,
)
from self_correcting_langgraph_agent.service import (
    status as service_status,
)
from self_correcting_langgraph_agent.service.contract import service_openapi
from self_correcting_langgraph_agent.service.runtime import (
    ServiceConcurrencyLimiter,
    ServiceConfig,
    ServiceIdempotencyCache,
    ServiceMetrics,
    ServiceRateLimiter,
    prometheus_metrics_text,
)


def handle_request(
    method: str,
    path: str,
    body: bytes,
    *,
    headers: Optional[Mapping[str, str]] = None,
    config: Optional[ServiceConfig] = None,
    metrics: Optional[ServiceMetrics] = None,
    rate_limiter: Optional[ServiceRateLimiter] = None,
    concurrency_limiter: Optional[ServiceConcurrencyLimiter] = None,
    idempotency_cache: Optional[ServiceIdempotencyCache] = None,
    remote_addr: str = "",
    agent_runner: Optional[Callable[[str, Any], Dict[str, Any]]] = None,
) -> Tuple[int, Any]:
    active_config = config or ServiceConfig()
    parsed_path = urlparse(path)
    route = parsed_path.path
    active_headers = headers or {}
    if method.upper() == "GET" and route == "/health":
        return 200, {"status": "ok"}
    if method.upper() == "GET" and route == "/ready":
        payload = service_status.readiness_payload(active_config)
        return (200 if payload["status"] == "ready" else 503), payload
    if method.upper() == "GET" and _is_protected_diagnostic_route(route):
        if active_config.protect_diagnostics and not service_safety.authorized(
            active_headers,
            active_config.auth_token,
            active_config.auth_tokens,
        ):
            return 401, service_errors.failure_payload(
                service_errors.UNAUTHORIZED,
                "unauthorized",
            )
    runtime_read_subject = ""
    runtime_read_is_admin = False
    if method.upper() == "GET" and (
        route.startswith("/runtime/approvals")
        or route == "/runtime/policy"
        or route.startswith("/runtime/runs")
    ):
        runtime_read_subject, runtime_read_is_admin = _runtime_read_auth_context(
            active_headers,
            active_config,
        )
    if method.upper() == "GET" and route == "/config":
        return 200, service_status.service_config_snapshot(active_config)
    if method.upper() == "GET" and route == "/version":
        from self_correcting_langgraph_agent import __version__

        return 200, {"version": __version__}
    if method.upper() == "GET" and route == "/tools":
        from self_correcting_langgraph_agent.core.tools import registered_tool_metadata

        return 200, {"tools": registered_tool_metadata()}
    if method.upper() == "GET" and route == "/runtime/tools":
        from self_correcting_langgraph_agent.runtime.tools import (
            registered_runtime_tool_metadata,
        )

        return 200, {"tools": registered_runtime_tool_metadata()}
    if method.upper() == "GET" and route == "/runtime/policy":
        return service_runtime_policy.execute_runtime_policy_request(
            active_config,
            request_auth_subject=runtime_read_subject,
            request_auth_is_admin=runtime_read_is_admin,
        )
    if method.upper() == "GET" and route == "/runtime/approvals/summary":
        return service_runtime_status.execute_runtime_approvals_summary_request(
            parsed_path.query,
            active_config,
            request_auth_subject=runtime_read_subject,
            request_auth_is_admin=runtime_read_is_admin,
        )
    if method.upper() == "GET" and route == "/runtime/approvals":
        return service_runtime_status.execute_runtime_approvals_request(
            parsed_path.query,
            active_config,
            request_auth_subject=runtime_read_subject,
            request_auth_is_admin=runtime_read_is_admin,
        )
    if method.upper() == "GET" and route == "/runtime/runs":
        return service_runtime_status.execute_runtime_list_request(
            parsed_path.query,
            active_config,
            request_auth_subject=runtime_read_subject,
            request_auth_is_admin=runtime_read_is_admin,
        )
    if method.upper() == "GET" and route == "/runtime/runs/summary":
        return service_runtime_status.execute_runtime_summary_request(
            parsed_path.query,
            active_config,
            request_auth_subject=runtime_read_subject,
            request_auth_is_admin=runtime_read_is_admin,
        )
    if method.upper() == "GET" and route.startswith("/runtime/runs/"):
        timeline_run_id = _runtime_timeline_route(route)
        if timeline_run_id is not None:
            return service_runtime_status.execute_runtime_timeline_request(
                timeline_run_id,
                active_config,
                request_auth_subject=runtime_read_subject,
                request_auth_is_admin=runtime_read_is_admin,
            )
    if method.upper() == "GET" and route.startswith("/runtime/runs/"):
        artifacts_run_id = _runtime_artifacts_route(route)
        if artifacts_run_id is not None:
            return service_runtime_status.execute_runtime_artifacts_request(
                artifacts_run_id,
                active_config,
                request_auth_subject=runtime_read_subject,
                request_auth_is_admin=runtime_read_is_admin,
            )
    if method.upper() == "GET" and route.startswith("/runtime/runs/"):
        artifact_route = _runtime_artifact_route(route)
        if artifact_route is not None:
            run_id, artifact_id = artifact_route
            return service_runtime_status.execute_runtime_artifact_request(
                run_id,
                artifact_id,
                active_config,
                request_auth_subject=runtime_read_subject,
                request_auth_is_admin=runtime_read_is_admin,
            )
    if method.upper() == "GET" and route.startswith("/runtime/runs/"):
        run_id = route.removeprefix("/runtime/runs/")
        return service_runtime_status.execute_runtime_status_request(
            run_id,
            active_config,
            request_auth_subject=runtime_read_subject,
            request_auth_is_admin=runtime_read_is_admin,
        )
    if method.upper() == "GET" and route == "/openapi.json":
        return 200, service_openapi()
    if method.upper() == "GET" and route == "/metrics":
        return 200, metrics_snapshot(
            metrics,
            concurrency_limiter,
            rate_limiter,
            idempotency_cache,
            active_config,
        )
    if method.upper() == "GET" and route == "/metrics.prom":
        return 200, prometheus_metrics_text(
            metrics_snapshot(
                metrics,
                concurrency_limiter,
                rate_limiter,
                idempotency_cache,
                active_config,
            )
        )
    if method.upper() == "POST" and route == "/run":
        return _handle_run_route(
            body,
            headers=headers or {},
            config=active_config,
            metrics=metrics,
            rate_limiter=rate_limiter,
            concurrency_limiter=concurrency_limiter,
            idempotency_cache=idempotency_cache,
            remote_addr=remote_addr,
            agent_runner=agent_runner,
        )
    if method.upper() == "POST" and route == "/runtime/run":
        return _handle_execution_route(
            body,
            headers=headers or {},
            config=active_config,
            metrics=metrics,
            rate_limiter=rate_limiter,
            concurrency_limiter=concurrency_limiter,
            idempotency_cache=idempotency_cache,
            remote_addr=remote_addr,
            idempotency_scope="POST /runtime/run",
            include_auth_admin=False,
            execute_request=(
                lambda request_body, service_config, auth_subject, _auth_is_admin: (
                    service_runtime_run.execute_runtime_run_request(
                        request_body,
                        service_config,
                        auth_subject,
                    )
                )
            ),
        )
    if method.upper() == "POST" and route == "/runtime/resume":
        return _handle_execution_route(
            body,
            headers=headers or {},
            config=active_config,
            metrics=metrics,
            rate_limiter=rate_limiter,
            concurrency_limiter=concurrency_limiter,
            idempotency_cache=idempotency_cache,
            remote_addr=remote_addr,
            idempotency_scope="POST /runtime/resume",
            include_auth_admin=True,
            execute_request=(
                lambda request_body, service_config, auth_subject, auth_is_admin: (
                    service_runtime_resume.execute_runtime_resume_request(
                        request_body,
                        service_config,
                        auth_subject,
                        request_auth_is_admin=auth_is_admin,
                    )
                )
            ),
        )
    if method.upper() == "POST" and route.startswith("/runtime/runs/"):
        cancel_run_id = _runtime_cancel_route(route)
        if cancel_run_id is not None:
            return _handle_execution_route(
                body,
                headers=headers or {},
                config=active_config,
                metrics=metrics,
                rate_limiter=rate_limiter,
                concurrency_limiter=concurrency_limiter,
                idempotency_cache=idempotency_cache,
                remote_addr=remote_addr,
                idempotency_scope=f"POST /runtime/runs/{cancel_run_id}/cancel",
                include_auth_admin=True,
                execute_request=(
                    lambda request_body, service_config, auth_subject, auth_is_admin: (
                        service_runtime_cancel.execute_runtime_cancel_request(
                            cancel_run_id,
                            request_body,
                            service_config,
                            auth_subject,
                            request_auth_is_admin=auth_is_admin,
                        )
                    )
                ),
            )
    return 404, service_errors.failure_payload(service_errors.NOT_FOUND, "not found")


def metrics_snapshot(
    metrics: Optional[ServiceMetrics],
    concurrency_limiter: Optional[ServiceConcurrencyLimiter],
    rate_limiter: Optional[ServiceRateLimiter],
    idempotency_cache: Optional[ServiceIdempotencyCache] = None,
    config: Optional[ServiceConfig] = None,
) -> Dict[str, Any]:
    payload = (metrics or ServiceMetrics()).snapshot()
    active_config = config or ServiceConfig()
    from self_correcting_langgraph_agent import __version__

    payload.update(
        {
            "service_version": __version__,
            "bind_host": active_config.host,
            "bind_port": str(active_config.port),
            "auth_required": str(active_config.auth_required).lower(),
            "auth_subject_count": str(
                len(active_config.auth_tokens) + (1 if active_config.auth_token else 0)
            ),
            "trace_persistence": "enabled" if active_config.trace_dir else "disabled",
            "max_request_bytes": str(active_config.max_request_bytes),
            "rate_limit_per_minute": str(active_config.rate_limit_per_minute),
            "max_concurrent_runs": str(active_config.max_concurrent_runs),
            "idempotency_cache_size": str(active_config.idempotency_cache_size),
            "idempotency_cache_backend": (
                "sqlite" if active_config.idempotency_cache_path else "memory"
            ),
            "idempotency_cache_path_configured": (
                "true" if active_config.idempotency_cache_path else "false"
            ),
            "max_goal_chars": str(active_config.max_goal_chars),
            "runtime_allowed_tools": (
                ",".join(active_config.runtime_allowed_tools)
                if active_config.runtime_allowed_tools
                else "default"
            ),
            "runtime_allowed_tools_by_subject_count": str(
                len(active_config.runtime_allowed_tools_by_subject)
            ),
            "runtime_max_iterations": str(active_config.runtime_max_iterations),
            "runtime_pending_approval_stale_seconds": str(
                active_config.runtime_pending_approval_stale_seconds
            ),
            "allow_full_trace_response": str(active_config.allow_full_trace_response).lower(),
            "protect_diagnostics": str(active_config.protect_diagnostics).lower(),
            "trust_forwarded_for": str(active_config.trust_forwarded_for).lower(),
            "run_timeout_seconds": str(active_config.run_timeout_seconds),
            "request_timeout_seconds": str(active_config.request_timeout_seconds),
        }
    )
    payload.update(service_status.security_response_header_snapshot())
    payload.update(service_status.trace_permission_policy_snapshot())
    payload.update(service_status.llm_provider_snapshot())
    payload.update(_runtime_pending_approval_metrics_snapshot(active_config))
    payload.update(_runtime_guardrail_metrics_snapshot(active_config))
    if concurrency_limiter is not None:
        payload.update(concurrency_limiter.snapshot())
    if rate_limiter is not None:
        payload.update(rate_limiter.snapshot())
    if idempotency_cache is not None:
        payload.update(idempotency_cache.snapshot())
    return payload


def _runtime_pending_approval_metrics_snapshot(config: ServiceConfig) -> Dict[str, str]:
    if not config.trace_dir:
        return _empty_runtime_pending_approval_metrics(config)
    unfiltered_status, unfiltered = (
        service_runtime_status.execute_runtime_approvals_summary_request(
            "",
            config,
            request_auth_is_admin=True,
        )
    )
    stale_status, stale = service_runtime_status.execute_runtime_approvals_summary_request(
        f"min_pending_age_seconds={config.runtime_pending_approval_stale_seconds}",
        config,
        request_auth_is_admin=True,
    )
    if unfiltered_status != 200 or stale_status != 200:
        return _empty_runtime_pending_approval_metrics(config)
    return {
        "runtime_pending_approvals_current": str(
            unfiltered.get("pending_approval_count", "0")
        ),
        "runtime_stale_pending_approvals_current": str(
            stale.get("pending_approval_count", "0")
        ),
        "runtime_max_pending_approval_age_seconds": str(
            unfiltered.get("max_pending_age_seconds", "0")
        ),
        "runtime_pending_approval_stale_seconds": str(
            config.runtime_pending_approval_stale_seconds
        ),
    }


def _empty_runtime_pending_approval_metrics(config: ServiceConfig) -> Dict[str, str]:
    return {
        "runtime_pending_approvals_current": "0",
        "runtime_stale_pending_approvals_current": "0",
        "runtime_max_pending_approval_age_seconds": "0",
        "runtime_pending_approval_stale_seconds": str(
            config.runtime_pending_approval_stale_seconds
        ),
    }


def _runtime_guardrail_metrics_snapshot(config: ServiceConfig) -> Dict[str, Any]:
    if not config.trace_dir:
        return _empty_runtime_guardrail_metrics()
    status_code, summary = service_runtime_status.execute_runtime_summary_request(
        "",
        config,
        request_auth_is_admin=True,
    )
    if status_code != 200:
        return _empty_runtime_guardrail_metrics()
    reason_counts = summary.get("final_answer_guardrail_reason_counts")
    return {
        "runtime_final_answer_guardrails_total": str(
            summary.get("final_answer_guardrail_applied_count", "0")
        ),
        "runtime_final_answer_guardrails_by_reason": (
            reason_counts if isinstance(reason_counts, dict) else {}
        ),
    }


def _empty_runtime_guardrail_metrics() -> Dict[str, Any]:
    return {
        "runtime_final_answer_guardrails_total": "0",
        "runtime_final_answer_guardrails_by_reason": {},
    }


def agent_run_status(status_code: int, payload: Any) -> str:
    if status_code == 504:
        return "timeout"
    if isinstance(payload, dict):
        status = str(payload.get("status", ""))
        if status:
            return status
    if status_code >= 500:
        return "failed"
    return "rejected"


_PROTECTED_DIAGNOSTIC_ROUTES = frozenset(
    {
        "/config",
        "/tools",
        "/runtime/tools",
        "/metrics",
        "/metrics.prom",
        "/openapi.json",
    }
)


def _is_protected_diagnostic_route(route: str) -> bool:
    return (
        route in _PROTECTED_DIAGNOSTIC_ROUTES
        or route.startswith("/runtime/approvals")
        or route == "/runtime/policy"
        or route.startswith("/runtime/runs")
    )


def _runtime_read_auth_context(
    headers: Mapping[str, str],
    config: ServiceConfig,
) -> tuple[str, bool]:
    auth_subject = service_safety.authenticated_subject(
        headers,
        config.auth_token,
        config.auth_tokens,
    )
    is_admin = service_safety.authenticated_with_primary_token(
        headers,
        config.auth_token,
    )
    return auth_subject, is_admin


def _runtime_timeline_route(route: str) -> str | None:
    remainder = route.removeprefix("/runtime/runs/")
    run_id, separator, suffix = remainder.partition("/timeline")
    if separator and run_id and suffix == "":
        return run_id
    return None


def _runtime_artifacts_route(route: str) -> str | None:
    remainder = route.removeprefix("/runtime/runs/")
    run_id, separator, suffix = remainder.partition("/artifacts")
    if separator and run_id and suffix == "":
        return run_id
    return None


def _runtime_artifact_route(route: str) -> tuple[str, str] | None:
    remainder = route.removeprefix("/runtime/runs/")
    run_id, separator, artifact_id = remainder.partition("/artifacts/")
    if separator and run_id and artifact_id:
        return run_id, artifact_id
    return None


def _runtime_cancel_route(route: str) -> str | None:
    remainder = route.removeprefix("/runtime/runs/")
    run_id, separator, suffix = remainder.partition("/cancel")
    if separator and run_id and suffix == "":
        return run_id
    return None


def _handle_run_route(
    body: bytes,
    *,
    headers: Mapping[str, str],
    config: ServiceConfig,
    metrics: Optional[ServiceMetrics],
    rate_limiter: Optional[ServiceRateLimiter],
    concurrency_limiter: Optional[ServiceConcurrencyLimiter],
    idempotency_cache: Optional[ServiceIdempotencyCache],
    remote_addr: str,
    agent_runner: Optional[Callable[[str, Any], Dict[str, Any]]],
) -> Tuple[int, Any]:
    def execute_request(
        request_body: bytes,
        service_config: ServiceConfig,
        _auth_subject: str,
        _auth_is_admin: bool,
    ) -> Tuple[int, Any]:
        return service_run.execute_run_request(request_body, service_config, agent_runner)

    return _handle_execution_route(
        body,
        headers=headers,
        config=config,
        metrics=metrics,
        rate_limiter=rate_limiter,
        concurrency_limiter=concurrency_limiter,
        idempotency_cache=idempotency_cache,
        remote_addr=remote_addr,
        idempotency_scope="POST /run",
        include_auth_admin=False,
        execute_request=execute_request,
    )


def _handle_execution_route(
    body: bytes,
    *,
    headers: Mapping[str, str],
    config: ServiceConfig,
    metrics: Optional[ServiceMetrics],
    rate_limiter: Optional[ServiceRateLimiter],
    concurrency_limiter: Optional[ServiceConcurrencyLimiter],
    idempotency_cache: Optional[ServiceIdempotencyCache],
    remote_addr: str,
    idempotency_scope: str,
    include_auth_admin: bool,
    execute_request: Callable[[bytes, ServiceConfig, str, bool], Tuple[int, Any]],
) -> Tuple[int, Any]:
    if not service_safety.json_content_type(headers):
        return 415, service_errors.failure_payload(
            service_errors.UNSUPPORTED_MEDIA_TYPE,
            "content-type must be application/json",
        )
    if len(body) > config.max_request_bytes:
        return 413, service_errors.failure_payload(
            service_errors.REQUEST_TOO_LARGE,
            "request body too large",
        )
    auth_subject = service_safety.authenticated_subject(
        headers,
        config.auth_token,
        config.auth_tokens,
    )
    auth_is_admin = (
        service_safety.authenticated_with_primary_token(headers, config.auth_token)
        if include_auth_admin
        else False
    )
    if config.auth_required and not auth_subject:
        return 401, service_errors.failure_payload(service_errors.UNAUTHORIZED, "unauthorized")
    idempotency_key = service_safety.header_value(headers, "Idempotency-Key")
    if idempotency_key and not service_safety.safe_idempotency_key(idempotency_key):
        return 400, service_errors.failure_payload(
            service_errors.INVALID_IDEMPOTENCY_KEY,
            "idempotency key must be 1-128 printable ASCII characters",
        )
    scoped_idempotency_key = _scoped_idempotency_key(
        idempotency_scope,
        idempotency_key,
        auth_subject,
    )
    if (
        idempotency_key
        and config.idempotency_cache_size > 0
        and idempotency_cache is not None
    ):
        cache_status, cached_response = idempotency_cache.lookup(scoped_idempotency_key, body)
        if cache_status == "hit" and cached_response is not None:
            return cached_response
        if cache_status == "conflict":
            return 409, service_errors.failure_payload(
                service_errors.IDEMPOTENCY_KEY_CONFLICT,
                "idempotency key was already used with a different request body",
            )
    rate_limit_key = service_safety.rate_limit_key(
        headers,
        remote_addr,
        trust_forwarded_for=config.trust_forwarded_for,
        auth_token=config.auth_token,
        auth_tokens=config.auth_tokens,
        auth_subject=auth_subject,
    )
    if rate_limiter is not None and not rate_limiter.allow(rate_limit_key):
        payload = service_errors.failure_payload(
            service_errors.RATE_LIMIT_EXCEEDED,
            "rate limit exceeded",
        )
        payload["retry_after_seconds"] = str(
            rate_limiter.retry_after_seconds(rate_limit_key)
        )
        return 429, payload
    release_run_slot = concurrency_limiter.try_acquire() if concurrency_limiter else None
    if concurrency_limiter is not None and release_run_slot is None:
        payload = service_errors.failure_payload(
            service_errors.TOO_MANY_CONCURRENT_RUNS,
            "too many concurrent runs",
        )
        payload["retry_after_seconds"] = "1"
        return 503, payload
    try:
        started_at = time.perf_counter()
        status_code, payload = execute_request(body, config, auth_subject, auth_is_admin)
        if (
            status_code == 200
            and idempotency_key
            and config.idempotency_cache_size > 0
            and idempotency_cache is not None
        ):
            idempotency_cache.store(scoped_idempotency_key, body, status_code, payload)
        if metrics is not None:
            metrics.record_agent_run(
                status=agent_run_status(status_code, payload),
                duration_seconds=time.perf_counter() - started_at,
            )
            _record_runtime_run_metrics(metrics, status_code, payload)
        return status_code, payload
    finally:
        if release_run_slot is not None:
            release_run_slot()


def _scoped_idempotency_key(scope: str, key: str, auth_subject: str = "") -> str:
    if not key:
        return ""
    subject_scope = auth_subject or "__anonymous__"
    return f"{scope}\x1f{subject_scope}\x1f{key}"


def _record_runtime_run_metrics(
    metrics: ServiceMetrics,
    status_code: int,
    payload: Any,
) -> None:
    if status_code != 200 or not isinstance(payload, dict):
        return
    if payload.get("trace_type") != "codex_runtime":
        return
    status = str(payload.get("status", ""))
    observations = payload.get("observations")
    failed_observation_count = _runtime_observation_status_count(
        observations,
        "failed",
    )
    approval_required_count = _runtime_observation_status_count(
        observations,
        "requires_approval",
    )
    metrics.record_runtime_run(
        status=status,
        failed_observation_count=failed_observation_count,
        approval_required_count=approval_required_count,
        budget_exhausted=(
            status == "failed"
            and str(payload.get("iteration_budget_remaining", "")) == "0"
        ),
        duration_seconds=_runtime_duration_seconds(payload),
        error_code_counts=_runtime_observation_error_code_counts(observations),
        auth_subject=str(payload.get("auth_subject", "")),
        resumed_by_auth_subject=str(payload.get("resumed_by_auth_subject", "")),
    )


def _runtime_duration_seconds(payload: Dict[str, Any]) -> float:
    try:
        return max(0.0, float(payload.get("duration_seconds", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _runtime_observation_status_count(value: Any, status: str) -> int:
    if not isinstance(value, list):
        return 0
    return sum(
        1
        for item in value
        if isinstance(item, dict) and str(item.get("status", "")) == status
    )


def _runtime_observation_error_code_counts(value: Any) -> Dict[str, int]:
    if not isinstance(value, list):
        return {}
    counts: Dict[str, int] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "")) not in {"failed", "requires_approval"}:
            continue
        error_code = str(item.get("error_code", ""))
        if not error_code:
            continue
        counts[error_code] = counts.get(error_code, 0) + 1
    return counts
