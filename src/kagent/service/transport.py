from __future__ import annotations

import json
from typing import Any, Tuple

JSON_CONTENT_TYPE = "application/json"
PROMETHEUS_TEXT_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
NOSNIFF_HEADER_VALUE = "nosniff"
CACHE_CONTROL_HEADER_VALUE = "no-store"
REFERRER_POLICY_HEADER_VALUE = "no-referrer"
CONTENT_SECURITY_POLICY_HEADER_VALUE = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
X_FRAME_OPTIONS_HEADER_VALUE = "DENY"


def response_body(payload: Any) -> Tuple[bytes, str]:
    if isinstance(payload, str):
        return payload.encode("utf-8"), PROMETHEUS_TEXT_CONTENT_TYPE
    return json.dumps(payload, sort_keys=True).encode("utf-8"), JSON_CONTENT_TYPE


def error_code_from_payload(payload: Any) -> str:
    if isinstance(payload, dict):
        return str(payload.get("error_code", ""))
    return ""
