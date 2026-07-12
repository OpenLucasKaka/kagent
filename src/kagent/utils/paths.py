from __future__ import annotations

import os
import secrets
import stat
from contextlib import contextmanager
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
            home = str(Path.home())
        suffix = value[2:] if value != "~" else ""
        path = Path(home) / suffix
    else:
        path = Path(value)
    return Path(os.path.abspath(path))


def kagent_home(env: Optional[Mapping[str, str]] = None) -> Path:
    environment = os.environ if env is None else env
    if KAGENT_HOME_ENV_VAR in environment:
        configured = environment[KAGENT_HOME_ENV_VAR]
        if not configured.strip():
            raise ValueError("KAGENT_HOME must not be empty")
        if (
            not (configured == "~" or configured.startswith("~/"))
            and not Path(configured).is_absolute()
        ):
            raise ValueError("KAGENT_HOME must be an absolute or tilde-prefixed path")
        return _absolute_user_path(configured, environment)

    home = environment.get("HOME", "").strip()
    if not home:
        home = str(Path.home())
    return _absolute_user_path(home, environment) / ".kagent"


def kagent_config_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    return kagent_home(env) / "config"


def kagent_state_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    return kagent_home(env) / "state"


def kagent_cache_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    return kagent_home(env) / "cache"


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def open_directory_fd(path: Path, *, create: bool = False) -> int:
    if not path.is_absolute():
        raise ValueError(f"directory path must be absolute: {path}")
    flags = _directory_open_flags()
    current_fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, _OWNER_DIRECTORY_MODE, dir_fd=current_fd)
                except FileExistsError:
                    pass
                try:
                    next_fd = os.open(part, flags, dir_fd=current_fd)
                except OSError as exc:
                    raise ValueError(
                        f"directory path must not contain symlinks or non-directories: {path}"
                    ) from exc
            except OSError as exc:
                raise ValueError(
                    f"directory path must not contain symlinks or non-directories: {path}"
                ) from exc
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def ensure_directory_fd_matches_path(path: Path, directory_fd: int) -> None:
    try:
        path_stat = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"directory changed during operation: {path}") from exc
    descriptor_stat = os.fstat(directory_fd)
    if (
        not stat.S_ISDIR(path_stat.st_mode)
        or path_stat.st_dev != descriptor_stat.st_dev
        or path_stat.st_ino != descriptor_stat.st_ino
    ):
        raise ValueError(f"directory changed or became a symlink: {path}")


def _ensure_private_directory(path: Path) -> None:
    directory_fd = open_directory_fd(path, create=True)
    try:
        os.fchmod(directory_fd, _OWNER_DIRECTORY_MODE)
        ensure_directory_fd_matches_path(path, directory_fd)
    finally:
        os.close(directory_fd)


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


def _path_kind(path: Path) -> Optional[str]:
    try:
        parent_fd = open_directory_fd(path.parent)
    except FileNotFoundError:
        return None
    try:
        try:
            mode = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False).st_mode
        except FileNotFoundError:
            return None
        ensure_directory_fd_matches_path(path.parent, parent_fd)
    finally:
        os.close(parent_fd)
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        raise ValueError(f"migration path must not contain symlinks: {path}")
    return "other"


