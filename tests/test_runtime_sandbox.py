import subprocess
from pathlib import Path

from kagent.runtime import sandbox as runtime_sandbox


def test_macos_shell_sandbox_uses_seatbelt_when_available(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_sandbox.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(runtime_sandbox.shutil, "which", lambda name: f"/usr/bin/{name}")

    execution = runtime_sandbox.prepare_shell_sandbox(
        "echo hello",
        workspace_root=tmp_path,
        cwd=tmp_path,
        env={"PATH": "/usr/bin"},
    )

    assert execution.argv[:3] == ["/usr/bin/sandbox-exec", "-p", execution.profile]
    assert execution.argv[-5:] == [
        "/bin/bash",
        "--noprofile",
        "--norc",
        "-c",
        "echo hello",
    ]
    assert execution.shell is False
    assert execution.metadata["backend"] == "macos-seatbelt"
    assert execution.metadata["enforced"] == "true"
    assert execution.metadata["filesystem"] == "workspace"
    assert execution.metadata["network"] == "disabled"
    assert "(deny network*)" in execution.profile
    assert "(allow file-read*)" not in execution.profile
    assert '(subpath "/Users")' in execution.profile
    assert "(require-not" in execution.profile
    assert "(require-any" in execution.profile
    assert "(deny file-write*)" in execution.profile
    assert f'(subpath "{tmp_path}")' in execution.profile


def test_macos_shell_sandbox_allows_raw_python_executable_directory(
    monkeypatch,
):
    executable = Path("/Users/kaka/project/.venv/bin/python")
    resolved = Path("/Applications/Xcode.app/python3")

    monkeypatch.setattr(runtime_sandbox.sys, "executable", str(executable))
    monkeypatch.setattr(runtime_sandbox.sys, "prefix", "/Users/kaka/project/.venv")
    monkeypatch.setattr(
        runtime_sandbox.Path,
        "resolve",
        lambda self: resolved if self == executable else self,
    )

    paths = runtime_sandbox._macos_runtime_read_paths()

    assert executable.parent in paths


def test_macos_shell_sandbox_allows_private_workspace_alias(monkeypatch):
    monkeypatch.setattr(runtime_sandbox.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(runtime_sandbox.shutil, "which", lambda name: f"/usr/bin/{name}")

    execution = runtime_sandbox.prepare_shell_sandbox(
        "echo ok > inside.txt",
        workspace_root=Path("/var/folders/kagent/workspace"),
        cwd=Path("/var/folders/kagent/workspace"),
        env={"PATH": "/usr/bin"},
    )

    assert '(subpath "/var/folders/kagent/workspace")' in execution.profile
    assert '(subpath "/private/var/folders/kagent/workspace")' in execution.profile


def test_linux_shell_sandbox_uses_bubblewrap_when_available(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_sandbox.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runtime_sandbox.shutil, "which", lambda name: f"/usr/bin/{name}")

    execution = runtime_sandbox.prepare_shell_sandbox(
        "pwd",
        workspace_root=tmp_path,
        cwd=tmp_path,
        env={"PATH": "/usr/bin"},
    )

    assert execution.argv[0] == "/usr/bin/bwrap"
    assert "--unshare-net" in execution.argv
    assert "--die-with-parent" in execution.argv
    assert ["--bind", str(tmp_path), str(tmp_path)] == [
        execution.argv[index : index + 3]
        for index, value in enumerate(execution.argv)
        if value == "--bind"
    ][0]
    assert execution.argv[-3:] == ["/bin/sh", "-lc", "pwd"]
    assert execution.shell is False
    assert execution.metadata["backend"] == "linux-bwrap"
    assert execution.metadata["enforced"] == "true"


def test_shell_sandbox_falls_back_to_soft_backend_when_native_tool_is_missing(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(runtime_sandbox.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runtime_sandbox.shutil, "which", lambda _name: None)

    execution = runtime_sandbox.prepare_shell_sandbox(
        "printf ok",
        workspace_root=tmp_path,
        cwd=tmp_path,
        env={"PATH": "/usr/bin"},
    )

    assert execution.argv == "printf ok"
    assert execution.shell is True
    assert execution.metadata["backend"] == "soft"
    assert execution.metadata["enforced"] == "false"
    assert execution.metadata["fallback_reason"] == "native sandbox unavailable"


def test_shell_sandbox_runner_falls_back_when_native_exec_is_missing(
    monkeypatch,
    tmp_path,
):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) == 1:
            raise FileNotFoundError("missing sandbox")
        return subprocess.CompletedProcess(args[0], 0, b"ok\n", b"")

    monkeypatch.setattr(runtime_sandbox.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(runtime_sandbox.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(runtime_sandbox.subprocess, "run", fake_run)

    result = runtime_sandbox.run_shell_sandboxed(
        "printf ok",
        workspace_root=tmp_path,
        cwd=tmp_path,
        env={"PATH": "/usr/bin"},
        timeout_seconds=1,
    )

    assert result.completed.returncode == 0
    assert result.completed.stdout == b"ok\n"
    assert result.metadata["backend"] == "soft"
    assert result.metadata["enforced"] == "false"
    assert result.metadata["fallback_reason"] == "native sandbox exec failed"
    assert len(calls) == 2


def test_shell_sandbox_runner_falls_back_when_linux_namespace_start_fails(
    monkeypatch,
    tmp_path,
):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                args[0],
                1,
                b"",
                b"bwrap: Creating new namespace failed: Operation not permitted",
            )
        return subprocess.CompletedProcess(args[0], 0, b"ok\n", b"")

    monkeypatch.setattr(runtime_sandbox.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runtime_sandbox.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(runtime_sandbox.subprocess, "run", fake_run)

    result = runtime_sandbox.run_shell_sandboxed(
        "printf ok",
        workspace_root=tmp_path,
        cwd=tmp_path,
        env={"PATH": "/usr/bin"},
        timeout_seconds=1,
    )

    assert result.completed.returncode == 0
    assert result.completed.stdout == b"ok\n"
    assert result.metadata["backend"] == "soft"
    assert result.metadata["enforced"] == "false"
    assert result.metadata["fallback_reason"] == "native sandbox startup failed"
    assert len(calls) == 2


def test_shell_sandbox_runner_does_not_fallback_for_macos_policy_denial(
    monkeypatch,
    tmp_path,
):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args[0],
            1,
            b"",
            b"Operation not permitted",
        )

    monkeypatch.setattr(runtime_sandbox.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(runtime_sandbox.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(runtime_sandbox.subprocess, "run", fake_run)

    result = runtime_sandbox.run_shell_sandboxed(
        "python -c 'open(\"/tmp/out\", \"w\").write(\"x\")'",
        workspace_root=tmp_path,
        cwd=tmp_path,
        env={"PATH": "/usr/bin"},
        timeout_seconds=1,
    )

    assert result.completed.returncode == 1
    assert result.metadata["backend"] == "macos-seatbelt"
    assert result.metadata["enforced"] == "true"
    assert "fallback_reason" not in result.metadata
    assert len(calls) == 1
