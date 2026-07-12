from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

from kagent.utils.paths import kagent_state_dir, migrate_legacy_kagent_state

PENDING_APPROVAL_PATH_ENV_VAR = "KAGENT_PENDING_APPROVAL_PATH"
_SCHEMA_VERSION = "1"
_MAX_SNAPSHOT_AGE_SECONDS = 24 * 60 * 60
_MAX_CLOCK_SKEW_SECONDS = 5 * 60
_VALID_PHASES = {"awaiting_approval", "approved_executing"}


def default_pending_approval_path(
    env: Mapping[str, str] | None = None,
    *,
    workspace: str | Path | None = None,
) -> str:
    source = os.environ if env is None else env
    configured = source.get(PENDING_APPROVAL_PATH_ENV_VAR, "").strip()
    if configured:
        return configured
    migrate_legacy_kagent_state(source)
    root = kagent_state_dir(source)
    workspace_root = Path.cwd() if workspace is None else Path(workspace)
    identity = hashlib.sha256(
        str(workspace_root.resolve()).encode("utf-8")
    ).hexdigest()
    return str(root / "pending-approvals" / f"{identity}.json")


def load_pending_approval(path: str) -> dict[str, Any] | None:
    if not path:
        return None
    target = Path(path)
    _reject_symlink_chain(target)
    if not target.exists():
        return None
    if not target.is_file():
        raise ValueError("pending approval path is not a regular file")
    _require_owner_only_file(target)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("pending approval state is invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _SCHEMA_VERSION
        or not isinstance(payload.get("action"), dict)
        or not isinstance(payload.get("goal"), str)
        or not isinstance(payload.get("runtime_goal"), str)
        or not isinstance(payload.get("plan"), dict)
        or payload.get("phase") not in _VALID_PHASES
        or isinstance(payload.get("saved_at"), bool)
        or not isinstance(payload.get("saved_at"), (int, float))
        or not str(payload["action"].get("id", "")).strip()
    ):
        raise ValueError("pending approval state is invalid")
    age_seconds = time.time() - float(payload["saved_at"])
    if age_seconds > _MAX_SNAPSHOT_AGE_SECONDS:
        clear_pending_approval(path)
        return None
    if age_seconds < -_MAX_CLOCK_SKEW_SECONDS:
        raise ValueError("pending approval state is invalid")
    return {
        "action": payload["action"],
        "goal": payload["goal"],
        "runtime_goal": payload["runtime_goal"],
        "plan": payload["plan"],
        "phase": payload["phase"],
    }


def save_pending_approval(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    phase = payload.get("phase", "awaiting_approval")
    if phase not in _VALID_PHASES:
        raise ValueError("pending approval phase is invalid")
    target = Path(path)
    _reject_symlink_chain(target)
    _ensure_owner_only_directory(target.parent)
    body = {
        "schema_version": _SCHEMA_VERSION,
        "action": payload["action"],
        "goal": payload["goal"],
        "runtime_goal": payload["runtime_goal"],
        "plan": payload["plan"],
        "phase": phase,
        "saved_at": time.time(),
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.chmod(temporary_path, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(body, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(target)
        target.chmod(0o600)
        _fsync_directory(target.parent)
    except Exception:
        if descriptor != -1:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)
        raise


def clear_pending_approval(path: str) -> None:
    if not path:
        return
    target = Path(path)
    _reject_symlink_chain(target)
    if target.exists():
        if not target.is_file():
            raise ValueError("pending approval path is not a regular file")
        target.unlink()
        _fsync_directory(target.parent)


def _reject_symlink_chain(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError("pending approval path must not contain symlinks")


def _ensure_owner_only_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    current = directory
    while current != current.parent and current.name in {
        "pending-approvals",
        "kagent",
    }:
        current.chmod(0o700)
        current = current.parent
    directory.chmod(0o700)


def _require_owner_only_file(path: Path) -> None:
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise ValueError("pending approval file must be owner-only")


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
