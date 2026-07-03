from __future__ import annotations

import re
import urllib.parse
from typing import Any

REDACTED_VALUE = "[REDACTED]"

_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")
_URL_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9:_-]{6,}"),
    re.compile(r"(?i)\bbearer[\s-]+[A-Za-z0-9._:/+=-]{6,}"),
)


def redact_runtime_payload(value: Any) -> Any:
    if isinstance(value, str):
        return redact_runtime_text(value)
    if isinstance(value, dict):
        return {key: redact_runtime_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_runtime_payload(item) for item in value]
    return value


def redact_runtime_text(value: str) -> str:
    return _URL_PATTERN.sub(lambda match: _redact_url(match.group(0)), value)


def _redact_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return value
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            _redact_url_netloc(parsed.netloc),
            parsed.path,
            _redact_url_component(parsed.query),
            _redact_url_component(parsed.fragment),
        )
    )


def _redact_url_netloc(netloc: str) -> str:
    if "@" not in netloc:
        return netloc
    return f"{REDACTED_VALUE}@{netloc.rsplit('@', 1)[1]}"


def _redact_url_component(value: str) -> str:
    if not value:
        return value
    if "=" not in value and _contains_secret_like_value(urllib.parse.unquote_plus(value)):
        return REDACTED_VALUE
    parts = []
    for item in value.split("&"):
        if "=" not in item:
            parts.append(_redact_bare_url_component_item(item))
            continue
        key, item_value = item.split("=", 1)
        decoded_key = urllib.parse.unquote_plus(key).lower()
        decoded_value = urllib.parse.unquote_plus(item_value)
        if _is_secret_like_key(decoded_key) or _contains_secret_like_value(decoded_value):
            parts.append(f"{key}={REDACTED_VALUE}")
        else:
            parts.append(item)
    return "&".join(parts)


def _redact_bare_url_component_item(value: str) -> str:
    decoded_value = urllib.parse.unquote_plus(value)
    if _is_secret_like_key(decoded_value.lower()) or _contains_secret_like_value(
        decoded_value
    ):
        return REDACTED_VALUE
    return value


def _is_secret_like_key(value: str) -> bool:
    return any(part in value for part in _URL_SECRET_KEY_PARTS)


def _contains_secret_like_value(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)
