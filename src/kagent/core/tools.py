from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Match, Optional, Pattern

ToolResult = Dict[str, str]
ToolHandler = Callable[[Match[str]], ToolResult]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    command: str
    description: str
    example: str
    pattern: Pattern[str]
    handler: ToolHandler


def execute_step(step: str) -> Optional[ToolResult]:
    for tool in TOOLS:
        match = tool.pattern.fullmatch(step)
        if match:
            return tool.handler(match)
    return None


def registered_tool_names() -> List[str]:
    return [tool.name for tool in TOOLS]


def registered_tool_metadata() -> List[Dict[str, str]]:
    return [
        {
            "name": tool.name,
            "command": tool.command,
            "description": tool.description,
            "example": tool.example,
        }
        for tool in TOOLS
    ]


def matching_tool_name(step: str) -> Optional[str]:
    for tool in TOOLS:
        if tool.pattern.fullmatch(step):
            return tool.name
    return None


def expected_answer(step: Optional[str]) -> Optional[str]:
    if step is None:
        return None

    execution = execute_step(step)
    if execution is None:
        return None
    return execution["output"]


def _calculate(match: Match[str]) -> ToolResult:
    left, right = match.groups()
    return _numeric_result("calculate_sum", match, int(left) + int(right))


def _multiply(match: Match[str]) -> ToolResult:
    left, right = match.groups()
    return _numeric_result("multiply_numbers", match, int(left) * int(right))


def _subtract(match: Match[str]) -> ToolResult:
    left, right = match.groups()
    return _numeric_result("subtract_numbers", match, int(left) - int(right))


def _numeric_result(tool: str, match: Match[str], output: int) -> ToolResult:
    return {
        "tool": tool,
        "input": match.group(0),
        "output": str(output),
    }


def _count_words(match: Match[str]) -> ToolResult:
    text = match.group(1)
    return _text_result("count_words", text, str(len([word for word in text.split() if word])))


def _lowercase_text(match: Match[str]) -> ToolResult:
    text = match.group(1)
    return _text_result("lowercase_text", text, text.lower())


def _uppercase_text(match: Match[str]) -> ToolResult:
    text = match.group(1)
    return _text_result("uppercase_text", text, text.upper())


def _reverse_text(match: Match[str]) -> ToolResult:
    text = match.group(1)
    return _text_result("reverse_text", text, text[::-1])


def _trim_text(match: Match[str]) -> ToolResult:
    text = match.group(1)
    return _text_result("trim_text", text, text.strip())


def _text_result(tool: str, text: str, output: str) -> ToolResult:
    return {
        "tool": tool,
        "input": text,
        "output": output,
    }


def _text_tool(
    name: str,
    command: str,
    description: str,
    example: str,
    handler: ToolHandler,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        command=f"{command} text in 'text'",
        description=description,
        example=example,
        pattern=re.compile(rf"{command}\s+text\s+in\s+['\"](.*)['\"]"),
        handler=handler,
    )


TOOLS = [
    ToolSpec(
        name="calculate_sum",
        command="calculate N + M",
        description="Add two integers.",
        example="calculate 2 + 3",
        pattern=re.compile(r"calculate\s+(-?\d+)\s*\+\s*(-?\d+)"),
        handler=_calculate,
    ),
    ToolSpec(
        name="count_words",
        command="count words in 'text'",
        description="Count whitespace-separated words in quoted text.",
        example="count words in 'ship small reliable agents'",
        pattern=re.compile(r"count\s+words\s+in\s+['\"](.*)['\"]"),
        handler=_count_words,
    ),
    _text_tool(
        "lowercase_text",
        "lowercase",
        "Convert quoted text to lowercase.",
        "lowercase text in 'Agent Loop'",
        _lowercase_text,
    ),
    ToolSpec(
        name="multiply_numbers",
        command="multiply N * M",
        description="Multiply two integers.",
        example="multiply 6 * 7",
        pattern=re.compile(r"multiply\s+(-?\d+)\s*\*\s*(-?\d+)"),
        handler=_multiply,
    ),
    _text_tool(
        "reverse_text",
        "reverse",
        "Reverse quoted text while preserving character case.",
        "reverse text in 'Agent Loop'",
        _reverse_text,
    ),
    ToolSpec(
        name="subtract_numbers",
        command="subtract N - M",
        description="Subtract the right integer from the left integer.",
        example="subtract 10 - 4",
        pattern=re.compile(r"subtract\s+(-?\d+)\s*-\s*(-?\d+)"),
        handler=_subtract,
    ),
    _text_tool(
        "trim_text",
        "trim",
        "Remove surrounding whitespace from quoted text.",
        "trim text in '  agent loop  '",
        _trim_text,
    ),
    _text_tool(
        "uppercase_text",
        "uppercase",
        "Convert quoted text to uppercase.",
        "uppercase text in 'agent loop'",
        _uppercase_text,
    ),
]
