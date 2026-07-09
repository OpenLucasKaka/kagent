from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Union

SandboxArgv = Union[str, List[str]]


@dataclass(frozen=True)
class ShellSandboxExecution:
    argv: SandboxArgv
    shell: bool
    env: Dict[str, str]
    metadata: Dict[str, str]
    profile: str = ""


@dataclass(frozen=True)
class ShellSandboxResult:
    completed: subprocess.CompletedProcess
    metadata: Dict[str, str]


def prepare_shell_sandbox(
    command: str,
    *,
    workspace_root: Path,
    cwd: Path,
    env: Dict[str, str],
) -> ShellSandboxExecution:
    system = platform.system().lower()
    if system == "darwin":
        return _prepare_macos_seatbelt(command, workspace_root=workspace_root, env=env)
    if system == "linux":
        return _prepare_linux_bwrap(command, workspace_root=workspace_root, cwd=cwd, env=env)
    if system == "windows":
        return _soft_execution(command, env=env, backend="windows-soft")
    return _soft_execution(command, env=env, backend="soft")


def run_shell_sandboxed(
    command: str,
    *,
    workspace_root: Path,
    cwd: Path,
    env: Dict[str, str],
    timeout_seconds: float,
) -> ShellSandboxResult:
    execution = prepare_shell_sandbox(
        command,
        workspace_root=workspace_root,
        cwd=cwd,
        env=env,
    )
    try:
        completed = _run_prepared_execution(execution, cwd=cwd, timeout_seconds=timeout_seconds)
        if _native_sandbox_startup_failed(execution, completed):
            fallback = _soft_execution(
                command,
                env=env,
                backend="soft",
                fallback_reason="native sandbox startup failed",
            )
            completed = _run_prepared_execution(
                fallback,
                cwd=cwd,
                timeout_seconds=timeout_seconds,
            )
            return ShellSandboxResult(completed=completed, metadata=fallback.metadata)
        return ShellSandboxResult(completed=completed, metadata=execution.metadata)
    except (FileNotFoundError, PermissionError, OSError):
        fallback = _soft_execution(
            command,
            env=env,
            backend="soft",
            fallback_reason="native sandbox exec failed",
        )
        completed = _run_prepared_execution(fallback, cwd=cwd, timeout_seconds=timeout_seconds)
        return ShellSandboxResult(completed=completed, metadata=fallback.metadata)


def _run_prepared_execution(
    execution: ShellSandboxExecution,
    *,
    cwd: Path,
    timeout_seconds: float,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        execution.argv,
        shell=execution.shell,
        cwd=str(cwd),
        env=execution.env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=False,
        timeout=timeout_seconds,
        start_new_session=True,
    )


def _native_sandbox_startup_failed(
    execution: ShellSandboxExecution,
    completed: subprocess.CompletedProcess,
) -> bool:
    if execution.metadata.get("enforced") != "true" or completed.returncode == 0:
        return False
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace").lower()
    backend = execution.metadata.get("backend", "")
    if backend == "linux-bwrap":
        startup_markers = (
            "creating new namespace failed",
            "bubblewrap:",
            "bwrap:",
            "failed to make",
        )
        return any(marker in stderr for marker in startup_markers)
    if backend == "macos-seatbelt":
        return "sandbox-exec: execvp" in stderr
    return False


def _prepare_macos_seatbelt(
    command: str,
    *,
    workspace_root: Path,
    env: Dict[str, str],
) -> ShellSandboxExecution:
    sandbox_exec = shutil.which("sandbox-exec")
    if not sandbox_exec:
        return _soft_execution(
            command,
            env=env,
            backend="soft",
            fallback_reason="native sandbox unavailable",
        )
    profile = _macos_seatbelt_profile(workspace_root)
    return ShellSandboxExecution(
        argv=[
            sandbox_exec,
            "-p",
            profile,
            "/bin/bash",
            "--noprofile",
            "--norc",
            "-c",
            command,
        ],
        shell=False,
        env=env,
        metadata=_sandbox_metadata(backend="macos-seatbelt", enforced=True),
        profile=profile,
    )


