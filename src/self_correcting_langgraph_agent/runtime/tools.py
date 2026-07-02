from __future__ import annotations

import hashlib
import ipaddress
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict

from self_correcting_langgraph_agent.runtime.policy import RuntimePolicy
from self_correcting_langgraph_agent.runtime.types import AgentObservation

RuntimeToolHandler = Callable[[Dict[str, Any]], Dict[str, Any]]
_ARTIFACT_KINDS = ("report", "plan", "decision", "data", "message")
_ARTIFACT_FORMATS = ("markdown", "plain_text", "json")
_TASK_STATUSES = ("pending", "in_progress", "blocked", "done")
_TASK_PRIORITIES = ("low", "normal", "high")
_SHORT_TEXT_MAX_LENGTH = 200
_TASK_TITLE_MAX_LENGTH = 500
_LONG_TEXT_MAX_LENGTH = 20000
_TAGS_MAX_ITEMS = 20
_DECISION_CRITERIA_MAX_ITEMS = 20
_DECISION_OPTIONS_MAX_ITEMS = 50
_RUBRIC_CRITERIA_MAX_ITEMS = 100
_TASK_ITEMS_MAX_ITEMS = 200
_RUBRIC_SEVERITIES = ("low", "normal", "blocking")
_HTTP_REQUEST_MAX_BYTES = 65536
_HTTP_REQUEST_TIMEOUT_SECONDS = 10.0
_BLOCKED_HTTP_HOSTS = {"localhost", "localhost."}
_HTTP_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_APPLY_PATCH_MAX_BYTES = 20000
_READ_FILE_MAX_BYTES = 65536
_LIST_FILES_MAX_DEPTH = 5
_LIST_FILES_MAX_ENTRIES = 500


@dataclass(frozen=True)
class _PatchOperation:
    operation: str
    relative_path: str
    content: str = ""
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeToolSpec:
    name: str
    description: str
    handler: RuntimeToolHandler
    input_schema: Dict[str, Any] = field(default_factory=lambda: {"type": "object"})
    output_schema: Dict[str, Any] = field(default_factory=lambda: {"type": "object"})
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


class _ToolExecutionTimeout(Exception):
    pass


_TEXT_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["text"],
    "properties": {"text": {"type": "string"}},
    "additionalProperties": False,
}

_ARTIFACT_OUTPUT_SCHEMA = {
    "type": "object",
    "required": [
        "artifact_id",
        "title",
        "kind",
        "format",
        "content",
        "tags",
        "bytes",
    ],
    "properties": {
        "artifact_id": {"type": "string"},
        "title": {"type": "string"},
        "kind": {"type": "string", "enum": list(_ARTIFACT_KINDS)},
        "format": {"type": "string", "enum": list(_ARTIFACT_FORMATS)},
        "content": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "bytes": {"type": "number", "minimum": 0},
    },
    "additionalProperties": False,
}

_APPLY_PATCH_CHANGED_FILE_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["path", "operation", "bytes", "sha256"],
    "properties": {
        "path": {"type": "string"},
        "operation": {"type": "string", "enum": ["add", "update", "delete"]},
        "bytes": {"type": "number", "minimum": 0},
        "sha256": {"type": "string"},
    },
    "additionalProperties": False,
}

_APPLY_PATCH_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["changed_files", "file_count"],
    "properties": {
        "changed_files": {
            "type": "array",
            "items": _APPLY_PATCH_CHANGED_FILE_OUTPUT_SCHEMA,
        },
        "file_count": {"type": "number", "minimum": 0},
    },
    "additionalProperties": False,
}

_DECISION_CRITERION_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["name", "weight"],
    "properties": {
        "name": {"type": "string"},
        "weight": {"type": "number", "minimum": 0},
    },
    "additionalProperties": False,
}

_DECISION_RANKING_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["rank", "name", "score", "scores", "rationale"],
    "properties": {
        "rank": {"type": "number", "minimum": 1},
        "name": {"type": "string"},
        "score": {"type": "number"},
        "scores": {"type": "array", "items": {"type": "number"}},
        "rationale": {"type": "string"},
    },
    "additionalProperties": False,
}

_DECISION_MATRIX_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["question", "criteria", "rankings", "winner"],
    "properties": {
        "question": {"type": "string"},
        "criteria": {
            "type": "array",
            "items": _DECISION_CRITERION_OUTPUT_SCHEMA,
        },
        "rankings": {
            "type": "array",
            "items": _DECISION_RANKING_OUTPUT_SCHEMA,
        },
        "winner": {"type": "string"},
    },
    "additionalProperties": False,
}

_RUBRIC_CRITERION_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["name", "passed", "severity", "evidence"],
    "properties": {
        "name": {"type": "string"},
        "passed": {"type": "boolean"},
        "severity": {"type": "string", "enum": list(_RUBRIC_SEVERITIES)},
        "evidence": {"type": "string"},
    },
    "additionalProperties": False,
}

