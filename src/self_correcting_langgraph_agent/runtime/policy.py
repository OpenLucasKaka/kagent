from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Set


@dataclass(frozen=True)
class PolicyDecision:
    status: str
    reason: str = ""


class RuntimePolicy:
    def __init__(self, *, allowed_tools: Optional[Set[str]] = None) -> None:
        self.allowed_tools = set(
            allowed_tools
            or {
                "apply_patch",
                "artifact",
                "decision_matrix",
                "list_files",
                "note",
                "open_url",
                "read_file",
                "rubric_score",
                "task_list",
                "transform_text",
            }
        )

    def authorize(self, tool: str, _input_payload: Dict[str, Any]) -> PolicyDecision:
        if tool not in self.allowed_tools:
            return PolicyDecision(status="denied", reason="tool_not_allowed")
        return PolicyDecision(status="allowed")
