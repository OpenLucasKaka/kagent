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


def test_runtime_workspace_searches_text_assets_with_bounded_results(tmp_path):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")
    workspace.write_text("reports", "pilot/summary.md", "上线风险：低\n下一步：灰度\n")
    workspace.write_text("reports", "pilot/raw.md", "原始反馈：体验风险需要跟进\n")
    workspace.write_text("logs", "events.log", "风险 should stay in logs\n")

    search = workspace.search("reports", "风险", max_depth=2, limit=2)

    assert search["kind"] == "reports"
    assert search["root"] == "reports"
    assert search["query"] == "风险"
    assert search["match_count"] == 2
    assert search["truncated"] is False
    assert search["matches"] == [
        {
            "path": "pilot/raw.md",
            "line_number": 1,
            "line": "原始反馈：体验风险需要跟进",
            "byte_offset": len("原始反馈：体验".encode("utf-8")),
            "sha256": workspace.read_text("reports", "pilot/raw.md")["sha256"],
        },
        {
            "path": "pilot/summary.md",
            "line_number": 1,
            "line": "上线风险：低",
            "byte_offset": len("上线".encode("utf-8")),
            "sha256": workspace.read_text("reports", "pilot/summary.md")["sha256"],
        },
    ]


def test_runtime_workspace_preserves_previous_versions_on_overwrite(tmp_path):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")
    first = workspace.write_text("reports", "pilot/summary.md", "v1\n")
    second = workspace.write_text("reports", "pilot/summary.md", "v2\n")

    history = workspace.history("reports", "pilot/summary.md")

    assert second["sha256"] != first["sha256"]
    assert history["kind"] == "reports"
    assert history["path"] == "pilot/summary.md"
    assert history["revision_count"] == 1
    assert history["revisions"][0]["sha256"] == first["sha256"]
    assert history["revisions"][0]["bytes"] == 3
    assert history["revisions"][0]["content"] == "v1\n"
    assert history["revisions"][0]["revision_id"]
    assert history["truncated"] is False


def test_runtime_workspace_diffs_latest_revision_against_current_file(tmp_path):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")
    first = workspace.write_text("reports", "pilot/summary.md", "v1\nstable\n")
    second = workspace.write_text("reports", "pilot/summary.md", "v2\nstable\n")

    diff = workspace.diff("reports", "pilot/summary.md", context_lines=1)

    assert diff["kind"] == "reports"
    assert diff["path"] == "pilot/summary.md"
    assert diff["from_sha256"] == first["sha256"]
    assert diff["to_sha256"] == second["sha256"]
    assert diff["revision_id"]
    assert "--- reports/pilot/summary.md@" in diff["diff"]
    assert "+++ reports/pilot/summary.md" in diff["diff"]
    assert "-v1" in diff["diff"]
    assert "+v2" in diff["diff"]
    assert diff["truncated"] is False


def test_runtime_workspace_rejects_unknown_kind(tmp_path):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")

    with pytest.raises(ValueError, match="unknown virtual directory kind"):
        workspace.write_text("cache", "x.txt", "no")
