from http.server import BaseHTTPRequestHandler

from self_correcting_langgraph_agent.service.runtime import (
    ServiceConcurrencyLimiter,
    ServiceConfig,
    ServiceIdempotencyCache,
    ServiceMetrics,
    ServiceRateLimiter,
    SqliteServiceIdempotencyCache,
)
from self_correcting_langgraph_agent.service.server import create_threading_server


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
