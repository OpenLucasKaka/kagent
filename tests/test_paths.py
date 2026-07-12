import os
import stat
from pathlib import Path

import pytest

from kagent.utils import paths
from kagent.utils.paths import (
    kagent_cache_dir,
    kagent_config_dir,
    kagent_home,
    kagent_state_dir,
    migrate_legacy_kagent_state,
)


def test_default_kagent_home_uses_hidden_home_directory(tmp_path):
    env = {"HOME": str(tmp_path)}

    assert kagent_home(env) == tmp_path / ".kagent"
    assert kagent_config_dir(env) == tmp_path / ".kagent" / "config"
    assert kagent_state_dir(env) == tmp_path / ".kagent" / "state"
    assert kagent_cache_dir(env) == tmp_path / ".kagent" / "cache"


def test_explicit_kagent_home_wins_and_expands_user(tmp_path):
    env = {"HOME": str(tmp_path), "KAGENT_HOME": "~/custom-home"}

    assert kagent_home(env) == tmp_path / "custom-home"


def test_kagent_home_returns_an_absolute_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert kagent_home({"HOME": "relative-home"}) == tmp_path / "relative-home" / ".kagent"


def test_kagent_home_rejects_a_relative_override(tmp_path):
    with pytest.raises(ValueError, match="absolute"):
        kagent_home({"HOME": str(tmp_path / "user-home"), "KAGENT_HOME": "relative-kagent"})


@pytest.mark.parametrize("value", ["", "   "])
def test_kagent_home_rejects_an_empty_override(tmp_path, value):
    with pytest.raises(ValueError, match="KAGENT_HOME"):
        kagent_home({"HOME": str(tmp_path), "KAGENT_HOME": value})


@pytest.mark.parametrize("env", [{}, {"HOME": "   "}])
def test_kagent_home_falls_back_to_system_home_when_home_is_unavailable(tmp_path, monkeypatch, env):
    system_home = tmp_path / "system-home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: system_home))

    assert kagent_home(env) == system_home / ".kagent"


def test_tilde_kagent_home_falls_back_to_system_home(tmp_path, monkeypatch):
    system_home = tmp_path / "system-home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: system_home))

    assert kagent_home({"KAGENT_HOME": "~"}) == system_home


def _legacy_env(tmp_path):
    return {
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "legacy-config"),
        "XDG_STATE_HOME": str(tmp_path / "legacy-state"),
    }


def _write(path, content):
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o644)


def test_migration_copies_all_durable_legacy_artifacts_with_owner_only_modes(tmp_path):
    env = _legacy_env(tmp_path)
    legacy_config = Path(env["XDG_CONFIG_HOME"]) / "kagent"
    legacy_state = Path(env["XDG_STATE_HOME"]) / "kagent"
    _write(legacy_config / "provider.json", "provider")
    _write(legacy_state / "session-memory.json", "memory")
    _write(legacy_state / "history", "history")
    _write(legacy_state / "pending-approvals" / "nested" / "approval.json", "approval")
    _write(legacy_state / "patches" / "patch.json", "patch")

    marker = migrate_legacy_kagent_state(env)
    root = Path(env["HOME"]) / ".kagent"

    assert marker == root / ".migration-v1-complete"
    assert (root / "config" / "provider.json").read_text(encoding="utf-8") == "provider"
    assert (root / "state" / "session-memory.json").read_text(encoding="utf-8") == "memory"
    assert (root / "state" / "history").read_text(encoding="utf-8") == "history"
    assert (root / "state" / "pending-approvals" / "nested" / "approval.json").read_text(
        encoding="utf-8"
    ) == "approval"
    assert (root / "state" / "patches" / "patch.json").read_text(encoding="utf-8") == "patch"
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o700
        for path in [
            root,
            root / "config",
            root / "state",
            root / "state" / "pending-approvals",
            root / "state" / "pending-approvals" / "nested",
            root / "state" / "patches",
        ]
    )
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in [
            root / "config" / "provider.json",
            root / "state" / "session-memory.json",
            root / "state" / "history",
            root / "state" / "pending-approvals" / "nested" / "approval.json",
            root / "state" / "patches" / "patch.json",
            marker,
        ]
    )
    assert (legacy_config / "provider.json").read_text(encoding="utf-8") == "provider"


def test_migration_uses_default_xdg_legacy_locations(tmp_path):
    home = tmp_path / "home"
    _write(home / ".config" / "kagent" / "provider.json", "provider")
    _write(home / ".local" / "state" / "kagent" / "history", "history")

    migrate_legacy_kagent_state({"HOME": str(home)})

    assert (home / ".kagent" / "config" / "provider.json").read_text() == "provider"
    assert (home / ".kagent" / "state" / "history").read_text() == "history"


