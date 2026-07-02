from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Type

from self_correcting_langgraph_agent.service.runtime import (
    ServiceConcurrencyLimiter,
    ServiceConfig,
    ServiceIdempotencyCache,
    ServiceMetrics,
    ServiceRateLimiter,
    SqliteServiceIdempotencyCache,
)


class ProductionThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = True
    request_queue_size = 64


def create_threading_server(
    host: str,
    port: int,
    handler_class: Type[BaseHTTPRequestHandler],
    *,
    config: Optional[ServiceConfig] = None,
) -> ThreadingHTTPServer:
    server = ProductionThreadingHTTPServer((host, port), handler_class)
    bound_host, bound_port = server.server_address
    server.service_config = config or ServiceConfig(  # type: ignore[attr-defined]
        host=str(bound_host),
        port=int(bound_port),
    )
    server.service_metrics = ServiceMetrics()  # type: ignore[attr-defined]
    server.service_rate_limiter = ServiceRateLimiter(  # type: ignore[attr-defined]
        limit_per_minute=server.service_config.rate_limit_per_minute  # type: ignore[attr-defined]
    )
    server.service_concurrency_limiter = ServiceConcurrencyLimiter(  # type: ignore[attr-defined]
        max_concurrent_runs=server.service_config.max_concurrent_runs  # type: ignore[attr-defined]
    )
    if server.service_config.idempotency_cache_path:  # type: ignore[attr-defined]
        server.service_idempotency_cache = SqliteServiceIdempotencyCache(  # type: ignore[attr-defined]
            max_entries=server.service_config.idempotency_cache_size,  # type: ignore[attr-defined]
            database_path=server.service_config.idempotency_cache_path,  # type: ignore[attr-defined]
        )
    else:
        server.service_idempotency_cache = ServiceIdempotencyCache(  # type: ignore[attr-defined]
            max_entries=server.service_config.idempotency_cache_size  # type: ignore[attr-defined]
        )
    return server
