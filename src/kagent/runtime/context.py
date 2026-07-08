from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class RuntimeContextStats:
    truncated_string_count: int = 0
    truncated_chars: int = 0
    omitted_artifact_content_count: int = 0


class RuntimeContextManager:
    def __init__(self, *, max_string_chars: int = 500) -> None:
        if max_string_chars < 1:
            raise ValueError("max_string_chars must be positive")
        self.max_string_chars = max_string_chars
        self._stats = RuntimeContextStats()

    def compact_observation_output(self, output: Any) -> Any:
        if isinstance(output, dict) and str(output.get("artifact_id", "")).strip():
            self._stats.omitted_artifact_content_count += 1
            return self._artifact_prompt_metadata(output)
        return self.compact_value(output)

    def compact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            if len(value) <= self.max_string_chars:
                return value
            self._stats.truncated_string_count += 1
            truncated_chars = len(value) - self.max_string_chars
            self._stats.truncated_chars += truncated_chars
            return {
                "text_prefix": value[: self.max_string_chars],
                "original_chars": len(value),
                "truncated_chars": truncated_chars,
            }
        if isinstance(value, dict):
            return {key: self.compact_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.compact_value(item) for item in value]
        return value

    def report(self) -> Dict[str, Any]:
        return {
            "strategy": "runtime_context_manager",
            "artifact_content_omitted": True,
            "max_string_chars": str(self.max_string_chars),
            "long_string_shape": "text_prefix/original_chars/truncated_chars",
            "truncated_string_count": str(self._stats.truncated_string_count),
            "truncated_chars": str(self._stats.truncated_chars),
            "omitted_artifact_content_count": str(
                self._stats.omitted_artifact_content_count
            ),
        }

    def _artifact_prompt_metadata(self, output: Dict[str, Any]) -> Dict[str, Any]:
        metadata = {
            key: output[key]
            for key in ["artifact_id", "title", "kind", "format", "tags", "bytes"]
            if key in output
        }
        metadata["content_omitted"] = True
        return metadata
