from __future__ import annotations

import json
import os
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from enum import Enum
from os import environ
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional

from kagent.runtime.redaction import REDACTED_VALUE, redact_runtime_text

DEFAULT_LLM_MODEL = "qwen3.5-122b-a10b"
PROVIDER_CONFIG_SCHEMA_VERSION = "1"


class ProviderKind(str, Enum):
    OPENAI_COMPATIBLE = "openai_compatible"
    DEEPSEEK = "deepseek"
    QWEN_OPENAI_COMPATIBLE = "qwen_openai_compatible"
    OLLAMA_OPENAI_COMPATIBLE = "ollama_openai_compatible"


@dataclass(frozen=True)
class LLMProviderConfig:
    provider: ProviderKind = ProviderKind.OPENAI_COMPATIBLE
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: float = 30.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.25

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "LLMProviderConfig":
        source = env if env is not None else environ
        base_url = source.get("KAGENT_LLM_BASE_URL", cls.base_url)
        model = source.get("KAGENT_LLM_MODEL", cls.model)
        return cls(
            provider=_provider_from_env(source, base_url=base_url, model=model),
            base_url=base_url,
            api_key=source.get("KAGENT_LLM_API_KEY", cls.api_key),
            model=model,
            timeout_seconds=_env_float(
                source,
                "KAGENT_LLM_TIMEOUT_SECONDS",
                cls.timeout_seconds,
            ),
            max_retries=_env_int(
                source,
                "KAGENT_LLM_MAX_RETRIES",
                cls.max_retries,
            ),
            retry_backoff_seconds=_env_float(
                source,
                "KAGENT_LLM_RETRY_BACKOFF_SECONDS",
                cls.retry_backoff_seconds,
            ),
        )

    @classmethod
    def from_sources(
        cls,
        env: Optional[Mapping[str, str]] = None,
        config_path: str = "",
    ) -> "LLMProviderConfig":
        source = env if env is not None else environ
        file_config = load_provider_config(config_path)
        merged = {
            "KAGENT_LLM_PROVIDER": file_config.provider.value,
            "KAGENT_LLM_BASE_URL": file_config.base_url,
            "KAGENT_LLM_API_KEY": file_config.api_key,
            "KAGENT_LLM_MODEL": file_config.model,
            "KAGENT_LLM_TIMEOUT_SECONDS": str(file_config.timeout_seconds),
            "KAGENT_LLM_MAX_RETRIES": str(file_config.max_retries),
            "KAGENT_LLM_RETRY_BACKOFF_SECONDS": str(
                file_config.retry_backoff_seconds
            ),
        }
        for key, value in source.items():
            if key.startswith("KAGENT_LLM_") and value != "":
                merged[key] = value
        provider_overridden = bool(source.get("KAGENT_LLM_PROVIDER", "").strip())
        endpoint_overridden = bool(
            source.get("KAGENT_LLM_BASE_URL", "").strip()
            or source.get("KAGENT_LLM_MODEL", "").strip()
        )
        if endpoint_overridden and not provider_overridden:
            merged["KAGENT_LLM_PROVIDER"] = ""
        return cls.from_env(merged)

    def redacted_snapshot(self) -> Dict[str, str]:
        provider = self.provider.value if self.base_url and self.model else "unconfigured"
        display_name = (
            provider_display_name(self.provider)
            if self.base_url and self.model
            else "Unconfigured"
        )
        base_url_configured = bool(self.base_url)
        return {
            "llm_provider": provider,
            "llm_provider_display_name": display_name,
            "llm_base_url": "configured" if base_url_configured else "",
            "llm_base_url_configured": str(base_url_configured).lower(),
            "llm_model": self.model,
            "llm_api_key_configured": str(bool(self.api_key)).lower(),
            "llm_timeout_seconds": str(self.timeout_seconds),
            "llm_max_retries": str(self.max_retries),
            "llm_retry_backoff_seconds": str(self.retry_backoff_seconds),
        }

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", normalize_provider_kind(self.provider))
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")


