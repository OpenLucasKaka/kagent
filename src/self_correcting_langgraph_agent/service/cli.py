from __future__ import annotations

import argparse
import json
import signal
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, List, Mapping, Optional
from urllib.parse import urlparse
from uuid import uuid4

from self_correcting_langgraph_agent.service import (
    contract as service_contract,
)
from self_correcting_langgraph_agent.service import (
    errors as service_errors,
)
from self_correcting_langgraph_agent.service import (
    router as service_router,
)
from self_correcting_langgraph_agent.service import (
    run as service_run,
)
from self_correcting_langgraph_agent.service import (
    runtime as service_runtime,
)
from self_correcting_langgraph_agent.service import (
    safety as service_safety,
)
from self_correcting_langgraph_agent.service import (
    server as service_server,
)
from self_correcting_langgraph_agent.service import (
    status as service_status,
)
from self_correcting_langgraph_agent.service import (
    trace_store as service_trace_store,
)
from self_correcting_langgraph_agent.service import (
    transport as service_transport,
)
from self_correcting_langgraph_agent.service.runtime import (
    ServiceConcurrencyLimiter,
    ServiceConfig,
    ServiceIdempotencyCache,
    ServiceMetrics,
    ServiceRateLimiter,
    access_log_record,
)
from self_correcting_langgraph_agent.utils.json_output import json_ready

_ALLOWED_HTTP_METHODS = service_contract.ALLOWED_HTTP_METHODS
_KNOWN_METRICS_PATHS = frozenset(
    {
        "/config",
        "/health",
        "/metrics",
        "/metrics.prom",
        "/openapi.json",
        "/ready",
        "/run",
        "/runtime/resume",
        "/runtime/approvals",
        "/runtime/approvals/summary",
        "/runtime/policy",
        "/runtime/runs",
        "/runtime/runs/summary",
        "/runtime/runs/{run_id}",
        "/runtime/runs/{run_id}/artifacts",
        "/runtime/runs/{run_id}/artifacts/{artifact_id}",
        "/runtime/runs/{run_id}/cancel",
        "/runtime/runs/{run_id}/timeline",
        "/runtime/run",
        "/runtime/tools",
        "/tools",
        "/version",
    }
)
_UNKNOWN_METRICS_PATH = "__unknown__"
access_log_schema = service_runtime.access_log_schema
service_openapi = service_contract.service_openapi
readiness_payload = service_status.readiness_payload
service_config_snapshot = service_status.service_config_snapshot
_failure_payload = service_errors.failure_payload
_authorized = service_safety.authorized
_json_content_type = service_safety.json_content_type
_json_ready = json_ready
_rate_limit_key = service_safety.rate_limit_key
_request_id_from_headers = service_safety.request_id_from_headers
_persist_trace = service_trace_store.persist_trace
handle_request = service_router.handle_request
_handle_run = service_run.execute_run_request
_run_with_timeout = service_run.run_with_timeout
_optional_int = service_run.optional_int
_payload_error_code = service_transport.error_code_from_payload
_metrics_snapshot = service_router.metrics_snapshot
_agent_run_status = service_router.agent_run_status


class _SignalShutdown(Exception):
    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(f"received signal {signum}")


