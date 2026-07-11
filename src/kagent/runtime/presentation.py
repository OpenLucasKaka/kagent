from __future__ import annotations

from typing import Any, Dict

from kagent.runtime.redaction import redact_runtime_text

MAX_PRESENTATION_CONTENT_CHARS = 4000


def project_runtime_presentation(
    tool: str,
    status: str,
    output: Dict[str, Any],
) -> Dict[str, Any]:
    if status != "ok" or not isinstance(output, dict):
        return {}

    projectors = {
        "artifact": _project_artifact,
        "apply_patch": _project_apply_patch,
        "workspace_diff": _project_workspace_diff,
        "open_url": _project_open_url,
        "open_app": _project_open_app,
        "http_request": _project_http_request,
        "shell_command": _project_shell_command,
    }
    projector = projectors.get(tool)
    if projector is None:
        return {}
    return projector(output)


def _project_artifact(output: Dict[str, Any]) -> Dict[str, Any]:
    title = _string(output.get("title"))
    content = _string(output.get("content"))
    if not title or not content:
        return {}
    kind = _display_label(output.get("kind"))
    artifact_format = _display_label(output.get("format"))
    byte_count = output.get("bytes")
    bytes_label = f"{byte_count} bytes" if isinstance(byte_count, int) else ""
    detail = " · ".join(
        part for part in (kind, artifact_format, bytes_label) if part
    )
    visible, truncated = _bounded_content(content)
    return _presentation_with_content(
        f"Created {title}",
        detail,
        visible,
        truncated,
    )


def _project_apply_patch(output: Dict[str, Any]) -> Dict[str, Any]:
    changed_files = output.get("changed_files")
    if not isinstance(changed_files, list) or not changed_files:
        return {}
    paths = []
    for item in changed_files:
        if not isinstance(item, dict):
            continue
        path = _string(item.get("path"))
        if path:
            paths.append(path)
    if not paths:
        return {}
    count = len(paths)
    visible_paths = paths[:3]
    path_detail = ", ".join(visible_paths)
    if count > len(visible_paths):
        path_detail += f", +{count - len(visible_paths)} more"
    label = "file" if count == 1 else "files"
    return _presentation("Updated files", f"{count} {label}: {path_detail}")


def _project_workspace_diff(output: Dict[str, Any]) -> Dict[str, Any]:
    path = _string(output.get("path"))
    diff = _string(output.get("diff"))
    if not path or not diff:
        return {}
    kind = _string(output.get("kind"))
    detail = f"{kind}/{path}" if kind else path
    visible, truncated = _bounded_content(
        diff,
        already_truncated=output.get("truncated") is True,
    )
    return _presentation_with_content(
        "Workspace changes",
        detail,
        visible,
        truncated,
    )


def _project_open_url(output: Dict[str, Any]) -> Dict[str, Any]:
    url = _string(output.get("url"))
    if output.get("opened") is not True or not url:
        return {}
    return _presentation("Opened URL", url)


def _project_open_app(output: Dict[str, Any]) -> Dict[str, Any]:
    application = _string(output.get("application"))
    if output.get("opened") is not True or not application:
        return {}
    return _presentation("Opened application", application)


def _project_http_request(output: Dict[str, Any]) -> Dict[str, Any]:
    url = _string(output.get("url"))
    status_code = output.get("status_code")
    if not url or not isinstance(status_code, int):
        return {}
    content_type = _string(output.get("content_type"))
    detail = " · ".join(
        part for part in (str(status_code), content_type, url) if part
    )
    return _presentation("Fetched URL", detail)


def _project_shell_command(output: Dict[str, Any]) -> Dict[str, Any]:
    exit_code = output.get("exit_code")
    if not isinstance(exit_code, int):
        return {}
    duration = output.get("duration_seconds")
    detail_parts = [f"Exit {exit_code}"]
    if isinstance(duration, (int, float)):
        detail_parts.append(f"{duration}s")
    stdout = _string(output.get("stdout"))
    stderr = _string(output.get("stderr"))
    content = "\n".join(part for part in (stdout, stderr) if part)
    visible, truncated = _bounded_content(
        content,
        already_truncated=output.get("truncated") is True,
    )
    return _presentation_with_content(
        "Command completed",
        " · ".join(detail_parts),
        visible,
        truncated,
    )


def _presentation(title: str, detail: str) -> Dict[str, Any]:
    return {
        "title": redact_runtime_text(title),
        "detail": redact_runtime_text(detail),
    }


def _presentation_with_content(
    title: str,
    detail: str,
    content: str,
    truncated: bool,
) -> Dict[str, Any]:
    return {
        **_presentation(title, detail),
        "content": content,
        "truncated": truncated,
    }


def _bounded_content(
    content: str,
    *,
    already_truncated: bool = False,
) -> tuple[str, bool]:
    redacted = redact_runtime_text(content)
    was_bounded = len(redacted) > MAX_PRESENTATION_CONTENT_CHARS
    return (
        redacted[:MAX_PRESENTATION_CONTENT_CHARS],
        already_truncated or was_bounded,
    )


def _display_label(value: Any) -> str:
    text = _string(value)
    if not text:
        return ""
    return " ".join(part.capitalize() for part in text.replace("_", " ").split())


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""