@pytest.mark.parametrize(
    ("legacy_root", "artifact", "destination_parts"),
    [
        ("XDG_CONFIG_HOME", "provider.json", ("config", "provider.json")),
        ("XDG_STATE_HOME", "session-memory.json", ("state", "session-memory.json")),
        ("XDG_STATE_HOME", "history", ("state", "history")),
    ],
)
def test_migration_preserves_existing_destination_content_and_tightens_permissions(
    tmp_path, legacy_root, artifact, destination_parts
):
    env = _legacy_env(tmp_path)
    source = Path(env[legacy_root]) / "kagent" / artifact
    destination = Path(env["HOME"]) / ".kagent" / Path(*destination_parts)
    _write(source, "legacy")
    _write(destination, "current")

    migrate_legacy_kagent_state(env)

    assert destination.read_text(encoding="utf-8") == "current"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


@pytest.mark.parametrize("artifact", ["pending-approvals", "patches"])
def test_directory_migration_skips_a_source_subtree_blocked_by_a_destination_file(
    tmp_path, artifact
):
    env = _legacy_env(tmp_path)
    legacy_state = Path(env["XDG_STATE_HOME"]) / "kagent"
    destination = Path(env["HOME"]) / ".kagent" / "state" / artifact
    _write(legacy_state / artifact / "nested" / "child.json", "legacy-child")
    _write(legacy_state / artifact / "sibling.json", "legacy-sibling")
    _write(legacy_state / "history", "legacy-history")
    _write(destination / "nested", "current-file")

    marker = migrate_legacy_kagent_state(env)

    assert (destination / "nested").read_text(encoding="utf-8") == "current-file"
    assert (destination / "sibling.json").read_text(encoding="utf-8") == "legacy-sibling"
    assert (Path(env["HOME"]) / ".kagent" / "state" / "history").read_text() == "legacy-history"
    assert marker.exists()


def test_migration_is_idempotent_after_completion(tmp_path):
    env = _legacy_env(tmp_path)
    source = Path(env["XDG_STATE_HOME"]) / "kagent" / "history"
    _write(source, "first")

    first_marker = migrate_legacy_kagent_state(env)
    source.write_text("second", encoding="utf-8")
    second_marker = migrate_legacy_kagent_state(env)

    assert first_marker == second_marker
    assert (Path(env["HOME"]) / ".kagent" / "state" / "history").read_text() == "first"


@pytest.mark.parametrize("marker_kind", ["directory", "fifo"])
def test_migration_rejects_a_non_regular_completion_marker(tmp_path, marker_kind):
    if marker_kind == "fifo" and not hasattr(os, "mkfifo"):
        pytest.skip("requires FIFO support")
    env = _legacy_env(tmp_path)
    marker = Path(env["HOME"]) / ".kagent" / ".migration-v1-complete"
    marker.parent.mkdir(parents=True)
    if marker_kind == "directory":
        marker.mkdir()
    else:
        os.mkfifo(marker)

    with pytest.raises(ValueError, match="regular file"):
        migrate_legacy_kagent_state(env)


def test_explicit_kagent_home_skips_legacy_discovery_and_marker(tmp_path):
    env = _legacy_env(tmp_path)
    env["KAGENT_HOME"] = str(tmp_path / "custom")
    _write(Path(env["XDG_CONFIG_HOME"]) / "kagent" / "provider.json", "provider")

    marker = migrate_legacy_kagent_state(env)

    assert marker == tmp_path / "custom" / ".migration-v1-complete"
    assert not marker.exists()
    assert not (tmp_path / "custom" / "config" / "provider.json").exists()


@pytest.mark.parametrize("unsafe_location", ["source", "destination", "destination-parent"])
def test_migration_rejects_symlink_sources_destinations_and_parent_chains(
    tmp_path, unsafe_location
):
    env = _legacy_env(tmp_path)
    source = Path(env["XDG_CONFIG_HOME"]) / "kagent" / "provider.json"
    destination = Path(env["HOME"]) / ".kagent" / "config" / "provider.json"
    outside_file = tmp_path / "outside.json"
    _write(outside_file, "outside")

    if unsafe_location == "source":
        source.parent.mkdir(parents=True)
        source.symlink_to(outside_file)
    elif unsafe_location == "destination":
        destination.parent.mkdir(parents=True)
        destination.symlink_to(outside_file)
        _write(source, "provider")
    else:
        real_config = tmp_path / "real-config"
        real_config.mkdir()
        destination.parent.parent.mkdir(parents=True)
        destination.parent.symlink_to(real_config, target_is_directory=True)
        _write(source, "provider")

    with pytest.raises(ValueError, match="symlink"):
        migrate_legacy_kagent_state(env)

    assert outside_file.read_text(encoding="utf-8") == "outside"
    assert not (Path(env["HOME"]) / ".kagent" / ".migration-v1-complete").exists()


def test_failed_directory_migration_writes_no_marker_and_can_retry(tmp_path):
    env = _legacy_env(tmp_path)
    pending = Path(env["XDG_STATE_HOME"]) / "kagent" / "pending-approvals"
    _write(pending / "valid.json", "valid")
    outside = tmp_path / "outside.json"
    _write(outside, "outside")
    unsafe = pending / "unsafe.json"
    unsafe.symlink_to(outside)

    with pytest.raises(ValueError, match="regular files|symlink"):
        migrate_legacy_kagent_state(env)

    marker = Path(env["HOME"]) / ".kagent" / ".migration-v1-complete"
    assert not marker.exists()

    unsafe.unlink()
    _write(unsafe, "safe")
    assert migrate_legacy_kagent_state(env) == marker
    assert marker.exists()
    assert (Path(env["HOME"]) / ".kagent" / "state" / "pending-approvals" / "valid.json").exists()