_RUBRIC_SCORE_OUTPUT_SCHEMA = {
    "type": "object",
    "required": [
        "criteria",
        "passed",
        "failed",
        "total",
        "score_percent",
        "blocking_failures",
        "failed_criteria",
    ],
    "properties": {
        "criteria": {
            "type": "array",
            "items": _RUBRIC_CRITERION_OUTPUT_SCHEMA,
        },
        "passed": {"type": "number", "minimum": 0},
        "failed": {"type": "number", "minimum": 0},
        "total": {"type": "number", "minimum": 0},
        "score_percent": {"type": "number", "minimum": 0, "maximum": 100},
        "blocking_failures": {"type": "array", "items": {"type": "string"}},
        "failed_criteria": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

_TASK_ITEM_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["title", "status", "priority"],
    "properties": {
        "title": {"type": "string"},
        "status": {"type": "string", "enum": list(_TASK_STATUSES)},
        "priority": {"type": "string", "enum": list(_TASK_PRIORITIES)},
        "owner": {"type": "string"},
        "due": {"type": "string"},
    },
    "additionalProperties": False,
}

_TASK_STATUS_COUNTS_OUTPUT_SCHEMA = {
    "type": "object",
    "required": list(_TASK_STATUSES),
    "properties": {
        "pending": {"type": "number", "minimum": 0},
        "in_progress": {"type": "number", "minimum": 0},
        "blocked": {"type": "number", "minimum": 0},
        "done": {"type": "number", "minimum": 0},
    },
    "additionalProperties": False,
}

_TASK_LIST_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["items", "counts", "total"],
    "properties": {
        "items": {"type": "array", "items": _TASK_ITEM_OUTPUT_SCHEMA},
        "counts": _TASK_STATUS_COUNTS_OUTPUT_SCHEMA,
        "total": {"type": "number", "minimum": 0},
    },
    "additionalProperties": False,
}

_HTTP_REQUEST_OUTPUT_SCHEMA = {
    "type": "object",
    "required": [
        "url",
        "status_code",
        "content_type",
        "body_text",
        "bytes",
        "truncated",
    ],
    "properties": {
        "url": {"type": "string"},
        "status_code": {"type": "number", "minimum": 100, "maximum": 599},
        "content_type": {"type": "string"},
        "body_text": {"type": "string"},
        "bytes": {"type": "number", "minimum": 0},
        "truncated": {"type": "boolean"},
    },
    "additionalProperties": False,
}

_OPEN_URL_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["url", "opened", "application", "command"],
    "properties": {
        "url": {"type": "string"},
        "opened": {"type": "boolean"},
        "application": {"type": "string"},
        "command": {"type": "string"},
    },
    "additionalProperties": False,
}

_READ_FILE_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["path", "content", "bytes", "truncated", "sha256"],
    "properties": {
        "path": {"type": "string"},
        "content": {"type": "string"},
        "bytes": {"type": "number", "minimum": 0},
        "truncated": {"type": "boolean"},
        "sha256": {"type": "string"},
    },
    "additionalProperties": False,
}

_LIST_FILES_ENTRY_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["path", "type", "bytes"],
    "properties": {
        "path": {"type": "string"},
        "type": {"type": "string", "enum": ["directory", "file"]},
        "bytes": {"type": "number", "minimum": 0},
    },
    "additionalProperties": False,
}

_LIST_FILES_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["root", "entries", "file_count", "truncated"],
    "properties": {
        "root": {"type": "string"},
        "entries": {"type": "array", "items": _LIST_FILES_ENTRY_OUTPUT_SCHEMA},
        "file_count": {"type": "number", "minimum": 0},
        "truncated": {"type": "boolean"},
    },
    "additionalProperties": False,
}


