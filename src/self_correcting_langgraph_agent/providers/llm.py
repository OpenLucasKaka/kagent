from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from os import environ
from typing import Any, Callable, Dict, List, Mapping, Optional


@dataclass(frozen=True)
class LLMProviderConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: float = 30.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.25

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "LLMProviderConfig":
        source = env if env is not None else environ
        return cls(
            base_url=source.get("SELF_CORRECTING_LLM_BASE_URL", cls.base_url),
            api_key=source.get("SELF_CORRECTING_LLM_API_KEY", cls.api_key),
            model=source.get("SELF_CORRECTING_LLM_MODEL", cls.model),
            timeout_seconds=_env_float(
                source,
                "SELF_CORRECTING_LLM_TIMEOUT_SECONDS",
                cls.timeout_seconds,
            ),
            max_retries=_env_int(
                source,
                "SELF_CORRECTING_LLM_MAX_RETRIES",
                cls.max_retries,
            ),
            retry_backoff_seconds=_env_float(
                source,
                "SELF_CORRECTING_LLM_RETRY_BACKOFF_SECONDS",
                cls.retry_backoff_seconds,
            ),
        )

    def redacted_snapshot(self) -> Dict[str, str]:
        provider = "openai_compatible" if self.base_url and self.model else "unconfigured"
        return {
            "llm_provider": provider,
            "llm_base_url": self.base_url,
            "llm_model": self.model,
            "llm_api_key_configured": str(bool(self.api_key)).lower(),
            "llm_timeout_seconds": str(self.timeout_seconds),
            "llm_max_retries": str(self.max_retries),
            "llm_retry_backoff_seconds": str(self.retry_backoff_seconds),
        }

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")


class FakeLLMProvider:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.calls: List[Dict[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        return self.response_text


class SequentialFakeLLMProvider:
    def __init__(self, response_texts: List[str]) -> None:
        if not response_texts:
            raise ValueError("response_texts must be non-empty")
        self.response_texts = list(response_texts)
        self.calls: List[Dict[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        if len(self.calls) <= len(self.response_texts):
            return self.response_texts[len(self.calls) - 1]
        return self.response_texts[-1]


class OpenAICompatibleProvider:
    def __init__(
        self,
        config: LLMProviderConfig,
        *,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not config.base_url:
            raise ValueError("base_url is required")
        if not config.model:
            raise ValueError("model is required")
        self.config = config
        self._urlopen = urlopen
        self._sleep = sleep

    def complete(self, system: str, user: str) -> str:
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }
        headers = {
            "Content-Type": "application/json",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        body = self._request_json_with_retries(request)
        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("llm provider response missing message content") from exc

    def _request_json_with_retries(self, request: urllib.request.Request) -> Dict[str, Any]:
        max_attempts = self.config.max_retries + 1
        for attempt in range(max_attempts):
            try:
                with self._urlopen(
                    request,
                    timeout=self.config.timeout_seconds,
                ) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = _read_http_error_body(exc)
                if attempt >= max_attempts - 1 or not _is_retryable_provider_error(
                    exc,
                    body,
                ):
                    raise RuntimeError(
                        _provider_failure_message(exc, self.config.api_key, body)
                    ) from exc
                retry_delay = _provider_retry_delay_seconds(exc, self.config)
                if retry_delay:
                    self._sleep(retry_delay)
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt >= max_attempts - 1 or not _is_retryable_provider_error(exc):
                    raise RuntimeError(
                        _provider_failure_message(exc, self.config.api_key)
                    ) from exc
                if self.config.retry_backoff_seconds:
                    self._sleep(self.config.retry_backoff_seconds)
        raise RuntimeError("llm provider request failed")


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


def _is_retryable_provider_error(exc: BaseException, body: str = "") -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return (
            exc.code == 429
            or 500 <= exc.code <= 599
            or (exc.code == 400 and "model unloaded" in body.lower())
        )
    return isinstance(exc, (urllib.error.URLError, TimeoutError))


def _provider_retry_delay_seconds(
    exc: BaseException,
    config: LLMProviderConfig,
) -> float:
    if isinstance(exc, urllib.error.HTTPError):
        retry_after = _numeric_retry_after_seconds(exc)
        if retry_after is not None:
            return retry_after
    return config.retry_backoff_seconds


def _numeric_retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after is None:
        return None
    try:
        seconds = float(str(retry_after).strip())
    except ValueError:
        return None
    if seconds < 0:
        return None
    return seconds


def _provider_failure_message(
    exc: BaseException,
    api_key: str,
    body: str = "",
) -> str:
    message = "llm provider request failed"
    if isinstance(exc, urllib.error.HTTPError):
        redacted_body = _redact_provider_text(body, api_key)
        if redacted_body:
            return f"{message}: http_status={exc.code} body={redacted_body}"
        return f"{message}: http_status={exc.code} reason={exc.reason}"
    if isinstance(exc, urllib.error.URLError):
        reason = _redact_provider_text(str(exc.reason), api_key)
        if reason:
            return f"{message}: reason={reason}"
    if isinstance(exc, TimeoutError):
        return f"{message}: reason=timeout"
    return message


def _read_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read()
    except OSError:
        return ""
    if not body:
        return ""
    return body.decode("utf-8", errors="replace")[:500]


def _redact_provider_text(text: str, api_key: str) -> str:
    redacted = text
    if api_key:
        redacted = redacted.replace(api_key, "[redacted]")
    return re.sub(r"sk-[A-Za-z0-9:_-]{8,}", "[redacted]", redacted)
