from __future__ import annotations

import argparse
from typing import Any, Dict, List, Optional

from self_correcting_langgraph_agent import __version__
from self_correcting_langgraph_agent.core.tools import registered_tool_names
from self_correcting_langgraph_agent.providers.llm import LLMProviderConfig
from self_correcting_langgraph_agent.service.runtime import ServiceConfig
from self_correcting_langgraph_agent.service.runtime_policy import (
    execute_runtime_policy_request,
)
from self_correcting_langgraph_agent.service.safety import safe_header_value
from self_correcting_langgraph_agent.service.status import (
    readiness_payload,
    service_config_snapshot,
)
from self_correcting_langgraph_agent.utils.json_output import format_and_write_json

MIN_PRODUCTION_AUTH_TOKEN_CHARS = 16
MIN_RUNTIME_PROVIDER_ITERATIONS = 2
PLACEHOLDER_AUTH_TOKENS = {
    "change-me",
    "changeme",
    "placeholder",
    "replace-me",
    "replace-with-a-long-random-token",
    "secret",
    "token",
}


def doctor_payload(
    config: Optional[ServiceConfig] = None,
    *,
    require_auth: bool = False,
    require_production_controls: bool = False,
    require_runtime_provider: bool = False,
    llm_config: Optional[LLMProviderConfig] = None,
) -> Dict[str, Any]:
    active_config = config or ServiceConfig.from_env()
    active_llm_config = llm_config or LLMProviderConfig.from_env()
    readiness = readiness_payload(active_config)
    policy = _policy_payload(
        active_config,
        active_llm_config,
        require_auth=require_auth,
        require_production_controls=require_production_controls,
        require_runtime_provider=require_runtime_provider,
    )
    status = (
        "ready"
        if readiness["status"] == "ready" and policy["status"] != "failed"
        else "not_ready"
    )
    config_snapshot = service_config_snapshot(active_config)
    config_snapshot.update(active_llm_config.redacted_snapshot())
    runtime_policy = _runtime_policy_summary(active_config)
    return {
        "status": status,
        "version": __version__,
        "readiness": readiness,
        "policy": policy,
        "runtime_policy": runtime_policy,
        "config": config_snapshot,
        "tool_count": str(len(registered_tool_names())),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run deployment self-checks for the self-correcting agent."
    )
    try:
        defaults = ServiceConfig.from_env()
    except ValueError as exc:
        parser.error(str(exc))
    parser.add_argument("--trace-dir", default=defaults.trace_dir)
    parser.add_argument(
        "--require-auth",
        action="store_true",
        help="Fail the self-check when POST /run bearer auth is disabled.",
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help=(
            "Fail the self-check unless production controls are configured: "
            "strong auth, diagnostic protection, trace persistence, rate "
            "limiting, and bounded concurrency."
        ),
    )
    parser.add_argument(
        "--require-runtime-provider",
        action="store_true",
        help=(
            "Fail the self-check unless the OpenAI-compatible runtime provider "
            "environment is configured and runtime replanning has at least two "
            "iterations available."
        ),
    )
    parser.add_argument("--output", default="", help="Optional JSON artifact path.")
    args = parser.parse_args(argv)

    config = ServiceConfig(
        host=defaults.host,
        port=defaults.port,
        max_request_bytes=defaults.max_request_bytes,
        max_goal_chars=defaults.max_goal_chars,
        auth_token=defaults.auth_token,
        auth_tokens=defaults.auth_tokens,
        rate_limit_per_minute=defaults.rate_limit_per_minute,
        max_concurrent_runs=defaults.max_concurrent_runs,
        idempotency_cache_size=defaults.idempotency_cache_size,
        idempotency_cache_path=defaults.idempotency_cache_path,
        runtime_allowed_tools=defaults.runtime_allowed_tools,
        runtime_allowed_tools_by_subject=defaults.runtime_allowed_tools_by_subject,
        runtime_max_iterations=defaults.runtime_max_iterations,
        allow_full_trace_response=defaults.allow_full_trace_response,
        protect_diagnostics=defaults.protect_diagnostics,
        trust_forwarded_for=defaults.trust_forwarded_for,
        trace_dir=args.trace_dir,
        run_timeout_seconds=defaults.run_timeout_seconds,
        request_timeout_seconds=defaults.request_timeout_seconds,
    )
    try:
        payload = doctor_payload(
            config,
            require_auth=args.require_auth,
            require_production_controls=args.production,
            require_runtime_provider=args.require_runtime_provider,
        )
    except ValueError as exc:
        parser.error(str(exc))
    try:
        json_payload = format_and_write_json(payload, args.output)
    except OSError as exc:
        parser.error(f"could not write --output file: {exc}")
    print(json_payload)
    return 0 if payload["status"] == "ready" else 1