def default_provider_config_path(env: Optional[Mapping[str, str]] = None) -> str:
    source = env if env is not None else environ
    if source.get("KAGENT_LLM_CONFIG_PATH"):
        return source["KAGENT_LLM_CONFIG_PATH"]
    config_home = source.get("XDG_CONFIG_HOME")
    if config_home:
        return str(Path(config_home) / "kagent" / "provider.json")
    return str(Path.home() / ".config" / "kagent" / "provider.json")


def load_provider_config(path: str = "") -> LLMProviderConfig:
    config_path = Path(path or default_provider_config_path())
    if not config_path.exists():
        return LLMProviderConfig()
    _validate_provider_config_path_for_read(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("provider config must be a JSON object")
    if str(payload.get("schema_version", "")) != PROVIDER_CONFIG_SCHEMA_VERSION:
        raise ValueError("provider config schema_version is unsupported")
    provider = normalize_provider_kind(str(payload.get("provider", "openai_compatible")))
    return LLMProviderConfig(
        provider=provider,
        base_url=str(payload.get("base_url", "")),
        api_key=str(payload.get("api_key", "")),
        model=str(payload.get("model", "")),
        timeout_seconds=float(
            payload.get("timeout_seconds", LLMProviderConfig.timeout_seconds)
        ),
        max_retries=int(payload.get("max_retries", LLMProviderConfig.max_retries)),
        retry_backoff_seconds=float(
            payload.get(
                "retry_backoff_seconds",
                LLMProviderConfig.retry_backoff_seconds,
            )
        ),
    )


def save_provider_config(config: LLMProviderConfig, path: str = "") -> str:
    config_path = Path(path or default_provider_config_path())
    _validate_provider_config_path_for_write(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(config_path.parent, 0o700)
    payload = {
        "schema_version": PROVIDER_CONFIG_SCHEMA_VERSION,
        "provider": config.provider.value,
        "base_url": config.base_url,
        "api_key": config.api_key,
        "model": config.model,
        "timeout_seconds": config.timeout_seconds,
        "max_retries": config.max_retries,
        "retry_backoff_seconds": config.retry_backoff_seconds,
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(config_path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(config_path, 0o600)
    return str(config_path)


def normalize_provider_kind(value: object) -> ProviderKind:
    if isinstance(value, ProviderKind):
        return value
    normalized = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "": ProviderKind.OPENAI_COMPATIBLE,
        "openai": ProviderKind.OPENAI_COMPATIBLE,
        "openai_compatible": ProviderKind.OPENAI_COMPATIBLE,
        "openai-compatible": ProviderKind.OPENAI_COMPATIBLE,
        "deepseek": ProviderKind.DEEPSEEK,
        "qwen": ProviderKind.QWEN_OPENAI_COMPATIBLE,
        "dashscope": ProviderKind.QWEN_OPENAI_COMPATIBLE,
        "qwen_openai_compatible": ProviderKind.QWEN_OPENAI_COMPATIBLE,
        "qwen-compatible": ProviderKind.QWEN_OPENAI_COMPATIBLE,
        "ollama": ProviderKind.OLLAMA_OPENAI_COMPATIBLE,
        "ollama_openai_compatible": ProviderKind.OLLAMA_OPENAI_COMPATIBLE,
    }
    if normalized in aliases:
        return aliases[normalized]
    try:
        return ProviderKind(normalized)
    except ValueError as exc:
        raise ValueError(f"unsupported llm provider: {value}") from exc


def detect_provider_kind(base_url: str, model: str = "") -> ProviderKind:
    haystack = f"{base_url} {model}".strip().lower()
    if not haystack:
        return ProviderKind.OPENAI_COMPATIBLE
    if "deepseek" in haystack:
        return ProviderKind.DEEPSEEK
    if any(marker in haystack for marker in ("dashscope", "aliyuncs", "qwen")):
        return ProviderKind.QWEN_OPENAI_COMPATIBLE
    if any(marker in haystack for marker in ("localhost:11434", "127.0.0.1:11434", "ollama")):
        return ProviderKind.OLLAMA_OPENAI_COMPATIBLE
    return ProviderKind.OPENAI_COMPATIBLE


def provider_display_name(provider: object) -> str:
    try:
        kind = normalize_provider_kind(provider)
    except ValueError:
        kind = ProviderKind.OPENAI_COMPATIBLE
    names = {
        ProviderKind.OPENAI_COMPATIBLE: "OpenAI-compatible",
        ProviderKind.DEEPSEEK: "DeepSeek",
        ProviderKind.QWEN_OPENAI_COMPATIBLE: "Qwen",
        ProviderKind.OLLAMA_OPENAI_COMPATIBLE: "Ollama",
    }
    return names[kind]


def provider_setup_options(
    default_model: str = DEFAULT_LLM_MODEL,
) -> List[Dict[str, object]]:
    return [
        {
            "provider": ProviderKind.QWEN_OPENAI_COMPATIBLE,
            "label": "Qwen / DashScope",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": default_model,
            "api_key_required": True,
        },
        {
            "provider": ProviderKind.DEEPSEEK,
            "label": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key_required": True,
        },
        {
            "provider": ProviderKind.OLLAMA_OPENAI_COMPATIBLE,
            "label": "Ollama local",
            "base_url": "http://localhost:11434/v1",
            "model": "llama3",
            "api_key_required": False,
        },
        {
            "provider": ProviderKind.OPENAI_COMPATIBLE,
            "label": "OpenAI-compatible / custom",
            "base_url": "",
            "model": default_model,
            "api_key_required": False,
        },
    ]


def missing_provider_config_fields(config: LLMProviderConfig) -> List[str]:
    missing = []
    if not config.base_url.strip():
        missing.append("KAGENT_LLM_BASE_URL")
    if not config.model.strip():
        missing.append("KAGENT_LLM_MODEL")
    if config.provider in {
        ProviderKind.QWEN_OPENAI_COMPATIBLE,
        ProviderKind.DEEPSEEK,
    } and not config.api_key.strip():
        missing.append("KAGENT_LLM_API_KEY")
    return missing


def validate_provider_setup_config(config: LLMProviderConfig) -> None:
    if not config.base_url.strip():
        raise ValueError("base_url is required")
    endpoint = urllib.parse.urlsplit(config.base_url)
    if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
        raise ValueError("base_url must be an absolute http or https URL")
    if not config.model.strip():
        raise ValueError("model is required")
    if config.provider in {
        ProviderKind.QWEN_OPENAI_COMPATIBLE,
        ProviderKind.DEEPSEEK,
    } and not config.api_key.strip():
        raise ValueError("api_key is required for this provider")


def _provider_from_env(
    env: Mapping[str, str],
    *,
    base_url: str,
    model: str,
) -> ProviderKind:
    explicit = env.get("KAGENT_LLM_PROVIDER", "")
    if explicit.strip():
        return normalize_provider_kind(explicit)
    return detect_provider_kind(base_url, model)


def _validate_provider_config_path_for_read(path: Path) -> None:
    _reject_symlink_path(path)
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise ValueError("provider config file must be owner-only")


def _validate_provider_config_path_for_write(path: Path) -> None:
    _reject_symlink_path(path)
    if path.parent.exists():
        _reject_symlink_path(path.parent)
        os.chmod(path.parent, 0o700)
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != 0o600:
            raise ValueError("provider config file must be owner-only")


def _reject_symlink_path(path: Path) -> None:
    current = Path(path.anchor or ".")
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            if current.parent == Path(current.anchor) and current.lstat().st_uid == 0:
                continue
            raise ValueError("provider config path must not contain symlinks")


class FakeLLMProvider:
    def __init__(self, response_text: str, stream_chunks: Optional[List[str]] = None) -> None:
        self.response_text = response_text
        self.stream_chunks = list(stream_chunks) if stream_chunks is not None else [response_text]
        self.calls: List[Dict[str, str]] = []
        self.stream_calls: List[Dict[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        return self.response_text

    def stream_complete(self, system: str, user: str) -> Iterator[str]:
        self.stream_calls.append({"system": system, "user": user})
        yield from self.stream_chunks


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
        self._last_request_diagnostics: Dict[str, str] = {}

    def complete(self, system: str, user: str) -> str:
        request = self._chat_completion_request(system, user, stream=False)
        body = self._request_json_with_retries(request)
        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            self._mark_request_diagnostics_failed("response_error")
            raise RuntimeError("llm provider response missing message content") from exc

    def stream_complete(self, system: str, user: str) -> Iterator[str]:
        request = self._chat_completion_request(system, user, stream=True)
        yield from self._request_stream_with_retries(request)

    def request_diagnostics(self) -> Dict[str, str]:
        return dict(self._last_request_diagnostics)

    def _chat_completion_request(
        self,
        system: str,
        user: str,
        *,
        stream: bool,
    ) -> urllib.request.Request:
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }
        if stream:
            payload["stream"] = True
        headers = {
            "Content-Type": "application/json",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

    def _request_json_with_retries(self, request: urllib.request.Request) -> Dict[str, Any]:
        max_attempts = self.config.max_retries + 1
        started = time.perf_counter()
        retry_count = 0
        for attempt in range(max_attempts):
            try:
                with self._urlopen(
                    request,
                    timeout=self.config.timeout_seconds,
                ) as response:
                    body = json.loads(response.read().decode("utf-8"))
                    self._set_request_diagnostics(
                        started_at=started,
                        attempt_count=attempt + 1,
                        retry_count=retry_count,
                        stream=False,
                        status="ok",
                    )
                    return body
            except urllib.error.HTTPError as exc:
                body = _read_http_error_body(exc)
                if attempt >= max_attempts - 1 or not _is_retryable_provider_error(
                    exc,
                    body,
                ):
                    self._set_request_diagnostics(
                        started_at=started,
                        attempt_count=attempt + 1,
                        retry_count=retry_count,
                        stream=False,
                        status="failed",
                        error_type=_provider_error_type(exc),
                        http_status=str(exc.code),
                        retryable_reason=_provider_retryable_reason(exc, body),
                    )
                    raise RuntimeError(
                        _provider_failure_message(exc, self.config.api_key, body)
                    ) from exc
                retry_count += 1
                retry_delay = _provider_retry_delay_seconds(exc, self.config)
                if retry_delay:
                    self._sleep(retry_delay)
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt >= max_attempts - 1 or not _is_retryable_provider_error(exc):
                    self._set_request_diagnostics(
                        started_at=started,
                        attempt_count=attempt + 1,
                        retry_count=retry_count,
                        stream=False,
                        status="failed",
                        error_type=_provider_error_type(exc),
                    )
                    raise RuntimeError(
                        _provider_failure_message(exc, self.config.api_key)
                    ) from exc
                retry_count += 1
                if self.config.retry_backoff_seconds:
                    self._sleep(self.config.retry_backoff_seconds)
        self._set_request_diagnostics(
            started_at=started,
            attempt_count=max_attempts,
            retry_count=retry_count,
            stream=False,
            status="failed",
            error_type="exhausted",
        )
        raise RuntimeError("llm provider request failed")

    def _request_stream_with_retries(
        self,
        request: urllib.request.Request,
    ) -> Iterator[str]:
        max_attempts = self.config.max_retries + 1
        started = time.perf_counter()
        retry_count = 0
        for attempt in range(max_attempts):
            try:
                with self._urlopen(
                    request,
                    timeout=self.config.timeout_seconds,
                ) as response:
                    try:
                        yield from _stream_openai_chat_completion_chunks(response)
                    except RuntimeError:
                        self._set_request_diagnostics(
                            started_at=started,
                            attempt_count=attempt + 1,
                            retry_count=retry_count,
                            stream=True,
                            status="failed",
                            error_type="response_error",
                        )
                        raise
                    self._set_request_diagnostics(
                        started_at=started,
                        attempt_count=attempt + 1,
                        retry_count=retry_count,
                        stream=True,
                        status="ok",
                    )
                    return
            except urllib.error.HTTPError as exc:
                body = _read_http_error_body(exc)
                if attempt >= max_attempts - 1 or not _is_retryable_provider_error(
                    exc,
                    body,
                ):
                    self._set_request_diagnostics(
                        started_at=started,
                        attempt_count=attempt + 1,
                        retry_count=retry_count,
                        stream=True,
                        status="failed",
                        error_type=_provider_error_type(exc),
                        http_status=str(exc.code),
                        retryable_reason=_provider_retryable_reason(exc, body),
                    )
                    raise RuntimeError(
                        _provider_failure_message(exc, self.config.api_key, body)
                    ) from exc
                retry_count += 1
                retry_delay = _provider_retry_delay_seconds(exc, self.config)
                if retry_delay:
                    self._sleep(retry_delay)
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt >= max_attempts - 1 or not _is_retryable_provider_error(exc):
                    self._set_request_diagnostics(
                        started_at=started,
                        attempt_count=attempt + 1,
                        retry_count=retry_count,
                        stream=True,
                        status="failed",
                        error_type=_provider_error_type(exc),
                    )
                    raise RuntimeError(
                        _provider_failure_message(exc, self.config.api_key)
                    ) from exc
                retry_count += 1
                if self.config.retry_backoff_seconds:
                    self._sleep(self.config.retry_backoff_seconds)
        self._set_request_diagnostics(
            started_at=started,
            attempt_count=max_attempts,
            retry_count=retry_count,
            stream=True,
            status="failed",
            error_type="exhausted",
        )
        raise RuntimeError("llm provider request failed")

    def _set_request_diagnostics(
        self,
        *,
        started_at: float,
        attempt_count: int,
        retry_count: int,
        stream: bool,
        status: str,
        error_type: str = "",
        http_status: str = "",
        retryable_reason: str = "",
    ) -> None:
        diagnostics = {
            "attempt_count": str(max(0, attempt_count)),
            "retry_count": str(max(0, retry_count)),
            "status": status,
            "stream": str(stream).lower(),
            "duration_seconds": f"{time.perf_counter() - started_at:.4f}",
        }
        if error_type:
            diagnostics["error_type"] = error_type
        if http_status:
            diagnostics["http_status"] = http_status
        if retryable_reason:
            diagnostics["retryable_reason"] = retryable_reason
        self._last_request_diagnostics = diagnostics

    def _mark_request_diagnostics_failed(self, error_type: str) -> None:
        diagnostics = dict(self._last_request_diagnostics)
        if not diagnostics:
            return
        diagnostics["status"] = "failed"
        diagnostics["error_type"] = error_type
        self._last_request_diagnostics = diagnostics


def build_llm_provider(
    config: LLMProviderConfig,
    *,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> OpenAICompatibleProvider:
    # DeepSeek, Qwen, Ollama, and many company gateways expose the same
    # /v1/chat/completions contract. Native protocol adapters can branch here.
    normalize_provider_kind(config.provider)
    return OpenAICompatibleProvider(config, urlopen=urlopen, sleep=sleep)


def _stream_openai_chat_completion_chunks(response: Any) -> Iterator[str]:
    while True:
        raw_line = response.readline()
        if raw_line == b"" or raw_line == "":
            return
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
        line = line.strip()
        if not line or not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if data == "[DONE]":
            return
        try:
            payload = json.loads(data)
            content = payload["choices"][0]["delta"].get("content", "")
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise RuntimeError("llm provider stream chunk missing delta content") from exc
        if content:
            yield str(content)


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
            or _provider_retryable_reason(exc, body) == "model_unloaded"
        )
    return isinstance(exc, (urllib.error.URLError, TimeoutError))


def _provider_retryable_reason(exc: BaseException, body: str = "") -> str:
    if (
        isinstance(exc, urllib.error.HTTPError)
        and exc.code == 400
        and "model unloaded" in body.lower()
    ):
        return "model_unloaded"
    return ""


def _provider_retry_delay_seconds(
    exc: BaseException,
    config: LLMProviderConfig,
) -> float:
    if isinstance(exc, urllib.error.HTTPError):
        retry_after = _numeric_retry_after_seconds(exc)
        if retry_after is not None:
            return retry_after
    return config.retry_backoff_seconds


def _provider_error_type(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return "http_error"
    if isinstance(exc, urllib.error.URLError):
        return "url_error"
    if isinstance(exc, TimeoutError):
        return "timeout"
    return "provider_error"


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
        redacted = redacted.replace(api_key, REDACTED_VALUE)
    return redact_runtime_text(redacted)
