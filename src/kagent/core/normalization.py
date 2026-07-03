from __future__ import annotations

from typing import List


def normalize_goal(goal: str) -> str:
    return " then ".join(plan_goal(goal))


def plan_goal(goal: str) -> List[str]:
    return [
        normalized
        for part in _split_goal_steps(goal)
        if (normalized := _normalize_step(part))
    ]


def _normalize_step(step: str) -> str:
    quote = None
    output = []
    previous_space = False
    for char in step.strip():
        if char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            output.append(char)
            previous_space = False
        elif quote is not None:
            output.append(char)
        elif char.isspace():
            if output and not previous_space:
                output.append(" ")
                previous_space = True
        else:
            output.append(char.lower())
            previous_space = False
    return "".join(output).strip()


def _split_goal_steps(goal: str) -> List[str]:
    stripped = goal.strip()
    if not stripped:
        return []

    parts = []
    buffer = []
    quote = None
    index = 0
    while index < len(stripped):
        char = stripped[index]
        if char in {"'", '"'}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            buffer.append(char)
            index += 1
        elif quote is None and char.isspace():
            next_index = index
            while next_index < len(stripped) and stripped[next_index].isspace():
                next_index += 1
            after_then = next_index + 4
            if (
                stripped[next_index:after_then].lower() == "then"
                and (after_then == len(stripped) or stripped[after_then].isspace())
            ):
                while after_then < len(stripped) and stripped[after_then].isspace():
                    after_then += 1
                parts.append("".join(buffer))
                buffer = []
                index = after_then
            else:
                buffer.append(" ")
                index = next_index
        else:
            buffer.append(char)
            index += 1
    parts.append("".join(buffer))
    return parts
