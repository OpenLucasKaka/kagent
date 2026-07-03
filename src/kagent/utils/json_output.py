from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any


def format_and_write_json(payload: Any, output_path: str) -> str:
    json_payload = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if output_path:
        Path(output_path).write_text(json_payload + "\n", encoding="utf-8")
    return json_payload


def json_ready(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value
