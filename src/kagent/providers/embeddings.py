from __future__ import annotations

import json
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
        )

    def redacted_snapshot(self) -> Dict[str, str]:
        provider = "openai_compatible" if self.base_url and self.model else "unconfigured"
        return {
            "embedding_provider": provider,
            "embedding_base_url": self.base_url,
            "embedding_model": self.model,
            "embedding_api_key_configured": str(bool(self.api_key)).lower(),
            "embedding_timeout_seconds": str(self.timeout_seconds),
        }

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("embedding timeout_seconds must be positive")


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        config: EmbeddingProviderConfig,
        *,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        if not config.base_url:
            raise ValueError("embedding base_url is required")
        if not config.model:
            raise ValueError("embedding model is required")
        self.config = config
        self._urlopen = urlopen

    def embed(self, text: str) -> List[float]:
        normalized_text = str(text).strip()
        if not normalized_text:
            raise ValueError("embedding text is required")
        request = self._embedding_request(normalized_text)
        with self._urlopen(request, timeout=self.config.timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
            if int(response.status) < 200 or int(response.status) >= 300:
                raise RuntimeError("embedding provider request failed")
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


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    value = env.get(name)
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
