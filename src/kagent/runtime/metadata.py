from __future__ import annotations

import re
from typing import Any, Dict, Tuple

MAX_RUNTIME_TAGS = 16
MAX_RUNTIME_TAG_CHARS = 64
MAX_RUNTIME_METADATA_ENTRIES = 16
MAX_RUNTIME_METADATA_KEY_CHARS = 64
MAX_RUNTIME_METADATA_VALUE_CHARS = 256

_SAFE_KEY_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "._:-"
)
_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
)
_API_KEY_VALUE_PATTERN = re.compile(r"\bsk-[A-Za-z0-9:_-]{8,}\b")
_BEARER_VALUE_PATTERN = re.compile(
    r"\b(Authorization:\s*Bearer\s+|Bearer\s+)[A-Za-z0-9._~+/:-]{8,}",
    re.IGNORECASE,
)
_URL_CREDENTIAL_VALUE_PATTERN = re.compile(r"\bhttps?://[^/\s:@]+:[^/\s@]+@")


def validate_runtime_metadata(
    metadata: Any,
) -> Tuple[Dict[str, str], str]:
    if metadata is None:
        return {}, ""
    if not isinstance(metadata, dict):
        return {}, "metadata must be a JSON object"
    if len(metadata) > MAX_RUNTIME_METADATA_ENTRIES:
        return {}, (
            f"metadata must contain at most {MAX_RUNTIME_METADATA_ENTRIES} entries"
        )
    normalized = {}
    for raw_key, raw_value in metadata.items():
        if not isinstance(raw_key, str):
            return {}, "metadata keys must be strings"
        key = raw_key.strip()
        if not key:
            return {}, "metadata keys must be non-empty strings"
        if len(key) > MAX_RUNTIME_METADATA_KEY_CHARS:
            return {}, (
                f"metadata keys must contain at most "
                f"{MAX_RUNTIME_METADATA_KEY_CHARS} characters"
            )
        if any(character not in _SAFE_KEY_CHARS for character in key):
            return {}, "metadata keys may only contain letters, numbers, . _ : and -"
        lowered_key = key.lower()
        if any(secret_part in lowered_key for secret_part in _SECRET_KEY_PARTS):
            return {}, "metadata must not contain secret-like keys"
        if not isinstance(raw_value, str):
            return {}, "metadata values must be strings"
        value = raw_value.strip()
        if len(value) > MAX_RUNTIME_METADATA_VALUE_CHARS:
            return {}, (
                f"metadata values must contain at most "
                f"{MAX_RUNTIME_METADATA_VALUE_CHARS} characters"
            )
        if not _safe_runtime_label_value(value):
            return {}, "metadata values must not contain control characters"
        if _secret_like_runtime_label_value(value):
            return {}, "metadata values must not contain secret-like values"
        normalized[key] = value
    return {key: normalized[key] for key in sorted(normalized)}, ""


def validate_runtime_tags(tags: Any) -> Tuple[list[str], str]:
    if tags is None:
        return [], ""
    if not isinstance(tags, list):
        return [], "tags must be an array of strings"
    if len(tags) > MAX_RUNTIME_TAGS:
        return [], f"tags must contain at most {MAX_RUNTIME_TAGS} entries"
    normalized = []
    seen = set()
    for raw_tag in tags:
        if not isinstance(raw_tag, str):
            return [], "tags must be an array of strings"
        tag = raw_tag.strip()
        if not tag:
            return [], "tags must contain non-empty strings"
        if len(tag) > MAX_RUNTIME_TAG_CHARS:
            return [], (
                f"tags must contain strings of at most "
                f"{MAX_RUNTIME_TAG_CHARS} characters"
            )
        if not _safe_runtime_label_value(tag):
            return [], "tags must not contain control characters"
        if tag not in seen:
            seen.add(tag)
            normalized.append(tag)
    return sorted(normalized), ""


def _safe_runtime_label_value(value: str) -> bool:
    return all(ord(character) >= 32 for character in value)


def _secret_like_runtime_label_value(value: str) -> bool:
    return bool(
        _API_KEY_VALUE_PATTERN.search(value)
        or _BEARER_VALUE_PATTERN.search(value)
        or _URL_CREDENTIAL_VALUE_PATTERN.search(value)
    )
