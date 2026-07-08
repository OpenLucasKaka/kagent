from __future__ import annotations

from stat import S_IMODE

import pytest

from kagent.runtime.workspace import RuntimeWorkspace


def test_runtime_workspace_creates_standard_layout_with_owner_only_permissions(
    tmp_path,
):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")

    manifest = workspace.ensure_layout()

    assert manifest["root"] == str(tmp_path / "runtime-workspace")
    assert manifest["kinds"] == ["workspace", "reports", "logs", "policies", "memories"]
    assert S_IMODE((tmp_path / "runtime-workspace").stat().st_mode) == 0o700
    for kind in manifest["kinds"]:
        path = tmp_path / "runtime-workspace" / kind
        assert path.is_dir()
        assert S_IMODE(path.stat().st_mode) == 0o700


def test_runtime_workspace_writes_and_reads_text_assets_by_kind(tmp_path):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")

    written = workspace.write_text(
        "reports",
        "pilot/summary.md",
        "# Summary\n\nready\n",
        metadata={"run_id": "run-123"},
    )
    read = workspace.read_text("reports", "pilot/summary.md")

    assert written["kind"] == "reports"
    assert written["path"] == "pilot/summary.md"
    assert written["bytes"] == len("# Summary\n\nready\n".encode("utf-8"))
    assert written["metadata"] == {"run_id": "run-123"}
    assert len(written["sha256"]) == 64
    assert read["content"] == "# Summary\n\nready\n"
    assert read["truncated"] is False
    assert read["sha256"] == written["sha256"]
    asset_path = tmp_path / "runtime-workspace" / "reports" / "pilot" / "summary.md"
    assert S_IMODE(asset_path.stat().st_mode) == 0o600


def test_runtime_workspace_read_text_truncates_by_byte_limit(tmp_path):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")
    workspace.write_text("logs", "events.log", "abcdef")

    read = workspace.read_text("logs", "events.log", max_bytes=3)

    assert read["content"] == "abc"
    assert read["bytes"] == 3
    assert read["truncated"] is True


def test_runtime_workspace_rejects_escape_and_symlink_paths(tmp_path):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")
    workspace.ensure_layout()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    (tmp_path / "runtime-workspace" / "reports" / "outside-link").symlink_to(outside)

    with pytest.raises(ValueError, match="path must stay inside the virtual directory"):
        workspace.write_text("reports", "../escape.md", "no")

    with pytest.raises(ValueError, match="path must not traverse symlinks"):
        workspace.read_text("reports", "outside-link")


def test_runtime_workspace_lists_assets_with_metadata(tmp_path):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")
    workspace.write_text("reports", "pilot/summary.md", "summary\n")
    workspace.write_text("reports", "pilot/raw.json", "{}\n")
    workspace.write_text("memories", "session.md", "remember\n")

    listing = workspace.list("reports", max_depth=2)

    assert listing["kind"] == "reports"
    assert listing["root"] == "reports"
    assert listing["truncated"] is False
    assert listing["entries"] == [
        {
            "path": "pilot",
            "type": "directory",
            "bytes": 0,
            "sha256": "",
        },
        {
            "path": "pilot/raw.json",
            "type": "file",
            "bytes": 3,
            "sha256": workspace.read_text("reports", "pilot/raw.json")["sha256"],
        },
        {
            "path": "pilot/summary.md",
            "type": "file",
            "bytes": 8,
            "sha256": workspace.read_text("reports", "pilot/summary.md")["sha256"],
        },
    ]


def test_runtime_workspace_rejects_unknown_kind(tmp_path):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")

    with pytest.raises(ValueError, match="unknown virtual directory kind"):
        workspace.write_text("cache", "x.txt", "no")
