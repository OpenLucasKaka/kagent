from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from typing import List, Mapping, Optional, Tuple

KAGENT_HOME_ENV_VAR = "KAGENT_HOME"
_MIGRATION_MARKER = ".migration-v1-complete"
_OWNER_DIRECTORY_MODE = 0o700
_OWNER_FILE_MODE = 0o600


def _absolute_user_path(value: str, env: Mapping[str, str]) -> Path:
    if value == "~" or value.startswith("~/"):
        home = env.get("HOME", "").strip()
        if not home:
            raise ValueError("HOME must be set to expand a user-relative path")
        suffix = value[2:] if value != "~" else ""
        path = Path(home) / suffix
    else:
        path = Path(value)
    return path.absolute()


def kagent_home(env: Optional[Mapping[str, str]] = None) -> Path:
    environment = os.environ if env is None else env
    if KAGENT_HOME_ENV_VAR in environment:
        configured = environment[KAGENT_HOME_ENV_VAR]
        if not configured.strip():
            raise ValueError("KAGENT_HOME must not be empty")
        return _absolute_user_path(configured, environment)

    home = environment.get("HOME", "").strip()
    if not home:
        raise ValueError("HOME must be set when KAGENT_HOME is not configured")
    return _absolute_user_path(home, environment) / ".kagent"


def kagent_config_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    return kagent_home(env) / "config"


def kagent_state_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    return kagent_home(env) / "state"


def kagent_cache_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    return kagent_home(env) / "cache"


def _reject_symlink_chain(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            break
        if stat.S_ISLNK(mode):
            raise ValueError(f"migration path must not contain symlinks: {current}")


def _ensure_private_directory(path: Path) -> None:
    _reject_symlink_chain(path)
    path.mkdir(mode=_OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
    _reject_symlink_chain(path)
    if not path.is_dir():
        raise ValueError(f"migration directory is not a directory: {path}")
    path.chmod(_OWNER_DIRECTORY_MODE)


def _legacy_root(
    environment: Mapping[str, str], variable: str, default_suffix: Tuple[str, ...]
) -> Path:
    configured = environment.get(variable, "").strip()
    if configured:
        return _absolute_user_path(configured, environment) / "kagent"
    home = environment.get("HOME", "").strip()
    if not home:
        raise ValueError(f"HOME must be set when {variable} is not configured")
    return _absolute_user_path(home, environment).joinpath(*default_suffix, "kagent")


def _source_kind(path: Path) -> Optional[str]:
    _reject_symlink_chain(path)
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        raise ValueError(f"migration path must not contain symlinks: {path}")
    raise ValueError(f"migration sources must contain only regular files and directories: {path}")


def _destination_exists(path: Path) -> bool:
    _reject_symlink_chain(path)
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _atomic_copy_file(source: Path, destination: Path) -> None:
    if _destination_exists(destination):
        return
    _ensure_private_directory(destination.parent)
    _reject_symlink_chain(source)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    source_fd = os.open(source, flags)
    temporary_path: Optional[Path] = None
    try:
        if not stat.S_ISREG(os.fstat(source_fd).st_mode):
            raise ValueError(f"migration sources must contain only regular files: {source}")
        temporary_fd, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", dir=str(destination.parent)
        )
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(temporary_fd, _OWNER_FILE_MODE)
            with os.fdopen(source_fd, "rb", closefd=False) as source_stream:
                with os.fdopen(temporary_fd, "wb") as destination_stream:
                    while True:
                        chunk = source_stream.read(1024 * 1024)
                        if not chunk:
                            break
                        destination_stream.write(chunk)
                    destination_stream.flush()
                    os.fsync(destination_stream.fileno())
            try:
                os.link(temporary_path, destination)
            except FileExistsError:
                _reject_symlink_chain(destination)
        finally:
            temporary_path.unlink(missing_ok=True)
    finally:
        os.close(source_fd)


def _scan_directory(source: Path) -> Tuple[List[Path], List[Path]]:
    directories: List[Path] = []
    files: List[Path] = []
    pending = [source]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                entry_path = Path(entry.path)
                if entry.is_symlink():
                    raise ValueError(
                        f"migration directories must contain only regular files and directories, "
                        f"not symlinks: {entry_path}"
                    )
                if entry.is_dir(follow_symlinks=False):
                    directories.append(entry_path)
                    pending.append(entry_path)
                elif entry.is_file(follow_symlinks=False):
                    files.append(entry_path)
                else:
                    raise ValueError(
                        "migration directories must contain only regular files and directories: "
                        f"{entry_path}"
                    )
    return sorted(directories), sorted(files)


def _copy_directory(source: Path, destination: Path) -> None:
    directories, files = _scan_directory(source)
    if _destination_exists(destination) and not destination.is_dir():
        return
    _ensure_private_directory(destination)
    for directory in directories:
        relative = directory.relative_to(source)
        _ensure_private_directory(destination / relative)
    for source_file in files:
        relative = source_file.relative_to(source)
        _atomic_copy_file(source_file, destination / relative)


def _write_marker(marker: Path) -> None:
    if _destination_exists(marker):
        if not marker.is_file():
            raise ValueError(f"migration marker is not a regular file: {marker}")
        marker.chmod(_OWNER_FILE_MODE)
        return
    _ensure_private_directory(marker.parent)
    temporary_fd, temporary_name = tempfile.mkstemp(
        prefix=f".{marker.name}.", dir=str(marker.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(temporary_fd, _OWNER_FILE_MODE)
        with os.fdopen(temporary_fd, "wb") as stream:
            stream.write(b"complete\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, marker)
        except FileExistsError:
            _reject_symlink_chain(marker)
    finally:
        temporary_path.unlink(missing_ok=True)


def migrate_legacy_kagent_state(env: Optional[Mapping[str, str]] = None) -> Path:
    environment = os.environ if env is None else env
    root = kagent_home(environment)
    marker = root / _MIGRATION_MARKER
    if KAGENT_HOME_ENV_VAR in environment:
        return marker

    _reject_symlink_chain(marker)
    if marker.exists():
        _ensure_private_directory(root)
        marker.chmod(_OWNER_FILE_MODE)
        return marker

    legacy_config = _legacy_root(environment, "XDG_CONFIG_HOME", (".config",))
    legacy_state = _legacy_root(environment, "XDG_STATE_HOME", (".local", "state"))
    migrations = [
        (legacy_config / "provider.json", root / "config" / "provider.json", "file"),
        (legacy_state / "session-memory.json", root / "state" / "session-memory.json", "file"),
        (legacy_state / "history", root / "state" / "history", "file"),
        (
            legacy_state / "pending-approvals",
            root / "state" / "pending-approvals",
            "directory",
        ),
        (legacy_state / "patches", root / "state" / "patches", "directory"),
    ]

    for source, destination, expected_kind in migrations:
        kind = _source_kind(source)
        if kind is None:
            continue
        if kind != expected_kind:
            raise ValueError(f"unexpected legacy migration source type: {source}")
        if kind == "file":
            _atomic_copy_file(source, destination)
        else:
            _copy_directory(source, destination)

    _write_marker(marker)
    return marker