def default_runtime_tools() -> Dict[str, RuntimeToolSpec]:
    return {
        "apply_patch": RuntimeToolSpec(
            name="apply_patch",
            description=(
                "Apply a Codex-style workspace patch. Supports adding, updating, "
                "and deleting files "
                "inside the current workspace and rejects absolute paths, parent "
                "traversal, unsafe deletes, and accidental overwrites. To create hello.md, "
                "use exactly: *** Begin Patch\n*** Add File: hello.md\n+content\n*** End Patch"
            ),
            handler=_apply_patch,
            input_schema={
                "type": "object",
                "required": ["patch"],
                "properties": {
                    "patch": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": _APPLY_PATCH_MAX_BYTES,
                    },
                },
                "additionalProperties": False,
            },
            output_schema=_APPLY_PATCH_OUTPUT_SCHEMA,
        ),
        "artifact": RuntimeToolSpec(
            name="artifact",
            description=(
                "Record a structured artifact such as a report, plan, "
                "decision, data, or message."
            ),
            handler=_artifact,
            input_schema={
                "type": "object",
                "required": ["title", "kind", "content"],
                "properties": {
                    "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": _SHORT_TEXT_MAX_LENGTH,
                    },
                    "kind": {
                        "type": "string",
                        "enum": list(_ARTIFACT_KINDS),
                    },
                    "content": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": _LONG_TEXT_MAX_LENGTH,
                    },
                    "format": {
                        "type": "string",
                        "enum": list(_ARTIFACT_FORMATS),
                    },
                    "tags": {
                        "type": "array",
                        "maxItems": _TAGS_MAX_ITEMS,
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": False,
            },
            output_schema=_ARTIFACT_OUTPUT_SCHEMA,
        ),
        "decision_matrix": RuntimeToolSpec(
            name="decision_matrix",
            description="Rank options with weighted criteria for structured decisions.",
            handler=_decision_matrix,
            input_schema={
                "type": "object",
                "required": ["question", "criteria", "options"],
                "properties": {
                    "question": {"type": "string"},
                    "criteria": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": _DECISION_CRITERIA_MAX_ITEMS,
                        "items": {
                            "type": "object",
                            "required": ["name", "weight"],
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": _SHORT_TEXT_MAX_LENGTH,
                                },
                                "weight": {"type": "number", "minimum": 0},
                            },
                            "additionalProperties": False,
                        },
                    },
                    "options": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": _DECISION_OPTIONS_MAX_ITEMS,
                        "items": {
                            "type": "object",
                            "required": ["name", "scores"],
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": _SHORT_TEXT_MAX_LENGTH,
                                },
                                "scores": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {"type": "number"},
                                },
                                "rationale": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
            output_schema=_DECISION_MATRIX_OUTPUT_SCHEMA,
        ),
        "note": RuntimeToolSpec(
            name="note",
            description="Record a short note as an artifact observation.",
            handler=_note,
            input_schema={
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text": {"type": "string", "maxLength": _LONG_TEXT_MAX_LENGTH}
                },
                "additionalProperties": False,
            },
            output_schema=_TEXT_OUTPUT_SCHEMA,
        ),
        "http_request": RuntimeToolSpec(
            name="http_request",
            description=(
                "Fetch a URL with an HTTP GET request. This does not open a "
                "browser window; use open_url when the user asks to open a "
                "web page. This tool is policy-gated and should only run after "
                "explicit approval. Private, loopback, and link-local targets "
                "are rejected."
            ),
            handler=_http_request,
            input_schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2048,
                    },
                    "max_bytes": {
                        "type": "number",
                        "minimum": 1,
                        "maximum": _HTTP_REQUEST_MAX_BYTES,
                    },
                },
                "additionalProperties": False,
            },
            output_schema=_HTTP_REQUEST_OUTPUT_SCHEMA,
        ),
        "list_files": RuntimeToolSpec(
            name="list_files",
            description=(
                "List files and directories inside the current workspace with "
                "bounded depth and entry count."
            ),
            handler=_list_files,
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "maxLength": 2048},
                    "max_depth": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": _LIST_FILES_MAX_DEPTH,
                    },
                    "limit": {
                        "type": "number",
                        "minimum": 1,
                        "maximum": _LIST_FILES_MAX_ENTRIES,
                    },
                },
                "additionalProperties": False,
            },
            output_schema=_LIST_FILES_OUTPUT_SCHEMA,
        ),
        "open_url": RuntimeToolSpec(
            name="open_url",
            description=(
                "Open an http:// or https:// URL in a local browser window on "
                "macOS. Uses Google Chrome automation first, with macOS open "
                "fallbacks. Use this when the user asks to open a web page."
            ),
            handler=_open_url,
            input_schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2048,
                    },
                },
                "additionalProperties": False,
            },
            output_schema=_OPEN_URL_OUTPUT_SCHEMA,
        ),
        "read_file": RuntimeToolSpec(
            name="read_file",
            description=(
                "Read a UTF-8 text file inside the current workspace with a "
                "bounded byte limit."
            ),
            handler=_read_file,
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 2048},
                    "max_bytes": {
                        "type": "number",
                        "minimum": 1,
                        "maximum": _READ_FILE_MAX_BYTES,
                    },
                },
                "additionalProperties": False,
            },
            output_schema=_READ_FILE_OUTPUT_SCHEMA,
        ),
        "task_list": RuntimeToolSpec(
            name="task_list",
            description="Create a structured task list with normalized status counts.",
            handler=_task_list,
            input_schema={
                "type": "object",
                "required": ["items"],
                "properties": {
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": _TASK_ITEMS_MAX_ITEMS,
                        "items": {
                            "type": "object",
                            "required": ["title"],
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": _TASK_TITLE_MAX_LENGTH,
                                },
                                "status": {
                                    "type": "string",
                                    "enum": list(_TASK_STATUSES),
                                },
                                "priority": {
                                    "type": "string",
                                    "enum": list(_TASK_PRIORITIES),
                                },
                                "owner": {"type": "string"},
                                "due": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
            output_schema=_TASK_LIST_OUTPUT_SCHEMA,
        ),
        "rubric_score": RuntimeToolSpec(
            name="rubric_score",
            description=(
                "Score a result against pass/fail rubric criteria and report "
                "blocking failures."
            ),
            handler=_rubric_score,
            input_schema={
                "type": "object",
                "required": ["criteria"],
                "properties": {
                    "criteria": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": _RUBRIC_CRITERIA_MAX_ITEMS,
                        "items": {
                            "type": "object",
                            "required": ["name", "passed"],
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": _SHORT_TEXT_MAX_LENGTH,
                                },
                                "passed": {"type": "boolean"},
                                "severity": {
                                    "type": "string",
                                    "enum": list(_RUBRIC_SEVERITIES),
                                },
                                "evidence": {
                                    "type": "string",
                                    "maxLength": _LONG_TEXT_MAX_LENGTH,
                                },
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
            output_schema=_RUBRIC_SCORE_OUTPUT_SCHEMA,
        ),
        "transform_text": RuntimeToolSpec(
            name="transform_text",
            description="Transform text with uppercase, lowercase, reverse, or trim modes.",
            handler=_transform_text,
            input_schema={
                "type": "object",
                "required": ["text", "mode"],
                "properties": {
                    "text": {"type": "string"},
                    "mode": {
                        "type": "string",
                        "enum": ["uppercase", "lowercase", "reverse", "trim"],
                    },
                },
                "additionalProperties": False,
            },
            output_schema=_TEXT_OUTPUT_SCHEMA,
        ),
    }


def registered_runtime_tool_metadata() -> list[Dict[str, Any]]:
    return runtime_tool_metadata(default_runtime_tools())


def runtime_tool_metadata(tools: Dict[str, RuntimeToolSpec]) -> list[Dict[str, Any]]:
    default_allowed_tools = RuntimePolicy().allowed_tools
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "approval_required_by_default": str(
                tool.name not in default_allowed_tools
            ).lower(),
            "input_schema": tool.input_schema,
            "output_schema": tool.output_schema,
            "timeout_seconds": f"{tool.timeout_seconds:.1f}",
        }
        for tool in sorted(tools.values(), key=lambda item: item.name)
    ]


def execute_runtime_tool(
    registry: Dict[str, RuntimeToolSpec],
    tool_name: str,
    input_payload: Dict[str, Any],
    *,
    action_id: str = "",
) -> AgentObservation:
    started_at = _utc_timestamp()
    started_timer = time.perf_counter()
    tool = registry.get(tool_name)
    if tool is None:
        return AgentObservation(
            action_id=action_id,
            tool=tool_name,
            status="failed",
            output={},
            error_code="tool_not_found",
            error="tool is not registered",
            started_at=started_at,
            completed_at=_utc_timestamp(),
            duration_seconds=_duration_since(started_timer),
        )
    try:
        _validate_tool_input(input_payload, tool.input_schema)
        output = _run_tool_handler(tool, input_payload)
    except _ToolExecutionTimeout:
        return AgentObservation(
            action_id=action_id,
            tool=tool_name,
            status="failed",
            output={},
            error_code="tool_execution_timeout",
            error="tool execution exceeded timeout",
            started_at=started_at,
            completed_at=_utc_timestamp(),
            duration_seconds=_duration_since(started_timer),
        )
    except ValueError as exc:
        return AgentObservation(
            action_id=action_id,
            tool=tool_name,
            status="failed",
            output={},
            error_code="invalid_tool_input",
            error=str(exc),
            started_at=started_at,
            completed_at=_utc_timestamp(),
            duration_seconds=_duration_since(started_timer),
        )
    try:
        _validate_tool_input(output, tool.output_schema, "output")
    except ValueError as exc:
        return AgentObservation(
            action_id=action_id,
            tool=tool_name,
            status="failed",
            output={},
            error_code="invalid_tool_output",
            error=str(exc),
            started_at=started_at,
            completed_at=_utc_timestamp(),
            duration_seconds=_duration_since(started_timer),
        )
    return AgentObservation(
        action_id=action_id,
        tool=tool_name,
        status="ok",
        output=output,
        started_at=started_at,
        completed_at=_utc_timestamp(),
        duration_seconds=_duration_since(started_timer),
    )


def _run_tool_handler(
    tool: RuntimeToolSpec,
    input_payload: Dict[str, Any],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    failure: Dict[str, BaseException] = {}

    def target() -> None:
        try:
            result["output"] = tool.handler(input_payload)
        except BaseException as exc:  # pragma: no cover - re-raised in caller thread
            failure["error"] = exc

    thread = threading.Thread(
        target=target,
        name=f"runtime-tool-{tool.name}",
        daemon=True,
    )
    thread.start()
    thread.join(tool.timeout_seconds)
    if thread.is_alive():
        raise _ToolExecutionTimeout()
    if "error" in failure:
        raise failure["error"]
    output = result.get("output")
    if not isinstance(output, dict):
        raise ValueError("output must be an object")
    return output


def _note(input_payload: Dict[str, Any]) -> Dict[str, Any]:
    text = input_payload.get("text")
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return {"text": text}


def _read_file(input_payload: Dict[str, Any]) -> Dict[str, Any]:
    relative_path = input_payload.get("path")
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("path must be a non-empty string")
    normalized_path = relative_path.strip()
    max_bytes = int(input_payload.get("max_bytes", _READ_FILE_MAX_BYTES))
    workspace_root = Path.cwd().resolve()
    target = _resolve_workspace_relative_path(workspace_root, normalized_path)
    if not target.exists():
        raise ValueError(f"file does not exist: {normalized_path}")
    if target.is_dir():
        raise ValueError(f"path is a directory: {normalized_path}")
    body = target.read_bytes()
    truncated = len(body) > max_bytes
    visible_body = body[:max_bytes] if truncated else body
    return {
        "path": _workspace_output_path(workspace_root, target),
        "content": visible_body.decode("utf-8", errors="replace"),
        "bytes": len(visible_body),
        "truncated": truncated,
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _list_files(input_payload: Dict[str, Any]) -> Dict[str, Any]:
    relative_path = input_payload.get("path", ".")
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ValueError("path must be a non-empty string")
    normalized_path = relative_path.strip()
    max_depth = int(input_payload.get("max_depth", _LIST_FILES_MAX_DEPTH))
    limit = int(input_payload.get("limit", _LIST_FILES_MAX_ENTRIES))
    workspace_root = Path.cwd().resolve()
    root = _resolve_workspace_relative_path(workspace_root, normalized_path)
    if not root.exists():
        raise ValueError(f"path does not exist: {normalized_path}")
    if root.is_file():
        entries = [_file_entry(workspace_root, root)]
        return {
            "root": _workspace_output_path(workspace_root, root),
            "entries": entries,
            "file_count": len(entries),
            "truncated": False,
        }
    entries = []
    truncated = False
    for path in _iter_workspace_entries(root, max_depth=max_depth):
        if len(entries) >= limit:
            truncated = True
            break
        entries.append(_file_entry(workspace_root, path))
    return {
        "root": _workspace_output_path(workspace_root, root),
        "entries": entries,
        "file_count": len(entries),
        "truncated": truncated,
    }


def _apply_patch(input_payload: Dict[str, Any]) -> Dict[str, Any]:
    patch = input_payload.get("patch")
    if not isinstance(patch, str) or not patch.strip():
        raise ValueError("patch must be a non-empty string")
    operations = _parse_workspace_patch(patch)
    workspace_root = Path.cwd().resolve()
    staged_contents: dict[Path, str | None] = {}
    changed_files = []

    for operation in operations:
        target = _resolve_workspace_relative_path(workspace_root, operation.relative_path)
        current_content = _staged_or_disk_content(target, staged_contents)
        if operation.operation == "add":
            if current_content is not None:
                raise ValueError(f"file already exists: {operation.relative_path}")
            next_content: str | None = operation.content
        elif operation.operation == "update":
            if current_content is None:
                raise ValueError(f"file does not exist: {operation.relative_path}")
            next_content = _apply_update_lines(
                current_content,
                operation.lines,
                operation.relative_path,
            )
        elif operation.operation == "delete":
            if current_content is None:
                raise ValueError(f"file does not exist: {operation.relative_path}")
            if target.is_dir():
                raise ValueError(f"path is a directory: {operation.relative_path}")
            next_content = None
        else:  # pragma: no cover - parser owns the operation enum
            raise ValueError(f"unsupported patch operation: {operation.operation}")

        staged_contents[target] = next_content
        encoded = (next_content or "").encode("utf-8")
        changed_files.append(
            {
                "path": operation.relative_path,
                "operation": operation.operation,
                "bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
        )

    for target, content in staged_contents.items():
        if content is None:
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="") as handle:
            handle.write(content)
    return {"changed_files": changed_files, "file_count": len(changed_files)}


def _parse_workspace_patch(patch: str) -> list[_PatchOperation]:
    lines = patch.splitlines()
    if not lines or lines[0] != "*** Begin Patch":
        raise ValueError("patch must start with *** Begin Patch")
    if lines[-1] != "*** End Patch":
        raise ValueError("patch must end with *** End Patch")
    operations = []
    index = 1
    while index < len(lines) - 1:
        line = lines[index]
        if line.startswith("*** Add File: "):
            relative_path = line.removeprefix("*** Add File: ").strip()
            if not relative_path:
                raise ValueError("patch file path is required")
            index += 1
            content_lines = []
            while index < len(lines) - 1 and not lines[index].startswith("*** "):
                content_line = lines[index]
                content_lines.append(
                    content_line[1:] if content_line.startswith("+") else content_line
                )
                index += 1
            if not content_lines:
                raise ValueError("add file patch must contain at least one content line")
            operations.append(
                _PatchOperation(
                    operation="add",
                    relative_path=relative_path,
                    content="\n".join(content_lines) + "\n",
                )
            )
            continue
        if line.startswith("*** Update File: "):
            relative_path = line.removeprefix("*** Update File: ").strip()
            if not relative_path:
                raise ValueError("patch file path is required")
            index += 1
            update_lines = []
            while index < len(lines) - 1 and not lines[index].startswith("*** "):
                update_line = lines[index]
                if update_line == "@@":
                    index += 1
                    continue
                update_lines.append(update_line)
                index += 1
            if not update_lines:
                raise ValueError("update file patch must contain at least one change line")
            operations.append(
                _PatchOperation(
                    operation="update",
                    relative_path=relative_path,
                    lines=tuple(update_lines),
                )
            )
            continue
        if line.startswith("*** Delete File: "):
            relative_path = line.removeprefix("*** Delete File: ").strip()
            if not relative_path:
                raise ValueError("patch file path is required")
            index += 1
            operations.append(
                _PatchOperation(operation="delete", relative_path=relative_path)
            )
            continue
        raise ValueError("only Add File, Update File, and Delete File patch hunks are supported")
    if not operations:
        raise ValueError("patch must contain at least one file hunk")
    return operations


def _staged_or_disk_content(
    target: Path,
    staged_contents: dict[Path, str | None],
) -> str | None:
    if target in staged_contents:
        return staged_contents[target]
    if not target.exists():
        return None
    if target.is_dir():
        raise ValueError("path is a directory")
    return target.read_text(encoding="utf-8")


def _apply_update_lines(
    content: str,
    update_lines: tuple[str, ...],
    relative_path: str,
) -> str:
    old_lines = []
    new_lines = []
    for line in update_lines:
        if line.startswith(" "):
            value = line[1:]
            old_lines.append(value)
            new_lines.append(value)
            continue
        if line.startswith("-"):
            old_lines.append(line[1:])
            continue
        if line.startswith("+"):
            new_lines.append(line[1:])
            continue
        raise ValueError("update lines must start with space, -, +, or @@")
    if old_lines == new_lines:
        raise ValueError("update file patch must change file content")
    content_lines = content.splitlines()
    start = _find_subsequence(content_lines, old_lines)
    if start is None:
        raise ValueError(f"update context not found: {relative_path}")
    next_lines = content_lines[:start] + new_lines + content_lines[start + len(old_lines) :]
    return "\n".join(next_lines) + "\n"


def _find_subsequence(lines: list[str], needle: list[str]) -> int | None:
    if not needle:
        return None
    last_start = len(lines) - len(needle)
    for index in range(last_start + 1):
        if lines[index : index + len(needle)] == needle:
            return index
    return None


def _iter_workspace_entries(root: Path, *, max_depth: int):
    root_depth = len(root.parts)
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        depth = len(path.parts) - root_depth
        if depth > max_depth:
            continue
        yield path


def _file_entry(workspace_root: Path, path: Path) -> Dict[str, Any]:
    if path.is_dir():
        return {
            "path": _workspace_output_path(workspace_root, path),
            "type": "directory",
            "bytes": 0,
        }
    return {
        "path": _workspace_output_path(workspace_root, path),
        "type": "file",
        "bytes": path.stat().st_size,
    }


def _workspace_output_path(workspace_root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("path must stay inside the workspace") from exc
    output = relative.as_posix()
    return "." if output == "" else output


def _resolve_workspace_relative_path(workspace_root: Path, relative_path: str) -> Path:
    candidate_path = Path(relative_path)
    if candidate_path.is_absolute():
        raise ValueError("path must stay inside the workspace")
    if any(part in {"", ".", ".."} for part in candidate_path.parts):
        raise ValueError("path must stay inside the workspace")
    normalized_path = os.path.normpath(relative_path)
    target = (workspace_root / normalized_path).resolve()
    try:
        target.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("path must stay inside the workspace") from exc
    return target


def _http_request(input_payload: Dict[str, Any]) -> Dict[str, Any]:
    url = input_payload.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")
    normalized_url = url.strip()
    _validate_http_request_url(normalized_url)
    max_bytes = int(input_payload.get("max_bytes", _HTTP_REQUEST_MAX_BYTES))
    request = urllib.request.Request(
        normalized_url,
        headers={"User-Agent": "self-correcting-langgraph-agent/0.1"},
        method="GET",
    )
    try:
        with _open_http_request_without_redirects(
            request,
            timeout_seconds=_HTTP_REQUEST_TIMEOUT_SECONDS,
        ) as response:
            body = response.read(max_bytes + 1)
            content_type = response.headers.get("Content-Type", "")
            status_code = int(response.status)
    except urllib.error.HTTPError as exc:
        body = exc.read(max_bytes + 1)
        content_type = exc.headers.get("Content-Type", "")
        status_code = int(exc.code)
    except urllib.error.URLError as exc:
        raise ValueError("http request failed") from exc
    truncated = len(body) > max_bytes
    if truncated:
        body = body[:max_bytes]
    return {
        "url": normalized_url,
        "status_code": status_code,
        "content_type": content_type,
        "body_text": body.decode("utf-8", errors="replace"),
        "bytes": len(body),
        "truncated": truncated,
    }


def _open_url(input_payload: Dict[str, Any]) -> Dict[str, Any]:
    url = input_payload.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")
    normalized_url = url.strip()
    _validate_open_url(normalized_url)
    attempts = [
        (
            ["osascript", "-e", _chrome_open_location_script(normalized_url)],
            "Google Chrome",
            "osascript Google Chrome",
        ),
        (["open", "-a", "Google Chrome", normalized_url], "Google Chrome", "open -a Google Chrome"),
        (["open", normalized_url], "default", "open"),
    ]
    last_error: BaseException | None = None
    for command_args, application, command_label in attempts:
        try:
            subprocess.run(
                command_args,
                check=True,
                capture_output=True,
                text=True,
            )
            return {
                "url": normalized_url,
                "opened": True,
                "application": application,
                "command": command_label,
            }
        except (OSError, subprocess.CalledProcessError) as exc:
            last_error = exc
            continue
    raise ValueError("open url failed") from last_error


def _validate_open_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("url must start with http:// or https://")
    if not parsed.hostname:
        raise ValueError("url host is required")


def _chrome_open_location_script(url: str) -> str:
    escaped_url = _apple_script_string(url)
    return (
        'tell application "Google Chrome"\n'
        "  activate\n"
        "  if (count of windows) = 0 then make new window\n"
        "  tell front window\n"
        f"    make new tab at end of tabs with properties {{URL:{escaped_url}}}\n"
        "    set active tab index to (count of tabs)\n"
        "  end tell\n"
        "end tell"
    )


def _apple_script_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_http_request_without_redirects(
    request: urllib.request.Request,
    *,
    timeout_seconds: float,
):
    opener = urllib.request.build_opener(_NoRedirectHandler)
    try:
        return opener.open(request, timeout=timeout_seconds)
    except urllib.error.HTTPError as exc:
        if exc.code in _HTTP_REDIRECT_STATUS_CODES:
            return exc
        raise


def _validate_http_request_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("url must start with http:// or https://")
    if not parsed.hostname:
        raise ValueError("url host is required")
    host = parsed.hostname.strip().lower()
    if host in _BLOCKED_HTTP_HOSTS or host.endswith(".localhost"):
        raise ValueError("url host is not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        _validate_resolved_http_host(host, parsed.port)
        return
    if _is_blocked_http_address(address):
        raise ValueError("url host is not allowed")


def _validate_resolved_http_host(host: str, port: int | None) -> None:
    try:
        records = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("url host could not be resolved") from exc
    for record in records:
        sockaddr = record[4]
        if not sockaddr:
            continue
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError as exc:
            raise ValueError("url host resolved to an invalid address") from exc
        if _is_blocked_http_address(address):
            raise ValueError("url host is not allowed")


def _is_blocked_http_address(address: ipaddress._BaseAddress) -> bool:
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _artifact(input_payload: Dict[str, Any]) -> Dict[str, Any]:
    title = input_payload.get("title")
    kind = input_payload.get("kind")
    content = input_payload.get("content")
    artifact_format = input_payload.get("format", "markdown")
    tags = input_payload.get("tags", [])

    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be a non-empty string")
    if kind not in _ARTIFACT_KINDS:
        raise ValueError("kind must be report, plan, decision, data, or message")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content must be a non-empty string")
    if artifact_format not in _ARTIFACT_FORMATS:
        raise ValueError("format must be markdown, plain_text, or json")
    if not isinstance(tags, list):
        raise ValueError("tags must be an array")

    normalized_title = title.strip()
    normalized_tags = []
    for index, tag in enumerate(tags):
        if not isinstance(tag, str):
            raise ValueError(f"tag {index} must be a string")
        normalized_tag = tag.strip()
        if normalized_tag:
            normalized_tags.append(normalized_tag)

    artifact_id = _artifact_id(normalized_title, str(kind), str(artifact_format), content)
    return {
        "artifact_id": artifact_id,
        "title": normalized_title,
        "kind": kind,
        "format": artifact_format,
        "content": content,
        "tags": normalized_tags,
        "bytes": len(content.encode("utf-8")),
    }


def _artifact_id(title: str, kind: str, artifact_format: str, content: str) -> str:
    digest = hashlib.sha256(
        "|".join([title, kind, artifact_format, content]).encode("utf-8")
    ).hexdigest()
    return f"artifact_{digest[:12]}"


def _decision_matrix(input_payload: Dict[str, Any]) -> Dict[str, Any]:
    question = input_payload.get("question")
    criteria = input_payload.get("criteria")
    options = input_payload.get("options")

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("criteria must be a non-empty array")
    if not isinstance(options, list) or len(options) < 2:
        raise ValueError("options must contain at least 2 item(s)")

    normalized_criteria = _normalize_decision_criteria(criteria)
    rankings = _rank_decision_options(options, normalized_criteria)
    return {
        "question": question.strip(),
        "criteria": normalized_criteria,
        "rankings": rankings,
        "winner": rankings[0]["name"],
    }


def _normalize_decision_criteria(criteria: list[Any]) -> list[Dict[str, Any]]:
    normalized = []
    for index, criterion in enumerate(criteria):
        if not isinstance(criterion, dict):
            raise ValueError(f"criterion {index} must be an object")
        name = criterion.get("name")
        weight = criterion.get("weight")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"criterion {index} name must be a non-empty string")
        if not _is_number(weight):
            raise ValueError(f"criterion {index} weight must be a number")
        normalized.append({"name": name.strip(), "weight": float(weight)})
    return normalized


def _rank_decision_options(
    options: list[Any],
    criteria: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    scored_options = []
    for index, option in enumerate(options):
        if not isinstance(option, dict):
            raise ValueError(f"option {index} must be an object")
        name = option.get("name")
        scores = option.get("scores")
        rationale = option.get("rationale", "")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"option {index} name must be a non-empty string")
        if not isinstance(scores, list) or len(scores) != len(criteria):
            raise ValueError(
                f"option {index} scores must match the number of criteria"
            )
        if not isinstance(rationale, str):
            raise ValueError(f"option {index} rationale must be a string")
        normalized_scores = []
        total = 0.0
        for score_index, score in enumerate(scores):
            if not _is_number(score):
                raise ValueError(f"option {index} score {score_index} must be a number")
            normalized_score = float(score)
            normalized_scores.append(normalized_score)
            total += normalized_score * float(criteria[score_index]["weight"])
        scored_options.append(
            {
                "name": name.strip(),
                "score": round(total, 4),
                "scores": normalized_scores,
                "rationale": rationale.strip(),
            }
        )

    ranked = sorted(scored_options, key=lambda item: (-item["score"], item["name"]))
    for index, option in enumerate(ranked, start=1):
        option["rank"] = index
    return [
        {
            "rank": option["rank"],
            "name": option["name"],
            "score": option["score"],
            "scores": option["scores"],
            "rationale": option["rationale"],
        }
        for option in ranked
    ]


def _validate_tool_input(value: Any, schema: Dict[str, Any], path: str = "input") -> None:
    expected_type = schema.get("type")
    if expected_type == "object":
        _validate_object(value, schema, path)
    elif expected_type == "array":
        _validate_array(value, schema, path)
    elif expected_type == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string")
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value.strip()) < min_length:
            raise ValueError(
                f"{path} must contain at least {min_length} character(s)"
            )
        max_length = schema.get("maxLength")
        if isinstance(max_length, int) and len(value) > max_length:
            raise ValueError(f"{path} must contain at most {max_length} character(s)")
    elif expected_type == "number":
        if not _is_number(value):
            raise ValueError(f"{path} must be a number")
        minimum = schema.get("minimum")
        if _is_number(minimum) and value < minimum:
            raise ValueError(f"{path} must be at least {minimum:g}")
        maximum = schema.get("maximum")
        if _is_number(maximum) and value > maximum:
            raise ValueError(f"{path} must be at most {maximum:g}")
    elif expected_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path} must be a boolean")

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        allowed = ", ".join(str(item) for item in enum_values)
        raise ValueError(f"{path} must be one of: {allowed}")


def _validate_object(value: Any, schema: Dict[str, Any], path: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    required = schema.get("required", [])
    if not isinstance(required, list):
        required = []
    for key in required:
        if key not in value:
            raise ValueError(f"{path}.{key} is required")
    if schema.get("additionalProperties") is False:
        for key in value:
            if key not in properties:
                raise ValueError(f"{path}.{key} is not allowed")
    for key, property_schema in properties.items():
        if key in value and isinstance(property_schema, dict):
            _validate_tool_input(value[key], property_schema, f"{path}.{key}")


def _validate_array(value: Any, schema: Dict[str, Any], path: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be an array")
    min_items = schema.get("minItems")
    if isinstance(min_items, int) and len(value) < min_items:
        raise ValueError(f"{path} must contain at least {min_items} item(s)")
    max_items = schema.get("maxItems")
    if isinstance(max_items, int) and len(value) > max_items:
        raise ValueError(f"{path} must contain at most {max_items} item(s)")
    item_schema = schema.get("items")
    if isinstance(item_schema, dict):
        for index, item in enumerate(value):
            _validate_tool_input(item, item_schema, f"{path}[{index}]")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_since(started_at: float) -> str:
    return f"{time.perf_counter() - started_at:.4f}"


def _transform_text(input_payload: Dict[str, Any]) -> Dict[str, Any]:
    text = input_payload.get("text")
    mode = input_payload.get("mode")
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    if mode == "uppercase":
        return {"text": text.upper()}
    if mode == "lowercase":
        return {"text": text.lower()}
    if mode == "reverse":
        return {"text": text[::-1]}
    if mode == "trim":
        return {"text": text.strip()}
    raise ValueError("mode must be uppercase, lowercase, reverse, or trim")


def _rubric_score(input_payload: Dict[str, Any]) -> Dict[str, Any]:
    criteria = input_payload.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("criteria must be a non-empty array")

    normalized_criteria = []
    failed_criteria = []
    blocking_failures = []
    passed_count = 0
    for index, criterion in enumerate(criteria):
        if not isinstance(criterion, dict):
            raise ValueError(f"criterion {index} must be an object")
        name = criterion.get("name")
        passed = criterion.get("passed")
        severity = criterion.get("severity", "normal")
        evidence = criterion.get("evidence", "")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"criterion {index} name must be a non-empty string")
        if not isinstance(passed, bool):
            raise ValueError(f"criterion {index} passed must be a boolean")
        if severity not in _RUBRIC_SEVERITIES:
            raise ValueError(f"criterion {index} severity must be low, normal, or blocking")
        if not isinstance(evidence, str):
            raise ValueError(f"criterion {index} evidence must be a string")

        normalized_name = name.strip()
        normalized = {
            "name": normalized_name,
            "passed": passed,
            "severity": severity,
            "evidence": evidence.strip(),
        }
        normalized_criteria.append(normalized)
        if passed:
            passed_count += 1
            continue
        failed_criteria.append(normalized_name)
        if severity == "blocking":
            blocking_failures.append(normalized_name)

    total = len(normalized_criteria)
    failed_count = total - passed_count
    return {
        "criteria": normalized_criteria,
        "passed": passed_count,
        "failed": failed_count,
        "total": total,
        "score_percent": round((passed_count / total) * 100, 2),
        "blocking_failures": blocking_failures,
        "failed_criteria": failed_criteria,
    }


def _task_list(input_payload: Dict[str, Any]) -> Dict[str, Any]:
    items = input_payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty array")

    normalized_items = []
    counts = {status: 0 for status in _TASK_STATUSES}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"item {index} must be an object")
        normalized = _normalize_task_item(item, index)
        normalized_items.append(normalized)
        counts[normalized["status"]] += 1
    return {
        "items": normalized_items,
        "counts": counts,
        "total": len(normalized_items),
    }


def _normalize_task_item(item: Dict[str, Any], index: int) -> Dict[str, Any]:
    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"item {index} title must be a non-empty string")
    status = item.get("status", "pending")
    if status not in _TASK_STATUSES:
        raise ValueError(
            f"item {index} status must be pending, in_progress, blocked, or done"
        )
    priority = item.get("priority", "normal")
    if priority not in _TASK_PRIORITIES:
        raise ValueError(f"item {index} priority must be low, normal, or high")

    normalized = {
        "title": title.strip(),
        "status": status,
        "priority": priority,
    }
    for optional_field in ["owner", "due"]:
        value = item.get(optional_field, "")
        if value == "":
            continue
        if not isinstance(value, str):
            raise ValueError(f"item {index} {optional_field} must be a string")
        normalized[optional_field] = value
    return normalized
