from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Type

from kagent.service.active_runs import ActiveRunRegistry
from kagent.service.runtime import (
    ServiceConcurrencyLimiter,
    ServiceConfig,
    ServiceIdempotencyCache,
    ServiceMetrics,
    ServiceRateLimiter,
    SqliteServiceIdempotencyCache,
)
from kagent.service.runtime_recovery import (
    RuntimeInstanceLease,
    reconcile_orphaned_runtime_traces,
)


class ProductionThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = True
    request_queue_size = 64

    def server_close(self) -> None:
        super().server_close()
        lease = getattr(self, "service_runtime_instance_lease", None)
        registry = getattr(self, "service_active_run_registry", None)
        if isinstance(lease, RuntimeInstanceLease) and isinstance(
            registry, ActiveRunRegistry
        ):
            lease.stop_when_idle(registry)


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
    server.service_active_run_registry = ActiveRunRegistry()  # type: ignore[attr-defined]
    if server.service_config.idempotency_cache_path:  # type: ignore[attr-defined]
        server.service_idempotency_cache = SqliteServiceIdempotencyCache(  # type: ignore[attr-defined]
            max_entries=server.service_config.idempotency_cache_size,  # type: ignore[attr-defined]
            database_path=server.service_config.idempotency_cache_path,  # type: ignore[attr-defined]
        )
    else:
        server.service_idempotency_cache = ServiceIdempotencyCache(  # type: ignore[attr-defined]
            max_entries=server.service_config.idempotency_cache_size  # type: ignore[attr-defined]
        )
    server.service_runtime_instance_lease = None  # type: ignore[attr-defined]
    server.service_runtime_reconciliation = {  # type: ignore[attr-defined]
        "enabled": False,
        "reason": "trace_persistence_disabled",
    }
    if server.service_config.trace_dir:  # type: ignore[attr-defined]
        lease = RuntimeInstanceLease(
            server.service_config.trace_dir,  # type: ignore[attr-defined]
            instance_id=server.service_active_run_registry.instance_id,  # type: ignore[attr-defined]
            heartbeat_seconds=(
                server.service_config.runtime_instance_heartbeat_seconds  # type: ignore[attr-defined]
            ),
        )
        server.service_runtime_instance_lease = lease  # type: ignore[attr-defined]
        try:
            lease.start()
            server.service_runtime_reconciliation = (  # type: ignore[attr-defined]
                reconcile_orphaned_runtime_traces(
                    server.service_config.trace_dir,  # type: ignore[attr-defined]
                    current_instance_id=(
                        server.service_active_run_registry.instance_id  # type: ignore[attr-defined]
                    ),
                    stale_after_seconds=(
                        server.service_config.runtime_orphaned_run_stale_seconds  # type: ignore[attr-defined]
                    ),
                )
            )
        except OSError as exc:
            lease.stop()
            server.service_runtime_instance_lease = None  # type: ignore[attr-defined]
            server.service_runtime_reconciliation = {  # type: ignore[attr-defined]
                "enabled": False,
                "reason": "trace_persistence_unavailable",
                "error_type": type(exc).__name__,
            }
        except Exception:
            lease.stop()
            super(ProductionThreadingHTTPServer, server).server_close()
            raise
    return server
