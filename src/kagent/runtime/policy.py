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
                "delegate_task",
                "decision_matrix",
                "list_files",
                "memory_get",
                "memory_put",
                "memory_search",
                "memory_upsert",
                "note",
                "read_file",
                "rubric_score",
                "skill_get",
                "skill_list",
                "task_list",
                "task_transition",
                "transform_text",
                "workspace_list",
                "workspace_read",
                "workspace_write",
            }
        )

    def authorize(self, tool: str, _input_payload: Dict[str, Any]) -> PolicyDecision:
        if tool not in self.allowed_tools:
            return PolicyDecision(status="denied", reason="tool_not_allowed")
        return PolicyDecision(status="allowed")