def _policy_payload(
    config: ServiceConfig,
    llm_config: LLMProviderConfig,
    *,
    require_auth: bool,
    require_production_controls: bool,
    require_runtime_provider: bool,
) -> Dict[str, Any]:
    warnings = []
    failures = []
    configured_auth_tokens = _configured_auth_tokens(config)
    if _is_public_bind(config.host) and not config.auth_required:
        warnings.append("public_bind_without_auth")
    if (require_auth or require_production_controls) and not config.auth_required:
        failures.append("auth_required")
    if require_auth or require_production_controls:
        if any(not safe_header_value(f"Bearer {token}") for token in configured_auth_tokens):
            failures.append("auth_token_unsafe")
        if any(_is_placeholder_auth_token(token) for token in configured_auth_tokens):
            failures.append("auth_token_placeholder")
    if require_production_controls:
        if any(len(token) < MIN_PRODUCTION_AUTH_TOKEN_CHARS for token in configured_auth_tokens):
            failures.append("auth_token_too_short")
        if not config.trace_dir:
            failures.append("trace_dir_required")
        if config.rate_limit_per_minute <= 0:
            failures.append("rate_limit_required")
        if config.max_concurrent_runs <= 0:
            failures.append("concurrency_limit_required")
        if not config.protect_diagnostics:
            failures.append("diagnostics_protection_required")
        if config.allow_full_trace_response:
            failures.append("full_trace_response_must_be_disabled")
    if require_runtime_provider:
        if not llm_config.base_url:
            failures.append("llm_base_url_required")
        if not llm_config.model:
            failures.append("llm_model_required")
        if not llm_config.api_key:
            failures.append("llm_api_key_required")
        if config.runtime_max_iterations < MIN_RUNTIME_PROVIDER_ITERATIONS:
            failures.append("runtime_iterations_too_low")
    if failures:
        status = "failed"
    elif warnings:
        status = "warning"
    else:
        status = "ok"
    return {
        "status": status,
        "warnings": warnings,
        "failures": failures,
    }


def _is_public_bind(host: str) -> bool:
    return host in {"0.0.0.0", "::", ""}


def _is_placeholder_auth_token(auth_token: str) -> bool:
    normalized = auth_token.strip().lower()
    return normalized in PLACEHOLDER_AUTH_TOKENS


def _configured_auth_tokens(config: ServiceConfig) -> list[str]:
    tokens = []
    if config.auth_token:
        tokens.append(config.auth_token)
    tokens.extend(config.auth_tokens.values())
    return tokens


def _runtime_policy_summary(config: ServiceConfig) -> Dict[str, Any]:
    _status_code, payload = execute_runtime_policy_request(
        config,
        request_auth_subject="default",
        request_auth_is_admin=True,
    )
    effective_tool_policy = payload.get("effective_tool_policy", [])
    approval_required_count = sum(
        1
        for item in effective_tool_policy
        if isinstance(item, dict)
        and item.get("approval_required") == "true"
    )
    return {
        "trace_type": payload.get("trace_type", ""),
        "effective_policy_source": payload.get("effective_policy_source", ""),
        "effective_allowed_tools": payload.get("effective_allowed_tools", []),
        "effective_allowed_tool_count": str(
            len(payload.get("effective_allowed_tools", []))
        ),
        "approval_required_tool_count": str(approval_required_count),
        "subject_policy_count": payload.get("subject_policy_count", "0"),
        "effective_tool_policy_sha256": payload.get(
            "effective_tool_policy_sha256", ""
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
