from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePath
from typing import Any, Dict

VIRTUAL_WORKSPACE_KINDS = ("workspace", "reports", "logs", "policies", "memories")
_OWNER_ONLY_DIRECTORY_MODE = 0o700
_OWNER_ONLY_FILE_MODE = 0o600
_DEFAULT_MAX_READ_BYTES = 65536
_DEFAULT_MAX_LIST_DEPTH = 5
_DEFAULT_LIST_LIMIT = 500


class RuntimeWorkspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def ensure_layout(self) -> Dict[str, Any]:
        root = self.root
        root.mkdir(parents=True, exist_ok=True)
        root.chmod(_OWNER_ONLY_DIRECTORY_MODE)
        for kind in VIRTUAL_WORKSPACE_KINDS:
            directory = root / kind
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(_OWNER_ONLY_DIRECTORY_MODE)
        return {
            "root": str(root),
            "kinds": list(VIRTUAL_WORKSPACE_KINDS),
            "directory_permissions": "0700",
            "file_permissions": "0600",
        }

    def resolve(self, kind: str, relative_path: str | Path = ".") -> Path:
        base = self._kind_directory(kind)
        relative_parts = _safe_relative_parts(relative_path)
        target = base.joinpath(*relative_parts) if relative_parts else base
        _reject_symlink_traversal(base, target)
        try:
            target.resolve(strict=False).relative_to(base.resolve(strict=True))
        except ValueError as exc:
            raise ValueError("path must stay inside the virtual directory") from exc
        return target

    def write_text(
        self,
        kind: str,
        relative_path: str | Path,
        content: str,
        *,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        self.ensure_layout()
        target = self.resolve(kind, relative_path)
        if target.exists() and target.is_dir():
            raise ValueError("path is a directory")
        target.parent.mkdir(parents=True, exist_ok=True)
        _chmod_created_directories(self._kind_directory(kind), target.parent)
        _reject_symlink_traversal(self._kind_directory(kind), target)
        encoded = content.encode("utf-8")
        _write_owner_only_text_file(target, content)
        return _asset_metadata(
            root=self._kind_directory(kind),
            path=target,
            kind=kind,
            content_bytes=encoded,
            metadata=metadata or {},
        )

    def read_text(
        self,
        kind: str,
        relative_path: str | Path,
        *,
        max_bytes: int = _DEFAULT_MAX_READ_BYTES,
    ) -> Dict[str, Any]:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.ensure_layout()
        target = self.resolve(kind, relative_path)
        if not target.exists():
            raise ValueError("file does not exist")
        if target.is_dir():
            raise ValueError("path is a directory")
        body = target.read_bytes()
        visible = body[:max_bytes]
        return {
            **_asset_metadata(
                root=self._kind_directory(kind),
                path=target,
                kind=kind,
                content_bytes=body,
                metadata={},
            ),
            "content": visible.decode("utf-8", errors="replace"),
            "bytes": len(visible),
            "truncated": len(body) > max_bytes,
        }

    def list(
        self,
        kind: str,
        relative_path: str | Path = ".",
        *,
        max_depth: int = _DEFAULT_MAX_LIST_DEPTH,
        limit: int = _DEFAULT_LIST_LIMIT,
    ) -> Dict[str, Any]:
        if max_depth < 0:
            raise ValueError("max_depth must be non-negative")
        if limit < 1:
            raise ValueError("limit must be positive")
        self.ensure_layout()
        root = self.resolve(kind, relative_path)
        if not root.exists():
            raise ValueError("path does not exist")
        entries = []
        truncated = False
        for path in _iter_entries(root, max_depth=max_depth):
            if len(entries) >= limit:
                truncated = True
                break
            if path.is_symlink():
                continue
            entries.append(_list_entry(self._kind_directory(kind), path))
        return {
            "kind": kind,
            "root": _relative_asset_path(self._kind_directory(kind), root)
            if root != self._kind_directory(kind)
            else kind,
            "entries": entries,
            "file_count": len(entries),
            "truncated": truncated,
        }

    def search(
        self,
        kind: str,
        query: str,
        relative_path: str | Path = ".",
        *,
        max_depth: int = _DEFAULT_MAX_LIST_DEPTH,
        limit: int = 50,
        max_bytes: int = _DEFAULT_MAX_READ_BYTES,
    ) -> Dict[str, Any]:
        normalized_query = str(query)
        if not normalized_query:
            raise ValueError("query must be non-empty")
        if max_depth < 0:
            raise ValueError("max_depth must be non-negative")
        if limit < 1:
            raise ValueError("limit must be positive")
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.ensure_layout()
        root = self.resolve(kind, relative_path)
        if not root.exists():
            raise ValueError("path does not exist")
        matches = []
        truncated = False
        for path in _iter_entries(root, max_depth=max_depth):
            if path.is_symlink() or not path.is_file():
                continue
            body = path.read_bytes()
            visible = body[:max_bytes]
            text = visible.decode("utf-8", errors="replace")
            lines = text.splitlines()
            for line_number, line in enumerate(lines, start=1):
                column = line.find(normalized_query)
                if column < 0:
                    continue
                if len(matches) >= limit:
                    truncated = True
                    break
                previous_text = "\n".join(lines[: line_number - 1])
                if previous_text:
                    previous_text += "\n"
                byte_offset = len((previous_text + line[:column]).encode("utf-8"))
                matches.append(
                    {
                        "path": _relative_asset_path(self._kind_directory(kind), path),
                        "line_number": line_number,
                        "line": line,
                        "byte_offset": byte_offset,
                        "sha256": hashlib.sha256(body).hexdigest(),
                    }
                )
            if truncated:
                break
        return {
            "kind": kind,
            "root": _relative_asset_path(self._kind_directory(kind), root)
            if root != self._kind_directory(kind)
            else kind,
            "query": normalized_query,
            "matches": matches,
            "match_count": len(matches),
            "truncated": truncated,
        }

    def _kind_directory(self, kind: str) -> Path:
        if kind not in VIRTUAL_WORKSPACE_KINDS:
            raise ValueError("unknown virtual directory kind")
        return self.root / kind


def _safe_relative_parts(relative_path: str | Path) -> tuple[str, ...]:
    raw_path = PurePath(relative_path)
    if raw_path.is_absolute():
        raise ValueError("path must be relative")
    parts = tuple(part for part in raw_path.parts if part not in {"", "."})
    if any(part == ".." for part in parts):
        raise ValueError("path must stay inside the virtual directory")
    return parts


def _reject_symlink_traversal(base: Path, target: Path) -> None:
    current = base
    if current.exists() and current.is_symlink():
        raise ValueError("path must not traverse symlinks")
    try:
        relative_parts = target.relative_to(base).parts
    except ValueError as exc:
        raise ValueError("path must stay inside the virtual directory") from exc
    for part in relative_parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError("path must not traverse symlinks")


def _chmod_created_directories(base: Path, target_parent: Path) -> None:
    current = base
    for part in target_parent.relative_to(base).parts:
        current = current / part
        current.chmod(_OWNER_ONLY_DIRECTORY_MODE)


def _write_owner_only_text_file(target: Path, content: str) -> None:
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        os.chmod(temporary_path, _OWNER_ONLY_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(target)
        target.chmod(_OWNER_ONLY_FILE_MODE)
    except Exception:
        if fd != -1:
            os.close(fd)
        temporary_path.unlink(missing_ok=True)
        raise


def _asset_metadata(
    *,
    root: Path,
    path: Path,
    kind: str,
    content_bytes: bytes,
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    stat_result = path.stat()
    timestamp = _timestamp(stat_result.st_mtime)
    return {
        "kind": kind,
        "path": _relative_asset_path(root, path),
        "bytes": len(content_bytes),
        "sha256": hashlib.sha256(content_bytes).hexdigest(),
        "created_at": timestamp,
        "updated_at": timestamp,
        "metadata": metadata,
    }


def _relative_asset_path(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    return "." if not relative.parts else relative.as_posix()


def _timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _iter_entries(root: Path, *, max_depth: int) -> list[Path]:
    if root.is_file():
        return [root]
    entries = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if len(path.relative_to(root).parts) > max_depth:
            continue
        entries.append(path)
    return entries


def _list_entry(root: Path, path: Path) -> Dict[str, Any]:
    if path.is_dir():
        return {
            "path": _relative_asset_path(root, path),
            "type": "directory",
            "bytes": 0,
            "sha256": "",
        }
    body = path.read_bytes()
    return {
        "path": _relative_asset_path(root, path),
        "type": "file",
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
