import json
import time
from http.server import BaseHTTPRequestHandler

from kagent.runtime.cancellation import RuntimeCancellationToken
from kagent.service.active_runs import ActiveRunRegistry
from kagent.service.runtime import (
    ServiceConcurrencyLimiter,
    ServiceConfig,
    ServiceIdempotencyCache,
    ServiceMetrics,
    ServiceRateLimiter,
    SqliteServiceIdempotencyCache,
)
from kagent.service.runtime_recovery import RuntimeInstanceLease
from kagent.service.server import create_threading_server
from kagent.service.trace_store import load_trace_by_run_id, persist_trace


class DummyHandler(BaseHTTPRequestHandler):
    def handle(self):
        return None


def test_create_threading_server_attaches_runtime_dependencies():
    config = ServiceConfig(
        host="127.0.0.1",
        port=8000,
        rate_limit_per_minute=7,
        max_concurrent_runs=2,
        idempotency_cache_size=5,
    )

    server = create_threading_server("127.0.0.1", 0, DummyHandler, config=config)

    try:
        assert server.service_config is config
        assert isinstance(server.service_metrics, ServiceMetrics)
        assert isinstance(server.service_rate_limiter, ServiceRateLimiter)
        assert server.service_rate_limiter.snapshot()["rate_limit_per_minute"] == "7"
        assert isinstance(server.service_concurrency_limiter, ServiceConcurrencyLimiter)
        assert server.service_concurrency_limiter.snapshot()["max_concurrent_runs"] == "2"
        assert isinstance(server.service_active_run_registry, ActiveRunRegistry)
        assert isinstance(server.service_idempotency_cache, ServiceIdempotencyCache)
        assert server.service_idempotency_cache.snapshot()["idempotency_cache_size"] == "5"
    finally:
        server.server_close()


def test_create_threading_server_uses_sqlite_idempotency_cache_when_configured(
    tmp_path,
):
    config = ServiceConfig(
        idempotency_cache_size=5,
        idempotency_cache_path=str(tmp_path / "idempotency.sqlite3"),
    )

    server = create_threading_server("127.0.0.1", 0, DummyHandler, config=config)

    try:
        assert isinstance(server.service_idempotency_cache, SqliteServiceIdempotencyCache)
        assert (
            server.service_idempotency_cache.snapshot()["idempotency_cache_backend"]
            == "sqlite"
        )
    finally:
        server.server_close()


def test_create_threading_server_uses_bound_address_for_default_config():
    server = create_threading_server("127.0.0.1", 0, DummyHandler)

    try:
        host, port = server.server_address
        assert server.service_config.host == host
        assert server.service_config.port == port
    finally:
        server.server_close()


def test_create_threading_server_uses_production_socket_defaults():
    server = create_threading_server("127.0.0.1", 0, DummyHandler)

    try:
        assert server.daemon_threads is False
        assert server.block_on_close is True
        assert server.allow_reuse_address is True
        assert server.request_queue_size >= 64
    finally:
        server.server_close()


def test_create_threading_server_starts_runtime_lease_and_reconciles_orphans(
    tmp_path,
):
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "orphaned-run",
            "status": "running",
            "runtime_instance_id": "missing-instance",
            "started_at": "2026-01-01T00:00:00+00:00",
            "events": [],
        },
        str(tmp_path),
    )
    config = ServiceConfig(
        trace_dir=str(tmp_path),
        runtime_instance_heartbeat_seconds=0.05,
        runtime_orphaned_run_stale_seconds=0.2,
    )

    server = create_threading_server("127.0.0.1", 0, DummyHandler, config=config)
    lease_path = (
        tmp_path
        / ".runtime-instances"
        / f"{server.service_active_run_registry.instance_id}.json"
    )

    try:
        assert lease_path.exists()
        lease_payload = json.loads(lease_path.read_text(encoding="utf-8"))
        assert (
            lease_payload["runtime_instance_id"]
            == server.service_active_run_registry.instance_id
        )
        assert server.service_runtime_reconciliation["recovered_running"] == 1
        recovered = load_trace_by_run_id("orphaned-run", str(tmp_path))
        assert recovered is not None
        assert recovered["status"] == "failed"
        assert recovered["error_code"] == "agent_run_interrupted"
    finally:
        server.server_close()

    assert not lease_path.exists()


def test_create_threading_server_does_not_reconcile_live_instance_trace(tmp_path):
    live_lease = RuntimeInstanceLease(
        str(tmp_path),
        instance_id="live-instance",
        heartbeat_seconds=0.05,
    )
    live_lease.start()
    persist_trace(
        {
            "trace_type": "codex_runtime",
            "run_id": "live-run",
            "status": "running",
            "runtime_instance_id": "live-instance",
            "started_at": "2026-01-01T00:00:00+00:00",
            "events": [],
        },
        str(tmp_path),
    )
    config = ServiceConfig(
        trace_dir=str(tmp_path),
        runtime_instance_heartbeat_seconds=0.05,
        runtime_orphaned_run_stale_seconds=0.2,
    )

    server = create_threading_server("127.0.0.1", 0, DummyHandler, config=config)
    try:
        assert server.service_runtime_reconciliation["protected_live"] == 1
        protected = load_trace_by_run_id("live-run", str(tmp_path))
        assert protected is not None
        assert protected["status"] == "running"
    finally:
        server.server_close()
        live_lease.stop()


def test_server_close_keeps_runtime_lease_until_active_workers_finish(tmp_path):
    config = ServiceConfig(
        trace_dir=str(tmp_path),
        runtime_instance_heartbeat_seconds=0.05,
        runtime_orphaned_run_stale_seconds=0.2,
    )
    server = create_threading_server("127.0.0.1", 0, DummyHandler, config=config)
    registry = server.service_active_run_registry
    registry.register("active-run", "", RuntimeCancellationToken())
    lease_path = (
        tmp_path / ".runtime-instances" / f"{registry.instance_id}.json"
    )

    server.server_close()

    assert lease_path.exists()
    registry.complete("active-run")
    deadline = time.monotonic() + 2
    while lease_path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not lease_path.exists()
