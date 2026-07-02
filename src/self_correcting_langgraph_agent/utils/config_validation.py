from __future__ import annotations

from typing import Any, Dict


def optional_json_int(payload: Dict[str, Any], key: str, default: int) -> int:
    value = payload.get(key)
    if value in {None, ""}:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def optional_json_bool(payload: Dict[str, Any], key: str, default: bool) -> bool:
    if key not in payload:
        return default
    value = payload[key]
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value