def test_destination_parent_replacement_is_not_followed_during_atomic_copy(tmp_path, monkeypatch):
    env = _legacy_env(tmp_path)
    source = Path(env["XDG_CONFIG_HOME"]) / "kagent" / "provider.json"
    destination_parent = Path(env["HOME"]) / ".kagent" / "config"
    displaced_parent = tmp_path / "displaced-config"
    outside_parent = tmp_path / "outside-config"
    outside_parent.mkdir()
    _write(source, "provider")
    real_link = paths.os.link
    replaced = False

    def replace_parent_before_link(*args, **kwargs):
        nonlocal replaced
        if not replaced:
            destination_parent.rename(displaced_parent)
            destination_parent.symlink_to(outside_parent, target_is_directory=True)
            replaced = True
        return real_link(*args, **kwargs)

    monkeypatch.setattr(paths.os, "link", replace_parent_before_link)

    with pytest.raises(ValueError, match="changed|symlink"):
        migrate_legacy_kagent_state(env)

    assert replaced
    assert not (outside_parent / "provider.json").exists()
    assert not (Path(env["HOME"]) / ".kagent" / ".migration-v1-complete").exists()


def test_destination_parent_replacement_is_detected_before_destination_wins(tmp_path, monkeypatch):
    env = _legacy_env(tmp_path)
    source = Path(env["XDG_CONFIG_HOME"]) / "kagent" / "provider.json"
    destination = Path(env["HOME"]) / ".kagent" / "config" / "provider.json"
    displaced_parent = tmp_path / "displaced-config"
    outside_parent = tmp_path / "outside-config"
    outside_parent.mkdir()
    _write(source, "legacy")
    _write(destination, "current")
    real_destination_entry_exists = paths._destination_entry_exists
    replaced = False

    def replace_parent_after_check(parent_fd, name, path):
        nonlocal replaced
        exists = real_destination_entry_exists(parent_fd, name, path)
        if not replaced:
            destination.parent.rename(displaced_parent)
            destination.parent.symlink_to(outside_parent, target_is_directory=True)
            replaced = True
        return exists

    monkeypatch.setattr(paths, "_destination_entry_exists", replace_parent_after_check)

    with pytest.raises(ValueError, match="changed|symlink"):
        migrate_legacy_kagent_state(env)

    assert replaced
    assert not (Path(env["HOME"]) / ".kagent" / ".migration-v1-complete").exists()


@pytest.mark.parametrize(
    ("operation", "failed_fdopen_call"),
    [("copy-source", 1), ("copy-destination", 2), ("marker", 1)],
)
def test_fdopen_failures_close_all_owned_file_descriptors(
    tmp_path, monkeypatch, operation, failed_fdopen_call
):
    env = _legacy_env(tmp_path)
    if operation != "marker":
        _write(Path(env["XDG_CONFIG_HOME"]) / "kagent" / "provider.json", "provider")

    opened_fds = []
    real_open_source_file = paths._open_source_file
    real_open_temporary_file = paths._open_temporary_file
    real_fdopen = paths.os.fdopen
    fdopen_calls = 0

    def capture_source_fd(path):
        source_fd = real_open_source_file(path)
        opened_fds.append(source_fd)
        return source_fd

    def capture_temporary_fd(parent_fd, destination_name):
        temporary_fd, temporary_name = real_open_temporary_file(parent_fd, destination_name)
        opened_fds.append(temporary_fd)
        return temporary_fd, temporary_name

    def fail_selected_fdopen(fd, *args, **kwargs):
        nonlocal fdopen_calls
        fdopen_calls += 1
        if fdopen_calls == failed_fdopen_call:
            raise OSError("injected fdopen failure")
        return real_fdopen(fd, *args, **kwargs)

    monkeypatch.setattr(paths, "_open_source_file", capture_source_fd)
    monkeypatch.setattr(paths, "_open_temporary_file", capture_temporary_fd)
    monkeypatch.setattr(paths.os, "fdopen", fail_selected_fdopen)

    with pytest.raises(OSError, match="injected fdopen failure"):
        migrate_legacy_kagent_state(env)

    assert opened_fds
    for opened_fd in opened_fds:
        with pytest.raises(OSError):
            os.fstat(opened_fd)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires FIFO support")
def test_directory_migration_rejects_non_regular_entries(tmp_path):
    env = _legacy_env(tmp_path)
    pending = Path(env["XDG_STATE_HOME"]) / "kagent" / "pending-approvals"
    pending.mkdir(parents=True)
    os.mkfifo(pending / "pipe")

    with pytest.raises(ValueError, match="regular files"):
        migrate_legacy_kagent_state(env)

    assert not (Path(env["HOME"]) / ".kagent" / ".migration-v1-complete").exists()
