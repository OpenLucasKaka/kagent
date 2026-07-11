from __future__ import annotations

import contextlib
import io
import json
import warnings
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any, Callable, Dict, Optional, Tuple

from kagent.service import errors as service_errors
from kagent.service.active_runs import ExecutionSlotLease
from kagent.service.errors import failure_payload
from kagent.service.runtime import ServiceConfig
from kagent.service.trace_store import persist_trace
from kagent.utils.config_validation import (
    optional_json_bool,
    optional_json_int,
)
from kagent.utils.json_output import json_ready


def execute_run_request(
    body: bytes,
    service_config: ServiceConfig,
    agent_runner: Optional[Callable[[str, Any], Dict[str, Any]]] = None,
    execution_slot_lease: Optional[ExecutionSlotLease] = None,
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
    if len(goal) > service_config.max_goal_chars:
        return 413, failure_payload(
            service_errors.GOAL_TOO_LARGE,
            "goal exceeds max_goal_chars",
        )
    try:
        wants_full_trace = optional_json_bool(payload, "full_trace", False)
    except ValueError as exc:
        return 400, failure_payload(service_errors.INVALID_REQUEST_BODY, str(exc))
    if wants_full_trace and not service_config.allow_full_trace_response:
        return 403, failure_payload(
            service_errors.FULL_TRACE_DISABLED,
            "full_trace responses are disabled",
        )

    warning_sink = io.StringIO()
    with contextlib.redirect_stderr(warning_sink), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from kagent.core.agent import AgentConfig, run_agent
        from kagent.core.summary import summarize_run

        try:
            defaults = AgentConfig()
            config = AgentConfig(
                max_steps=optional_int(payload, "max_steps", defaults.max_steps),
                max_retries=optional_int(payload, "max_retries", defaults.max_retries),
            )
        except ValueError as exc:
            return 400, failure_payload(service_errors.INVALID_AGENT_CONFIG, str(exc))

        def run_with_config() -> Dict[str, Any]:
            if agent_runner is not None:
                return agent_runner(goal, config)
            return run_agent(goal, config=config)

        try:
            release_worker_slot = (
                execution_slot_lease.transfer()
                if execution_slot_lease is not None
                else None
            )
            timeout_options = {"timeout_seconds": service_config.run_timeout_seconds}
            if release_worker_slot is not None:
                timeout_options["on_complete"] = release_worker_slot
            trace = run_with_timeout(run_with_config, **timeout_options)
        except TimeoutError:
            return 504, failure_payload(
                service_errors.AGENT_RUN_TIMEOUT,
                "agent run timed out",
            )
        except Exception:
            return 500, failure_payload(service_errors.AGENT_RUN_FAILED, "agent run failed")
        trace_path = ""
        if service_config.trace_dir:
            try:
                trace_path = persist_trace(trace, service_config.trace_dir)
            except OSError as exc:
                return 500, failure_payload(
                    service_errors.TRACE_PERSISTENCE_FAILED,
                    f"could not persist trace: {exc}",
                )
        result = trace if wants_full_trace else summarize_run(trace)
        if trace_path:
            result["trace_path"] = trace_path
        return 200, json_ready(result)


def run_with_timeout(
    call,
    *,
    timeout_seconds: float,
    on_timeout: Optional[Callable[[], None]] = None,
    on_complete: Optional[Callable[[], None]] = None,
) -> Dict[str, Any]:
    executor = ThreadPoolExecutor(max_workers=1)

    def run_and_complete() -> Dict[str, Any]:
        try:
            return call()
        finally:
            if on_complete is not None:
                try:
                    on_complete()
                except Exception:
                    # Lifecycle cleanup must not replace the worker result or error.
                    pass

    future = executor.submit(run_and_complete)
    try:
        try:
            return future.result(timeout=timeout_seconds)
        except TimeoutError as timeout_error:
            if future.done():
                return future.result()
            if on_timeout is not None:
                on_timeout()
            try:
                future.result(timeout=timeout_seconds)
            except TimeoutError:
                pass
            except Exception:
                pass
            raise timeout_error
    finally:
        if not future.done():
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)


def optional_int(payload: Dict[str, Any], key: str, default: int) -> int:
    return optional_json_int(payload, key, default)
