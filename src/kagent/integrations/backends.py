from __future__ import annotations

import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from os import environ
from typing import Dict, Mapping, Optional


@dataclass(frozen=True)
class ExternalBackendConfig:
    redis_url: str = ""
    milvus_url: str = ""
    kafka_audit_url: str = ""
    kafka_audit_topic: str = ""
    timeout_seconds: float = 2.0

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
    ) -> "ExternalBackendConfig":
        source = env if env is not None else environ
        return cls(
            redis_url=source.get("KAGENT_REDIS_URL", cls.redis_url),
            milvus_url=source.get("KAGENT_MILVUS_URL", cls.milvus_url),
            kafka_audit_url=source.get(
                "KAGENT_KAFKA_AUDIT_URL",
                cls.kafka_audit_url,
            ),
            kafka_audit_topic=source.get(
                "KAGENT_KAFKA_AUDIT_TOPIC",
                cls.kafka_audit_topic,
            ),
            timeout_seconds=_env_float(
                source,
                "KAGENT_EXTERNAL_BACKEND_TIMEOUT_SECONDS",
                cls.timeout_seconds,
            ),
        )

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("external backend timeout_seconds must be positive")

    def redacted_snapshot(self) -> Dict[str, str]:
        return {
            "redis_short_term_memory": "enabled" if self.redis_url else "disabled",
            "milvus_long_term_memory": "enabled" if self.milvus_url else "disabled",
            "kafka_audit_sink": "enabled" if self.kafka_audit_url else "disabled",
            "kafka_audit_topic_configured": str(bool(self.kafka_audit_topic)).lower(),
            "external_backend_timeout_seconds": str(self.timeout_seconds),
        }


def check_external_backends(config: ExternalBackendConfig) -> Dict[str, str]:
    checks: Dict[str, str] = {}
    if config.redis_url:
        checks["redis_short_term_memory"] = _check(
            lambda: _redis_ping(config.redis_url, timeout_seconds=config.timeout_seconds),
            "redis_unavailable",
        )
    if config.milvus_url:
        checks["milvus_long_term_memory"] = _check(
            lambda: _http_get_ok(
                config.milvus_url,
                timeout_seconds=config.timeout_seconds,
            ),
            "milvus_unavailable",
        )
    if config.kafka_audit_url:
        checks["kafka_audit_sink"] = _check(
            lambda: _http_get_ok(
                config.kafka_audit_url,
                timeout_seconds=config.timeout_seconds,
            ),
            "kafka_audit_unavailable",
        )
    return checks


def _check(check, failure_code: str) -> str:
    try:
        check()
    except Exception:
        return f"failed: {failure_code}"
    return "ok"


def _redis_ping(redis_url: str, *, timeout_seconds: float) -> None:
    parsed = urllib.parse.urlparse(redis_url)
    if parsed.scheme != "redis":
        raise ValueError("redis url must use redis://")
    if not parsed.hostname:
        raise ValueError("redis url host is required")
    port = parsed.port or 6379
    with socket.create_connection(
        (parsed.hostname, port),
        timeout=timeout_seconds,
    ) as conn:
        conn.settimeout(timeout_seconds)
        conn.sendall(b"*1\r\n$4\r\nPING\r\n")
        response = conn.recv(64)
    if not response.startswith(b"+PONG"):
        raise RuntimeError("redis ping failed")


def _http_get_ok(url: str, *, timeout_seconds: float) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("backend url must use http:// or https://")
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(response.status)
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
    if status_code < 200 or status_code >= 300:
        raise RuntimeError("backend health check failed")


def _env_float(source: Mapping[str, str], name: str, default: float) -> float:
    value = source.get(name, "")
    if value == "":
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a float") from exc