def create_server(
    host: str,
    port: int,
    *,
    config: Optional[ServiceConfig] = None,
) -> ThreadingHTTPServer:
    return service_server.create_threading_server(
        host,
        port,
        _AgentRequestHandler,
        config=config,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the self-correcting LangGraph agent API.")
    try:
        defaults = ServiceConfig.from_env()
    except ValueError as exc:
        parser.error(str(exc))
    parser.add_argument("--host", default=defaults.host)
    parser.add_argument("--port", type=int, default=defaults.port)
    parser.add_argument("--max-request-bytes", type=int, default=defaults.max_request_bytes)
    parser.add_argument("--max-goal-chars", type=int, default=defaults.max_goal_chars)
    parser.add_argument("--auth-token", default=defaults.auth_token)
    parser.add_argument("--rate-limit-per-minute", type=int, default=defaults.rate_limit_per_minute)
    parser.add_argument("--max-concurrent-runs", type=int, default=defaults.max_concurrent_runs)
    parser.add_argument(
        "--idempotency-cache-size",
        type=int,
        default=defaults.idempotency_cache_size,
    )
    parser.add_argument(
        "--idempotency-cache-path",
        default=defaults.idempotency_cache_path,
        help="Optional SQLite file for persistent/shared Idempotency-Key responses.",
    )
    parser.add_argument(
        "--runtime-max-iterations",
        type=int,
        default=defaults.runtime_max_iterations,
        help="Maximum Codex-style runtime planner iterations per request.",
    )
    parser.add_argument(
        "--runtime-pending-approval-stale-seconds",
        type=int,
        default=defaults.runtime_pending_approval_stale_seconds,
        help=(
            "Age threshold for stale pending approval gauges exposed by "
            "/metrics and /metrics.prom."
        ),
    )
    parser.add_argument(
        "--runtime-allowed-tools",
        default=",".join(defaults.runtime_allowed_tools),
        help=(
            "Comma-separated runtime tools allowed to execute without approval; "
            "empty uses the default policy."
        ),
    )
    parser.add_argument(
        "--runtime-allowed-tools-by-subject",
        default=_subject_tools_json(defaults.runtime_allowed_tools_by_subject),
        help=(
            "JSON object mapping auth_subject values to comma-separated tool lists "
            "or arrays of tool names."
        ),
    )
    parser.add_argument(
        "--allow-full-trace-response",
        action=argparse.BooleanOptionalAction,
        default=defaults.allow_full_trace_response,
        help="Allow POST /run full_trace=true to return internal trace bodies.",
    )
    parser.add_argument(
        "--protect-diagnostics",
        action=argparse.BooleanOptionalAction,
        default=defaults.protect_diagnostics,
        help="Require bearer auth for diagnostic GET endpoints.",
    )
    parser.add_argument(
        "--trust-forwarded-for",
        action="store_true",
        default=defaults.trust_forwarded_for,
    )
    parser.add_argument("--trace-dir", default=defaults.trace_dir)
    parser.add_argument("--run-timeout-seconds", type=float, default=defaults.run_timeout_seconds)
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=defaults.request_timeout_seconds,
    )
    args = parser.parse_args(argv)
    try:
        config = ServiceConfig(
            host=args.host,
            port=args.port,
            max_request_bytes=args.max_request_bytes,
            max_goal_chars=args.max_goal_chars,
            auth_token=args.auth_token,
            auth_tokens=defaults.auth_tokens,
            rate_limit_per_minute=args.rate_limit_per_minute,
            max_concurrent_runs=args.max_concurrent_runs,
            idempotency_cache_size=args.idempotency_cache_size,
            idempotency_cache_path=args.idempotency_cache_path,
            runtime_allowed_tools=_csv_tuple(args.runtime_allowed_tools),
            runtime_allowed_tools_by_subject=_subject_tools_map(
                args.runtime_allowed_tools_by_subject
            ),
            runtime_max_iterations=args.runtime_max_iterations,
            runtime_pending_approval_stale_seconds=(
                args.runtime_pending_approval_stale_seconds
            ),
            allow_full_trace_response=args.allow_full_trace_response,
            protect_diagnostics=args.protect_diagnostics,
            trust_forwarded_for=args.trust_forwarded_for,
            trace_dir=args.trace_dir,
            run_timeout_seconds=args.run_timeout_seconds,
            request_timeout_seconds=args.request_timeout_seconds,
        )
    except ValueError as exc:
        parser.error(str(exc))

    server = create_server(config.host, config.port, config=config)
    host, port = server.server_address
    print(json.dumps({"status": "serving", "host": host, "port": port}), flush=True)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _raise_signal_shutdown)
    try:
        server.serve_forever()
    except _SignalShutdown as exc:
        return 128 + exc.signum
    except KeyboardInterrupt:
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        server.server_close()
    return 0


def _raise_signal_shutdown(signum: int, _frame: Any) -> None:
    raise _SignalShutdown(signum)