def _open_source_file(path: Path) -> int:
    parent_fd = open_directory_fd(path.parent)
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            source_fd = os.open(path.name, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise ValueError(
                f"migration source must be a regular file without symlinks: {path}"
            ) from exc
        try:
            if not stat.S_ISREG(os.fstat(source_fd).st_mode):
                raise ValueError(f"migration source must be a regular file: {path}")
            ensure_directory_fd_matches_path(path.parent, parent_fd)
            return source_fd
        except BaseException:
            os.close(source_fd)
            raise
    finally:
        os.close(parent_fd)


def _open_temporary_file(parent_fd: int, destination_name: str) -> Tuple[int, str]:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    for _ in range(128):
        name = f".{destination_name}.{secrets.token_hex(8)}"
        try:
            return os.open(name, flags, _OWNER_FILE_MODE, dir_fd=parent_fd), name
        except FileExistsError:
            continue
    raise OSError("unable to allocate an atomic migration temporary file")


@contextmanager
def _fdopen_stream(file_descriptor: int, mode: str, *, closefd: bool = True):
    try:
        stream = os.fdopen(file_descriptor, mode, closefd=closefd)
    except BaseException:
        if closefd:
            os.close(file_descriptor)
        raise
    try:
        yield stream
    finally:
        stream.close()


def _destination_entry_exists(parent_fd: int, name: str, path: Path) -> bool:
    try:
        mode = os.stat(name, dir_fd=parent_fd, follow_symlinks=False).st_mode
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(mode):
        raise ValueError(f"migration path must not contain symlinks: {path}")
    return True


def _atomic_copy_file(source: Path, destination: Path) -> None:
    _ensure_private_directory(destination.parent)
    destination_parent_fd = open_directory_fd(destination.parent)
    try:
        ensure_directory_fd_matches_path(destination.parent, destination_parent_fd)
        if _destination_entry_exists(destination_parent_fd, destination.name, destination):
            ensure_directory_fd_matches_path(destination.parent, destination_parent_fd)
            return
        source_fd = _open_source_file(source)
        try:
            with _fdopen_stream(source_fd, "rb", closefd=False) as source_stream:
                temporary_fd, temporary_name = _open_temporary_file(
                    destination_parent_fd, destination.name
                )
                try:
                    with _fdopen_stream(temporary_fd, "wb") as destination_stream:
                        while True:
                            chunk = source_stream.read(1024 * 1024)
                            if not chunk:
                                break
                            destination_stream.write(chunk)
                        destination_stream.flush()
                        os.fsync(destination_stream.fileno())
                    try:
                        os.link(
                            temporary_name,
                            destination.name,
                            src_dir_fd=destination_parent_fd,
                            dst_dir_fd=destination_parent_fd,
                            follow_symlinks=False,
                        )
                    except FileExistsError:
                        _destination_entry_exists(
                            destination_parent_fd, destination.name, destination
                        )
                    ensure_directory_fd_matches_path(destination.parent, destination_parent_fd)
                finally:
                    try:
                        os.unlink(temporary_name, dir_fd=destination_parent_fd)
                    except FileNotFoundError:
                        pass
        finally:
            os.close(source_fd)
    finally:
        os.close(destination_parent_fd)


def _scan_directory(source: Path) -> Tuple[List[Path], List[Path]]:
    directories: List[Path] = []
    files: List[Path] = []
    root_fd = open_directory_fd(source)

    def scan(directory_fd: int, directory: Path) -> None:
        ensure_directory_fd_matches_path(directory, directory_fd)
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                entry_path = directory / entry.name
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISLNK(mode):
                    raise ValueError(
                        f"migration directories must contain only regular files and directories, "
                        f"not symlinks: {entry_path}"
                    )
                if stat.S_ISDIR(mode):
                    directories.append(entry_path)
                    try:
                        child_fd = os.open(entry.name, _directory_open_flags(), dir_fd=directory_fd)
                    except OSError as exc:
                        raise ValueError(
                            f"migration directory changed or became a symlink: {entry_path}"
                        ) from exc
                    try:
                        scan(child_fd, entry_path)
                    finally:
                        os.close(child_fd)
                elif stat.S_ISREG(mode):
                    files.append(entry_path)
                else:
                    raise ValueError(
                        "migration directories must contain only regular files and directories: "
                        f"{entry_path}"
                    )
        ensure_directory_fd_matches_path(directory, directory_fd)

    try:
        scan(root_fd, source)
    finally:
        os.close(root_fd)
    return sorted(directories), sorted(files)


def _copy_directory(source: Path, destination: Path) -> None:
    directories, files = _scan_directory(source)
    destination_kind = _path_kind(destination)
    if destination_kind is not None and destination_kind != "directory":
        return
    _ensure_private_directory(destination)
    blocked_prefixes: List[Path] = []
    for directory in directories:
        relative = directory.relative_to(source)
        if any(prefix == relative or prefix in relative.parents for prefix in blocked_prefixes):
            continue
        target = destination / relative
        target_kind = _path_kind(target)
        if target_kind is not None and target_kind != "directory":
            blocked_prefixes.append(relative)
            continue
        _ensure_private_directory(target)
    for source_file in files:
        relative = source_file.relative_to(source)
        if any(prefix == relative or prefix in relative.parents for prefix in blocked_prefixes):
            continue
        _atomic_copy_file(source_file, destination / relative)


def _write_marker(marker: Path) -> None:
    marker_kind = _path_kind(marker)
    if marker_kind is not None:
        if marker_kind != "file":
            raise ValueError(f"migration marker must be a regular file: {marker}")
        parent_fd = open_directory_fd(marker.parent)
        try:
            flags = (
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0)
            )
            marker_fd = os.open(marker.name, flags, dir_fd=parent_fd)
            try:
                if not stat.S_ISREG(os.fstat(marker_fd).st_mode):
                    raise ValueError(f"migration marker must be a regular file: {marker}")
                os.fchmod(marker_fd, _OWNER_FILE_MODE)
                ensure_directory_fd_matches_path(marker.parent, parent_fd)
            finally:
                os.close(marker_fd)
        finally:
            os.close(parent_fd)
        return
    _ensure_private_directory(marker.parent)
    parent_fd = open_directory_fd(marker.parent)
    try:
        temporary_fd, temporary_name = _open_temporary_file(parent_fd, marker.name)
        try:
            with _fdopen_stream(temporary_fd, "wb") as stream:
                stream.write(b"complete\n")
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(
                    temporary_name,
                    marker.name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                if _path_kind(marker) != "file":
                    raise ValueError(f"migration marker must be a regular file: {marker}")
            ensure_directory_fd_matches_path(marker.parent, parent_fd)
        finally:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
    finally:
        os.close(parent_fd)


def migrate_legacy_kagent_state(env: Optional[Mapping[str, str]] = None) -> Path:
    environment = os.environ if env is None else env
    root = kagent_home(environment)
    marker = root / _MIGRATION_MARKER
    if KAGENT_HOME_ENV_VAR in environment:
        return marker

    marker_kind = _path_kind(marker)
    if marker_kind is not None:
        if marker_kind != "file":
            raise ValueError(f"migration marker must be a regular file: {marker}")
        _ensure_private_directory(root)
        _write_marker(marker)
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
        kind = _path_kind(source)
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
