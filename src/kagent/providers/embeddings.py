from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from os import environ
from typing import Any, Callable, Dict, List, Mapping, Optional


@dataclass(frozen=True)
class EmbeddingProviderConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: float = 30.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.25

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
    ) -> "EmbeddingProviderConfig":
        source = env if env is not None else environ
        return cls(
            base_url=source.get(
                "KAGENT_EMBEDDING_BASE_URL",
                source.get("KAGENT_LLM_BASE_URL", cls.base_url),
            ),
            api_key=source.get(
                "KAGENT_EMBEDDING_API_KEY",
                source.get("KAGENT_LLM_API_KEY", cls.api_key),
            ),
            model=source.get("KAGENT_EMBEDDING_MODEL", cls.model),
            timeout_seconds=_env_float(
                source,
                "KAGENT_EMBEDDING_TIMEOUT_SECONDS",
                cls.timeout_seconds,
            ),
            max_retries=_env_int(
                source,
                "KAGENT_EMBEDDING_MAX_RETRIES",
                cls.max_retries,
            ),
            retry_backoff_seconds=_env_float(
                source,
                "KAGENT_EMBEDDING_RETRY_BACKOFF_SECONDS",
                cls.retry_backoff_seconds,
            ),
        )

    def redacted_snapshot(self) -> Dict[str, str]:
        provider = "openai_compatible" if self.base_url and self.model else "unconfigured"
        return {
            "embedding_provider": provider,
            "embedding_base_url": self.base_url,
            "embedding_model": self.model,
            "embedding_api_key_configured": str(bool(self.api_key)).lower(),
            "embedding_timeout_seconds": str(self.timeout_seconds),
            "embedding_max_retries": str(self.max_retries),
            "embedding_retry_backoff_seconds": str(self.retry_backoff_seconds),
        }

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("embedding timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("embedding max_retries must be non-negative")
        if self.retry_backoff_seconds < 0:
            raise ValueError("embedding retry_backoff_seconds must be non-negative")


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        config: EmbeddingProviderConfig,
        *,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not config.base_url:
            raise ValueError("embedding base_url is required")
        if not config.model:
            raise ValueError("embedding model is required")
        self.config = config
        self._urlopen = urlopen
        self._sleep = sleep

    def embed(self, text: str) -> List[float]:
        normalized_text = str(text).strip()
        if not normalized_text:
            raise ValueError("embedding text is required")
        request = self._embedding_request(normalized_text)
        body = self._request_json_with_retries(request)
        try:
            vector = body["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("embedding provider response missing vector") from exc
        if not isinstance(vector, list) or not vector:
            raise RuntimeError("embedding provider response missing vector")
        normalized_vector = []
        for item in vector:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise RuntimeError("embedding provider vector must contain numbers")
            normalized_vector.append(float(item))
        return normalized_vector

    def _embedding_request(self, text: str) -> urllib.request.Request:
        endpoint = self.config.base_url.rstrip("/") + "/embeddings"
        payload = {
            "input": text,
            "model": self.config.model,
        }
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

    def _request_json_with_retries(
        self,
        request: urllib.request.Request,
    ) -> Dict[str, Any]:
        max_attempts = self.config.max_retries + 1
        for attempt in range(max_attempts):
            try:
                with self._urlopen(
                    request,
                    timeout=self.config.timeout_seconds,
                ) as response:
                    body = json.loads(response.read().decode("utf-8"))
                    if int(response.status) < 200 or int(response.status) >= 300:
                        raise RuntimeError("embedding provider request failed")
                    if not isinstance(body, dict):
                        raise RuntimeError("embedding provider response must be an object")
                    return body
            except urllib.error.HTTPError as exc:
                if attempt >= max_attempts - 1 or not _is_retryable_embedding_error(
                    exc
                ):
                    raise RuntimeError(
                        f"embedding provider request failed: http_status={exc.code}"
                    ) from exc
                if self.config.retry_backoff_seconds:
                    self._sleep(self.config.retry_backoff_seconds)
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt >= max_attempts - 1:
                    raise RuntimeError(
                        "embedding provider request failed: network_error"
                    ) from exc
                if self.config.retry_backoff_seconds:
                    self._sleep(self.config.retry_backoff_seconds)
        raise RuntimeError("embedding provider request failed")


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    value = env.get(name)
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name)
    if value in {None, ""}:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _is_retryable_embedding_error(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or 500 <= exc.code <= 599
    return isinstance(exc, (urllib.error.URLError, TimeoutError))