def _prepare_linux_bwrap(
    command: str,
    *,
    workspace_root: Path,
    cwd: Path,
    env: Dict[str, str],
) -> ShellSandboxExecution:
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return _soft_execution(
            command,
            env=env,
            backend="soft",
            fallback_reason="native sandbox unavailable",
        )
    argv: List[str] = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--unshare-net",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
    ]
    for source in _linux_readonly_binds():
        argv.extend(["--ro-bind", source, source])
    argv.extend(["--bind", str(workspace_root), str(workspace_root)])
    argv.extend(["--chdir", str(cwd)])
    argv.extend(["/bin/sh", "-lc", command])
    return ShellSandboxExecution(
        argv=argv,
        shell=False,
        env=env,
        metadata=_sandbox_metadata(backend="linux-bwrap", enforced=True),
    )


def _linux_readonly_binds() -> Sequence[str]:
    candidates = (
        "/bin",
        "/usr",
        "/lib",
        "/lib64",
        "/etc/alternatives",
        "/etc/ssl",
        "/etc/ca-certificates",
    )
    return tuple(path for path in candidates if Path(path).exists())


def _soft_execution(
    command: str,
    *,
    env: Dict[str, str],
    backend: str,
    fallback_reason: str = "",
) -> ShellSandboxExecution:
    return ShellSandboxExecution(
        argv=command,
        shell=True,
        env=env,
        metadata=_sandbox_metadata(
            backend=backend,
            enforced=False,
            fallback_reason=fallback_reason,
        ),
    )


def _sandbox_metadata(
    *,
    backend: str,
    enforced: bool,
    fallback_reason: str = "",
) -> Dict[str, str]:
    metadata = {
        "enabled": "true",
        "backend": backend,
        "enforced": "true" if enforced else "false",
        "filesystem": "workspace",
        "network": "disabled",
        "env_policy": "minimal",
    }
    if fallback_reason:
        metadata["fallback_reason"] = fallback_reason
    return metadata


def _macos_seatbelt_profile(workspace_root: Path) -> str:
    workspace_read_rules = " ".join(
        f"(subpath {_seatbelt_string(str(path))})"
        for path in _macos_path_aliases(workspace_root)
    )
    read_exception_filters = _macos_read_exception_filters(workspace_root)
    runtime_read_rules = " ".join(
        f"(subpath {_seatbelt_string(str(path))})"
        for runtime_path in _macos_runtime_read_paths()
        for path in _macos_path_aliases(runtime_path)
    )
    workspace_write_rules = " ".join(
        f"(subpath {_seatbelt_string(str(path))})"
        for path in _macos_path_aliases(workspace_root)
    )
    return "\n".join(
        [
            "(version 1)",
            "(allow default)",
            "(deny network*)",
            "(deny file-read*",
            "  (require-all",
            '    (subpath "/Users")',
            "    (require-not",
            "      (require-any",
            f"        {read_exception_filters}))))",
            f"(allow file-read* {workspace_read_rules})",
            f"(allow file-read* {runtime_read_rules})" if runtime_read_rules else "",
            "(deny file-write*)",
            f"(allow file-write* {workspace_write_rules})",
        ]
    )


def _seatbelt_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _macos_runtime_read_paths() -> Sequence[Path]:
    candidates = {
        Path(sys.executable).absolute().parent,
        Path(sys.executable).resolve().parent,
        Path(sys.prefix).resolve(),
    }
    return tuple(path for path in candidates if str(path).startswith("/Users/"))


def _macos_read_exception_filters(workspace_root: Path) -> str:
    subpaths = set(_macos_path_aliases(workspace_root))
    for runtime_path in _macos_runtime_read_paths():
        subpaths.update(_macos_path_aliases(runtime_path))
    literals = set(subpaths)
    for path in tuple(subpaths):
        literals.update(_macos_user_ancestor_literals(path))
    filters = [
        f"(subpath {_seatbelt_string(str(path))})"
        for path in sorted(subpaths, key=str)
    ]
    filters.extend(
        f"(literal {_seatbelt_string(str(path))})"
        for path in sorted(literals, key=str)
    )
    return " ".join(filters)


def _macos_user_ancestor_literals(path: Path) -> Sequence[Path]:
    candidates = [path]
    candidates.extend(path.parents)
    return tuple(candidate for candidate in candidates if str(candidate).startswith("/Users"))


def _macos_path_aliases(path: Path) -> Sequence[Path]:
    path_text = str(path)
    aliases = {path}
    if path_text.startswith(("/var/", "/tmp/", "/etc/")):
        aliases.add(Path(f"/private{path_text}"))
    if path_text.startswith("/private/"):
        aliases.add(Path(path_text.removeprefix("/private")))
    return tuple(aliases)