def _csv_tuple(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(sorted({item.strip() for item in value.split(",") if item.strip()}))


def _subject_tools_json(value: Mapping[str, tuple[str, ...]]) -> str:
    if not value:
        return ""
    return json.dumps({subject: list(tools) for subject, tools in value.items()})


def _subject_tools_map(value: str) -> dict[str, tuple[str, ...]]:
    if not value:
        return {}
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("runtime_allowed_tools_by_subject must be a JSON object")
    result: dict[str, tuple[str, ...]] = {}
    for subject, tools in payload.items():
        if isinstance(tools, str):
            result[str(subject)] = _csv_tuple(tools)
        elif isinstance(tools, list) and all(isinstance(item, str) for item in tools):
            result[str(subject)] = tuple(sorted({item.strip() for item in tools if item.strip()}))
        else:
            raise ValueError(
                "runtime_allowed_tools_by_subject values must be strings or arrays of strings"
            )
    return result


class _AgentRequestHandler(BaseHTTPRequestHandler):
    server_version = "SelfCorrectingAgentHTTP/0.1"

    def version_string(self) -> str:
        return self.server_version

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(self._config().request_timeout_seconds)

    def do_GET(self) -> None:
        self._started_at = time.perf_counter()
        self._request_id_value = _request_id_from_headers(self.headers)
        self._idempotency_key_present = None
        if self._has_ambiguous_authorization():
            self._send_unauthorized_response()
            return
        self._send_response(
            *handle_request(
                "GET",
                self.path,
                b"",
                headers=dict(self.headers.items()),
                config=self._config(),
                metrics=self._metrics(),
                rate_limiter=self._rate_limiter(),
                concurrency_limiter=self._concurrency_limiter(),
                idempotency_cache=self._idempotency_cache(),
                remote_addr=self._remote_addr(),
            )
        )

    def do_HEAD(self) -> None:
        self._started_at = time.perf_counter()
        self._request_id_value = _request_id_from_headers(self.headers)
        self._idempotency_key_present = None
        if self._has_ambiguous_authorization():
            self._send_unauthorized_response()
            return
        self._send_response(
            *handle_request(
                "GET",
                self.path,
                b"",
                headers=dict(self.headers.items()),
                config=self._config(),
                metrics=self._metrics(),
                rate_limiter=self._rate_limiter(),
                concurrency_limiter=self._concurrency_limiter(),
                idempotency_cache=self._idempotency_cache(),
                remote_addr=self._remote_addr(),
            ),
            write_body=False,
        )

    def do_OPTIONS(self) -> None:
        self._started_at = time.perf_counter()
        self._request_id_value = _request_id_from_headers(self.headers)
        self._idempotency_key_present = None
        self._send_empty_response(204, headers={"Allow": _ALLOWED_HTTP_METHODS})

    def do_POST(self) -> None:
        self._started_at = time.perf_counter()
        self._request_id_value = _request_id_from_headers(self.headers)
        self._request_body_bytes = None
        if self._has_ambiguous_authorization():
            self._idempotency_key_present = None
            self._send_unauthorized_response()
            return
        expect_headers = self.headers.get_all("Expect", [])
        if expect_headers:
            self._idempotency_key_present = None
            self._send_response(
                417,
                _failure_payload(
                    service_errors.EXPECTATION_FAILED,
                    "expect header is unsupported",
                ),
            )
            return
        idempotency_keys = self.headers.get_all("Idempotency-Key", [])
        self._idempotency_key_present = bool(idempotency_keys)
        if len(idempotency_keys) > 1:
            self._send_response(
                400,
                _failure_payload(
                    service_errors.INVALID_IDEMPOTENCY_KEY,
                    "idempotency key must be single-valued",
                ),
            )
            return
        transfer_encodings = self.headers.get_all("Transfer-Encoding", [])
        if transfer_encodings:
            self._send_response(
                400,
                _failure_payload(
                    service_errors.INVALID_TRANSFER_ENCODING,
                    "transfer-encoding is unsupported",
                ),
            )
            return
        content_types = self.headers.get_all("Content-Type", [])
        if len(content_types) > 1:
            self._send_response(
                415,
                _failure_payload(
                    service_errors.UNSUPPORTED_MEDIA_TYPE,
                    "content-type must be single-valued application/json",
                ),
            )
            return
        content_lengths = self.headers.get_all("Content-Length", [])
        if len(content_lengths) != 1:
            self._send_response(
                400,
                _failure_payload(service_errors.INVALID_CONTENT_LENGTH, "invalid content-length"),
            )
            return
        try:
            length = int(content_lengths[0])
        except ValueError:
            self._send_response(
                400,
                _failure_payload(service_errors.INVALID_CONTENT_LENGTH, "invalid content-length"),
            )
            return
        if length < 0:
            self._send_response(
                400,
                _failure_payload(service_errors.INVALID_CONTENT_LENGTH, "invalid content-length"),
            )
            return
        if length > self._config().max_request_bytes:
            self._send_response(
                413,
                _failure_payload(service_errors.REQUEST_TOO_LARGE, "request body too large"),
            )
            return
        try:
            body = self.rfile.read(length) if length else b""
        except socket.timeout:
            payload = _failure_payload(
                service_errors.REQUEST_BODY_TIMEOUT,
                "timed out while reading request body",
            )
            payload["retry_after_seconds"] = "1"
            self._send_response(
                408,
                payload,
            )
            return
        self._request_body_bytes = len(body)
        if len(body) != length:
            self._send_response(
                400,
                _failure_payload(
                    service_errors.INCOMPLETE_REQUEST_BODY,
                    "request body ended before content-length bytes were read",
                ),
            )
            return
        self._send_response(
            *handle_request(
                "POST",
                self.path,
                body,
                headers=dict(self.headers.items()),
                config=self._config(),
                metrics=self._metrics(),
                rate_limiter=self._rate_limiter(),
                concurrency_limiter=self._concurrency_limiter(),
                idempotency_cache=self._idempotency_cache(),
                remote_addr=self._remote_addr(),
            )
        )

    def do_DELETE(self) -> None:
        self._send_method_not_allowed()

    def do_PATCH(self) -> None:
        self._send_method_not_allowed()

    def do_PUT(self) -> None:
        self._send_method_not_allowed()

    def log_message(self, format: str, *args: Any) -> None:
        return None

    def _send_method_not_allowed(self) -> None:
        self._started_at = time.perf_counter()
        self._request_id_value = _request_id_from_headers(self.headers)
        self._idempotency_key_present = None
        if self._has_ambiguous_authorization():
            self._send_unauthorized_response()
            return
        self._send_response(
            405,
            _failure_payload(service_errors.METHOD_NOT_ALLOWED, "method not allowed"),
            headers={"Allow": _ALLOWED_HTTP_METHODS},
        )

    def _send_response(
        self,
        status_code: int,
        payload: Any,
        *,
        headers: Optional[Mapping[str, str]] = None,
        write_body: bool = True,
    ) -> None:
        data, content_type = service_transport.response_body(payload)
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", service_transport.NOSNIFF_HEADER_VALUE)
        self.send_header("Cache-Control", service_transport.CACHE_CONTROL_HEADER_VALUE)
        self.send_header("Referrer-Policy", service_transport.REFERRER_POLICY_HEADER_VALUE)
        self.send_header(
            "Content-Security-Policy",
            service_transport.CONTENT_SECURITY_POLICY_HEADER_VALUE,
        )
        self.send_header("X-Frame-Options", service_transport.X_FRAME_OPTIONS_HEADER_VALUE)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Request-ID", self._request_id())
        run_id = _payload_field(payload, "run_id")
        if _safe_response_header_value(run_id):
            self.send_header("X-Run-ID", run_id)
        trace_path = _payload_field(payload, "trace_path")
        if _safe_trace_path_response_header_value(trace_path):
            self.send_header("X-Trace-Path", trace_path)
        if status_code == 401:
            self.send_header("WWW-Authenticate", "Bearer")
        retry_after = _retry_after_value(status_code, payload)
        if retry_after:
            self.send_header("Retry-After", retry_after)
        for header_name, header_value in (headers or {}).items():
            self.send_header(header_name, header_value)
        self.end_headers()
        if write_body:
            self.wfile.write(data)
        self._write_access_log(status_code, payload)

    def _send_empty_response(
        self,
        status_code: int,
        *,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.send_response(status_code)
        self.send_header("X-Content-Type-Options", service_transport.NOSNIFF_HEADER_VALUE)
        self.send_header("Cache-Control", service_transport.CACHE_CONTROL_HEADER_VALUE)
        self.send_header("Referrer-Policy", service_transport.REFERRER_POLICY_HEADER_VALUE)
        self.send_header(
            "Content-Security-Policy",
            service_transport.CONTENT_SECURITY_POLICY_HEADER_VALUE,
        )
        self.send_header("X-Frame-Options", service_transport.X_FRAME_OPTIONS_HEADER_VALUE)
        self.send_header("Content-Length", "0")
        self.send_header("X-Request-ID", self._request_id())
        for header_name, header_value in (headers or {}).items():
            self.send_header(header_name, header_value)
        self.end_headers()
        self._write_access_log(status_code, {})

    def _send_unauthorized_response(self) -> None:
        self._send_response(
            401,
            _failure_payload(service_errors.UNAUTHORIZED, "unauthorized"),
        )

    def _has_ambiguous_authorization(self) -> bool:
        authorization_headers = self.headers.get_all("Authorization", [])
        return bool(self._config().auth_required and len(authorization_headers) > 1)

    def _config(self) -> ServiceConfig:
        return getattr(self.server, "service_config", ServiceConfig())

    def _metrics(self) -> ServiceMetrics:
        return getattr(self.server, "service_metrics", ServiceMetrics())

    def _rate_limiter(self) -> ServiceRateLimiter:
        return getattr(self.server, "service_rate_limiter", ServiceRateLimiter(limit_per_minute=0))

    def _concurrency_limiter(self) -> ServiceConcurrencyLimiter:
        return getattr(
            self.server,
            "service_concurrency_limiter",
            ServiceConcurrencyLimiter(max_concurrent_runs=0),
        )

    def _idempotency_cache(self) -> ServiceIdempotencyCache:
        return getattr(
            self.server,
            "service_idempotency_cache",
            ServiceIdempotencyCache(max_entries=0),
        )

    def _request_id(self) -> str:
        return getattr(self, "_request_id_value", str(uuid4()))

    def _write_access_log(self, status_code: int, payload: Any) -> None:
        started_at = getattr(self, "_started_at", time.perf_counter())
        duration_seconds = time.perf_counter() - started_at
        error_code = _payload_error_code(payload)
        run_id = _payload_field(payload, "run_id")
        trace_path = _payload_field(payload, "trace_path")
        runtime_owner_auth_subject = _payload_field(payload, "auth_subject")
        resumed_by_auth_subject = _payload_field(payload, "resumed_by_auth_subject")
        idempotency_key_present = getattr(self, "_idempotency_key_present", None)
        request_body_bytes = getattr(self, "_request_body_bytes", None)
        config = self._config() if hasattr(self, "_config") else ServiceConfig()
        raw_headers = dict(self.headers.items()) if hasattr(self, "headers") else {}
        record = access_log_record(
            method=self.command,
            path=urlparse(self.path).path,
            status_code=status_code,
            duration_seconds=duration_seconds,
            request_id=self._request_id(),
            remote_addr=self._remote_addr(),
            error_code=error_code,
            run_id=run_id,
            trace_path=trace_path,
            idempotency_key_present=idempotency_key_present,
            request_body_bytes=request_body_bytes,
            auth_subject=service_safety.authenticated_subject(
                raw_headers,
                config.auth_token,
                config.auth_tokens,
            ),
            runtime_owner_auth_subject=runtime_owner_auth_subject,
            resumed_by_auth_subject=resumed_by_auth_subject,
        )
        self._metrics().record(
            method=record["method"],
            path=_metrics_path(record["path"]),
            status_code=status_code,
            duration_seconds=duration_seconds,
            error_code=error_code,
            auth_subject=record.get("auth_subject", ""),
        )
        sys.stderr.write(json.dumps(record, sort_keys=True) + "\n")
        sys.stderr.flush()

    def _remote_addr(self) -> str:
        return str(self.client_address[0])


def _payload_field(payload: Any, field_name: str) -> str:
    if isinstance(payload, dict):
        return str(payload.get(field_name, ""))
    return ""


def _metrics_path(path: str) -> str:
    if path == "/runtime/approvals/summary":
        return "/runtime/approvals/summary"
    if path == "/runtime/approvals":
        return "/runtime/approvals"
    if path == "/runtime/policy":
        return "/runtime/policy"
    if path == "/runtime/runs/summary":
        return "/runtime/runs/summary"
    if path.startswith("/runtime/runs/") and "/artifacts/" in path:
        return "/runtime/runs/{run_id}/artifacts/{artifact_id}"
    if path.startswith("/runtime/runs/") and path.endswith("/artifacts"):
        return "/runtime/runs/{run_id}/artifacts"
    if path.startswith("/runtime/runs/") and path.endswith("/cancel"):
        return "/runtime/runs/{run_id}/cancel"
    if path.startswith("/runtime/runs/") and path.endswith("/timeline"):
        return "/runtime/runs/{run_id}/timeline"
    if path.startswith("/runtime/runs/"):
        return "/runtime/runs/{run_id}"
    return path if path in _KNOWN_METRICS_PATHS else _UNKNOWN_METRICS_PATH


def _safe_response_header_value(value: str) -> bool:
    return service_safety.safe_request_id(value)


def _safe_trace_path_response_header_value(value: str) -> bool:
    return bool(value and len(value) <= 1024 and service_safety.safe_header_value(value))


def _retry_after_value(status_code: int, payload: Any) -> str:
    error_code = _payload_error_code(payload)
    if status_code == 429 and error_code == service_errors.RATE_LIMIT_EXCEEDED:
        retry_after_seconds = _payload_field(payload, "retry_after_seconds")
        return retry_after_seconds if retry_after_seconds else "60"
    if status_code == 503 and error_code == service_errors.TOO_MANY_CONCURRENT_RUNS:
        retry_after_seconds = _payload_field(payload, "retry_after_seconds")
        return retry_after_seconds if retry_after_seconds else "1"
    if status_code == 408 and error_code == service_errors.REQUEST_BODY_TIMEOUT:
        retry_after_seconds = _payload_field(payload, "retry_after_seconds")
        return retry_after_seconds if retry_after_seconds else "1"
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
