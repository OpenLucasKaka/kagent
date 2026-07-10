from __future__ import annotations

import json
from typing import Any, Dict

from kagent.runtime.types import parse_agent_plan


def build_resumable_plan(
    plan: Dict[str, Any],
    pending_approval: Dict[str, Any],
) -> Dict[str, Any] | None:
    """Return the pending action and every action that follows it.

    Actions before the approval boundary already completed in the persisted run.
    Their dependencies are therefore removed while dependencies between remaining
    actions stay intact.
    """

    try:
        parsed_plan = parse_agent_plan(
            json.dumps(plan, ensure_ascii=False, sort_keys=True)
        )
    except (TypeError, ValueError):
        return None

    pending_action_id = str(pending_approval.get("id", "")).strip()
    raw_actions = plan.get("actions")
    if not pending_action_id or not isinstance(raw_actions, list):
        return None

    matching_indexes = [
        index
        for index, action in enumerate(raw_actions)
        if isinstance(action, dict) and action.get("id") == pending_action_id
    ]
    if len(matching_indexes) != 1:
        return None

    pending_index = matching_indexes[0]
    if raw_actions[pending_index] != pending_approval:
        return None

    completed_action_ids = {
        action.id for action in parsed_plan.actions[:pending_index]
    }
    remaining_actions = []
    for action in parsed_plan.actions[pending_index:]:
        payload = action.to_dict()
        remaining_dependencies = [
            dependency
            for dependency in action.depends_on
            if dependency not in completed_action_ids
        ]
        if remaining_dependencies:
            payload["depends_on"] = remaining_dependencies
        else:
            payload.pop("depends_on", None)
        remaining_actions.append(payload)

    resumable_plan: Dict[str, Any] = {"actions": remaining_actions}
    if parsed_plan.final_answer:
        resumable_plan["final_answer"] = parsed_plan.final_answer
    return resumable_plan
