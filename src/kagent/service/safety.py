from __future__ import annotations

import hmac
from ipaddress import ip_address
from typing import Any, Mapping
from uuid import uuid4

_MAX_REQUEST_ID_LENGTH = 128
_MAX_IDEMPOTENCY_KEY_LENGTH = 128
_SAFE_TRACE_FILENAME_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    "._-"
)


def authorized(
    headers: Mapping[str, str],
    auth_token: str,
    auth_tokens: Mapping[str, str] | None = None,
) -> bool:
    if not auth_token and not auth_tokens:
        return True
    return bool(authenticated_subject(headers, auth_token, auth_tokens or {}))


def authenticated_subject(
    headers: Mapping[str, str],
    auth_token: str,
    auth_tokens: Mapping[str, str] | None = None,
) -> str:
    provided = header_value(headers, "Authorization")
    if not safe_header_value(provided):
        return ""
    if auth_token:
        expected = f"Bearer {auth_token}"
        if safe_header_value(expected) and hmac.compare_digest(provided, expected):
            return "default"
    for subject, token in sorted((auth_tokens or {}).items()):
        expected = f"Bearer {token}"
        if safe_header_value(expected) and hmac.compare_digest(provided, expected):
            return subject
    return ""


def authenticated_with_primary_token(headers: Mapping[str, str], auth_token: str) -> bool:
    if not auth_token:
        return False
    provided = header_value(headers, "Authorization")
    expected = f"Bearer {auth_token}"
    return (
        safe_header_value(provided)
        and safe_header_value(expected)
        and hmac.compare_digest(provided, expected)
    )


def json_content_type(headers: Mapping[str, str]) -> bool:
    content_type = header_value(headers, "Content-Type")
    if not content_type:
        return True
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type == "application/json"


def rate_limit_key(
    headers: Mapping[str, str],
    remote_addr: str,
    *,
    trust_forwarded_for: bool,
    auth_token: str = "",
    auth_tokens: Mapping[str, str] | None = None,
    auth_subject: str = "",
) -> str:
    subject = auth_subject or authenticated_subject(headers, auth_token, auth_tokens or {})
    if subject:
        return f"auth:{subject}"
    if trust_forwarded_for:
        forwarded_for = header_value(headers, "X-Forwarded-For").split(",", 1)[0].strip()
        forwarded_for_key = forwarded_for_client_key(forwarded_for)
        if forwarded_for_key:
            return forwarded_for_key
    return remote_addr or "local"


def request_id_from_headers(headers: Mapping[str, str]) -> str:
    request_id = header_value(headers, "X-Request-ID")
    if safe_request_id(request_id):
        return request_id
    return str(uuid4())


def safe_request_id(value: str) -> bool:
    if not value or len(value) > _MAX_REQUEST_ID_LENGTH:
        return False
    return all(33 <= ord(character) <= 126 for character in value)


def safe_idempotency_key(value: str) -> bool:
    if not value or len(value) > _MAX_IDEMPOTENCY_KEY_LENGTH:
        return False
    return all(33 <= ord(character) <= 126 for character in value)


def safe_forwarded_for_client(value: str) -> bool:
    return bool(forwarded_for_client_key(value))


def forwarded_for_client_key(value: str) -> str:
    if not safe_request_id(value):
        return ""
    try:
        return str(ip_address(value))
    except ValueError:
        return ""


def safe_trace_file_stem(value: Any) -> str:
    raw_value = str(value or "trace")
    safe_value = "".join(
        character if character in _SAFE_TRACE_FILENAME_CHARS else "_"
        for character in raw_value
    ).strip("._")
    return safe_value or "trace"


def header_value(headers: Mapping[str, str], name: str) -> str:
    expected = name.lower()
    for key, value in headers.items():
        if key.lower() == expected:
            return value
    return ""


def safe_header_value(value: str) -> bool:
    if not value:
        return False
    return all(32 <= ord(character) <= 126 for character in value)
