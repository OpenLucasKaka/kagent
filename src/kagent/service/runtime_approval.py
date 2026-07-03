from __future__ import annotations

from typing import Any


def validate_approved_action_ids(value: Any) -> tuple[list[str], str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return [], "approved_action_ids must be an array of strings"
    seen = set()
    approved_action_ids = []
    for action_id in value:
        if not action_id.strip():
            return [], "approved_action_ids must contain non-empty strings"
        if action_id != action_id.strip():
            return [], "approved_action_ids must not contain surrounding whitespace"
        if action_id in seen:
            return [], "approved_action_ids must not contain duplicate action ids"
        seen.add(action_id)
        approved_action_ids.append(action_id)
    return approved_action_ids, ""
