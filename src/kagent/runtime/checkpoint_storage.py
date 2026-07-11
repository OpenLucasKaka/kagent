from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DIRECTORY_MODE = 0o700
FILE_MODE = 0o600
MANIFEST_VERSION = 1
_SIGNING_KEY_NAME = ".checkpoint-signing-key"
_CHECKPOINT_ID_PATTERN = re.compile(
    r"^\d{8}T\d{6}\.\d{6}Z-[0-9a-f]{12}$"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def new_checkpoint_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{timestamp}-{secrets.token_hex(6)}"


def validate_checkpoint_id(checkpoint_id: str) -> None:
    if not isinstance(checkpoint_id, str) or not _CHECKPOINT_ID_PATTERN.fullmatch(
        checkpoint_id
    ):
        raise ValueError("invalid checkpoint_id")


def resolve_checkpoint_target(workspace_root: Path, relative_path: Any) -> Path:
    if not isinstance(relative_path, str):
        raise ValueError("checkpoint manifest is invalid")
    candidate = Path(relative_path)
    if candidate.is_absolute() or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        raise ValueError("checkpoint path must stay inside the workspace")
    target = workspace_root.joinpath(*candidate.parts)
    try:
        target.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("checkpoint path must stay inside the workspace") from exc
    return target


def ensure_store_layout(
    state_root: Path,
    workspace_directory: Path,
    checkpoint_directory: Path,
) -> None:
    reject_existing_symlink_chain(state_root)
    directories = (
        state_root,
        workspace_directory,
        workspace_directory / "checkpoints",
        checkpoint_directory,
    )
    for directory in directories:
        if directory.exists() and directory.is_symlink():
            raise ValueError("checkpoint path must not contain symlinks")
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(DIRECTORY_MODE)


def reject_existing_symlink_chain(path: Path) -> None:
    absolute_path = path.absolute()
    current = Path(absolute_path.anchor)
    for part in absolute_path.parts[1:]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError("checkpoint path must not contain symlinks")


def reject_symlink(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("checkpoint path must not contain symlinks")


def remove_checkpoint_directory(checkpoint_directory: Path) -> None:
    reject_symlink(checkpoint_directory)
    for path in checkpoint_directory.iterdir():
        reject_symlink(path)
        if not path.is_file():
            raise ValueError("checkpoint directory contains an unexpected entry")
        path.unlink()
    checkpoint_directory.rmdir()


def atomic_write_text(target: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.chmod(temporary_path, FILE_MODE)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(target)
        _fsync_directory(target.parent)
    except Exception:
        if descriptor != -1:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)
        raise


def write_signed_manifest(
    target: Path,
    manifest: dict[str, Any],
    state_root: Path,
) -> None:
    signing_key = load_or_create_signing_key(state_root)
    atomic_write_text(
        target,
        json.dumps(
            signed_manifest_payload(manifest, signing_key),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )


def read_signed_manifest(
    manifest_path: Path,
    state_root: Path,
    checkpoint_id: str,
) -> dict[str, Any]:
    try:
        envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("checkpoint manifest is invalid") from exc
    if (
        not isinstance(envelope, dict)
        or set(envelope) != {"manifest", "hmac_sha256"}
        or not isinstance(envelope["manifest"], dict)
        or not isinstance(envelope["hmac_sha256"], str)
    ):
        raise ValueError("checkpoint manifest is invalid")
    manifest = envelope["manifest"]
    expected_hmac = _manifest_hmac(manifest, read_signing_key(state_root))
    if not hmac.compare_digest(envelope["hmac_sha256"], expected_hmac):
        raise ValueError("checkpoint manifest integrity check failed")
    _validate_manifest(manifest, checkpoint_id)
    return manifest


def signed_manifest_payload(
    manifest: dict[str, Any],
    signing_key: bytes,
) -> dict[str, Any]:
    return {
        "manifest": manifest,
        "hmac_sha256": _manifest_hmac(manifest, signing_key),
    }


def load_or_create_signing_key(state_root: Path) -> bytes:
    key_path = state_root / _SIGNING_KEY_NAME
    reject_symlink(key_path)
    if key_path.exists():
        return read_signing_key(state_root)
    signing_key = secrets.token_bytes(32)
    try:
        descriptor = os.open(
            key_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            FILE_MODE,
        )
    except FileExistsError:
        return read_signing_key(state_root)
    try:
        os.write(descriptor, signing_key)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(state_root)
    return signing_key


def read_signing_key(state_root: Path) -> bytes:
    key_path = state_root / _SIGNING_KEY_NAME
    reject_existing_symlink_chain(state_root)
    reject_symlink(key_path)
    if not key_path.is_file():
        raise ValueError("checkpoint signing key is missing")
    signing_key = key_path.read_bytes()
    if len(signing_key) != 32:
        raise ValueError("checkpoint signing key is invalid")
    return signing_key


def _manifest_hmac(manifest: dict[str, Any], signing_key: bytes) -> str:
    canonical = json.dumps(
        manifest,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hmac.new(signing_key, canonical, hashlib.sha256).hexdigest()


def _validate_manifest(manifest: Any, checkpoint_id: str) -> None:
    if (
        not isinstance(manifest, dict)
        or manifest.get("version") != MANIFEST_VERSION
        or manifest.get("checkpoint_id") != checkpoint_id
        or manifest.get("status") not in {"prepared", "committed"}
        or not isinstance(manifest.get("created_at"), str)
        or not isinstance(manifest.get("entries"), list)
        or not manifest["entries"]
    ):
        raise ValueError("checkpoint manifest is invalid")
    paths = []
    for entry in manifest["entries"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "before", "after"}:
            raise ValueError("checkpoint manifest is invalid")
        if not isinstance(entry["path"], str):
            raise ValueError("checkpoint manifest is invalid")
        _validate_state(entry["before"])
        _validate_state(entry["after"])
        paths.append(entry["path"])
    if len(paths) != len(set(paths)):
        raise ValueError("checkpoint manifest contains duplicate paths")


def _validate_state(state: Any) -> None:
    if not isinstance(state, dict) or set(state) != {
        "exists",
        "sha256",
        "mode",
        "blob",
    }:
        raise ValueError("checkpoint manifest is invalid")
    exists = state["exists"]
    mode = state["mode"]
    blob = state["blob"]
    sha256 = state["sha256"]
    if not isinstance(exists, bool):
        raise ValueError("checkpoint manifest is invalid")
    if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 0o7777:
        raise ValueError("checkpoint manifest is invalid")
    if not isinstance(blob, str) or not isinstance(sha256, str):
        raise ValueError("checkpoint manifest is invalid")
    if exists:
        if Path(blob).name != blob or not blob or not _SHA256_PATTERN.fullmatch(sha256):
            raise ValueError("checkpoint manifest is invalid")
    elif blob or sha256:
        raise ValueError("checkpoint manifest is invalid")


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
