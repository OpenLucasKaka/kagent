from __future__ import annotations

from typing import Dict, List, Optional

from self_correcting_langgraph_agent.core.faults import validate_faults
from self_correcting_langgraph_agent.core.normalization import normalize_goal
from self_correcting_langgraph_agent.core.tools import expected_answer, matching_tool_name


def normalize_fault_plan(fault_plan: Dict[str, List[str]]) -> Dict[str, List[str]]:
    for faults in fault_plan.values():
        validate_faults(faults)
    return {
        normalize_goal(step): list(faults)
        for step, faults in fault_plan.items()
    }


def plan_errors(plan: List[str], max_steps: int) -> List[str]:
    unsupported_step = _unsupported_planned_step(plan)
    if not plan:
        return ["empty plan"]
    if len(plan) > max_steps:
        return ["planned steps exceed max_steps"]
    if unsupported_step is not None:
        return [f"unsupported planned step: {unsupported_step}"]
    return []


def validate_plan_steps(plan: List[str]) -> List[Dict[str, str]]:
    validations = []
    for step in plan:
        tool_name = matching_tool_name(step)
        validations.append(
            {
                "step": step,
                "supported": str(tool_name is not None).lower(),
                "tool": tool_name or "",
            }
        )
    return validations


def _unsupported_planned_step(plan: List[str]) -> Optional[str]:
    for step in plan:
        if expected_answer(step) is None:
            return step
    return None
