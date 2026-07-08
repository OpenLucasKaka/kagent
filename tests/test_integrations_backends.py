from __future__ import annotations

import socket
import threading

from kagent.integrations.backends import (
    ExternalBackendConfig,
    check_external_backends,
)


def test_external_backend_config_reads_redacted_snapshot():
    config = ExternalBackendConfig.from_env(
        {
            "KAGENT_REDIS_URL": "redis://localhost:6379/0",
            "KAGENT_MILVUS_URL": "http://milvus.internal:19530/healthz",
            "KAGENT_KAFKA_AUDIT_URL": "http://kafka-rest.internal:8082/topics/audit",
            "KAGENT_KAFKA_AUDIT_TOPIC": "kagent-audit",
            "KAGENT_EXTERNAL_BACKEND_TIMEOUT_SECONDS": "1.5",
        }
    )

    assert config.redis_url == "redis://localhost:6379/0"
    assert config.milvus_url == "http://milvus.internal:19530/healthz"
    assert config.kafka_audit_url == "http://kafka-rest.internal:8082/topics/audit"
    assert config.kafka_audit_topic == "kagent-audit"
    assert config.timeout_seconds == 1.5
    assert config.redacted_snapshot() == {
        "redis_short_term_memory": "enabled",
        "milvus_long_term_memory": "enabled",
        "kafka_audit_sink": "enabled",
        "kafka_audit_topic_configured": "true",
        "external_backend_timeout_seconds": "1.5",
    }


def test_check_external_backends_pings_configured_redis():
    server = _RedisPingServer()
    server.start()
    try:
        checks = check_external_backends(
            ExternalBackendConfig(
                redis_url=f"redis://127.0.0.1:{server.port}/0",
                timeout_seconds=1.0,
            )
        )
    finally:
        server.stop()

    assert checks == {"redis_short_term_memory": "ok"}


class _RedisPingServer:
    def __init__(self) -> None:
        self._socket = socket.socket()
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(1)
        self.port = int(self._socket.getsockname()[1])
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._socket.close()
        self._thread.join(timeout=1)

    def _serve(self) -> None:
        try:
            conn, _addr = self._socket.accept()
        except OSError:
            return
        with conn:
            conn.recv(1024)
            conn.sendall(b"+PONG\r\n")
