from __future__ import annotations

import fcntl
import os
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class TextFileState:
    content: str | None
    mode: int


@contextmanager
def workspace_transaction(workspace_root: Path) -> Iterator[None]:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(workspace_root, flags)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def commit_text_changes(
    workspace_root: Path,
    staged_contents: dict[Path, str | None],
    *,
    original_states: dict[Path, TextFileState] | None = None,
    target_modes: dict[Path, int] | None = None,
) -> None:
    snapshots = original_states or capture_text_states(staged_contents)
    resolved_target_modes = target_modes or {}
    created_directories: list[Path] = []
    try:
        for target, content in staged_contents.items():
            _reject_symlink_parts(workspace_root, target)
            if content is None:
                if target.exists():
                    target.unlink()
                    _fsync_directory(target.parent)
                continue
            _ensure_parent(
                workspace_root,
                target.parent,
                created_directories=created_directories,
            )
            _atomic_write_text(target, content, mode=resolved_target_modes.get(target))
    except Exception as commit_error:
        try:
            _rollback(
                workspace_root,
                snapshots,
                created_directories=created_directories,
            )
        except Exception as rollback_error:
            raise RuntimeError(
                f"patch commit failed: {commit_error}; rollback failed: {rollback_error}"
            ) from commit_error
        raise


def capture_text_states(paths) -> dict[Path, TextFileState]:
    return {target: _snapshot(target) for target in paths}


def validate_workspace_targets(workspace_root: Path, paths) -> None:
    for target in paths:
        target.relative_to(workspace_root)
        _reject_symlink_parts(workspace_root, target)


def _snapshot(target: Path) -> TextFileState:
    if not target.exists():
        return TextFileState(content=None, mode=0o600)
    if not target.is_file():
        raise ValueError("path is not a regular file")
    return TextFileState(
        content=target.read_text(encoding="utf-8"),
        mode=stat.S_IMODE(target.stat().st_mode),
    )


def _rollback(
    workspace_root: Path,
    snapshots: dict[Path, TextFileState],
    *,
    created_directories: list[Path],
) -> None:
    errors = []
    for target, snapshot in reversed(tuple(snapshots.items())):
        try:
            _reject_symlink_parts(workspace_root, target)
            if snapshot.content is None:
                if target.exists():
                    target.unlink()
                    _fsync_directory(target.parent)
                continue
            _ensure_parent(workspace_root, target.parent, created_directories=[])
            _atomic_write_text(target, snapshot.content, mode=snapshot.mode)
        except Exception as exc:
            relative_path = target.relative_to(workspace_root).as_posix()
            errors.append(f"{relative_path}: {exc}")
    for directory in reversed(created_directories):
        try:
            directory.rmdir()
            _fsync_directory(directory.parent)
        except OSError:
            continue
    if errors:
        raise RuntimeError("; ".join(errors))


def _reject_symlink_parts(workspace_root: Path, target: Path) -> None:
    current = workspace_root
    for part in target.relative_to(workspace_root).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("path must not be a symlink")
        if not current.exists():
            return


def _ensure_parent(
    workspace_root: Path,
    target_parent: Path,
    *,
    created_directories: list[Path],
) -> None:
    current = workspace_root
    for part in target_parent.relative_to(workspace_root).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("path must not be a symlink")
        if current.exists():
            if not current.is_dir():
                raise ValueError("parent path is not a directory")
            continue
        current.mkdir()
        created_directories.append(current)
        _fsync_directory(current.parent)


def _atomic_write_text(
    target: Path,
    content: str,
    *,
    mode: int | None = None,
) -> None:
    resolved_mode = mode
    if resolved_mode is None:
        resolved_mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o600
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.chmod(temporary_path, resolved_mode)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
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


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
