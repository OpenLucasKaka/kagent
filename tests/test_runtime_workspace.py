from __future__ import annotations

import threading
from stat import S_IMODE

import pytest

from kagent.runtime import workspace as workspace_module
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


def test_runtime_workspace_restores_revision_and_preserves_redo_revision(tmp_path):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")
    first = workspace.write_text("reports", "pilot/summary.md", "v1\n")
    second = workspace.write_text("reports", "pilot/summary.md", "v2\n")
    first_revision_id = workspace.history("reports", "pilot/summary.md")["revisions"][0][
        "revision_id"
    ]

    restored = workspace.restore(
        "reports",
        "pilot/summary.md",
        revision_id=first_revision_id,
        expected_current_sha256=second["sha256"].upper(),
        expected_revision_sha256=first["sha256"].upper(),
    )

    assert restored == {
        "kind": "reports",
        "path": "pilot/summary.md",
        "restored_revision_id": first_revision_id,
        "previous_sha256": second["sha256"],
        "sha256": first["sha256"],
        "bytes": 3,
        "updated_at": workspace.read_text("reports", "pilot/summary.md")["updated_at"],
    }
    assert workspace.read_text("reports", "pilot/summary.md")["content"] == "v1\n"
    redo_revision = next(
        revision
        for revision in workspace.history("reports", "pilot/summary.md")["revisions"]
        if revision["sha256"] == second["sha256"]
    )

    redone = workspace.restore(
        "reports",
        "pilot/summary.md",
        revision_id=redo_revision["revision_id"],
        expected_current_sha256=first["sha256"],
        expected_revision_sha256=redo_revision["sha256"],
    )

    assert redone["sha256"] == second["sha256"]
    assert workspace.read_text("reports", "pilot/summary.md")["content"] == "v2\n"
    asset_path = tmp_path / "runtime-workspace" / "reports" / "pilot" / "summary.md"
    assert S_IMODE(asset_path.stat().st_mode) == 0o600


@pytest.mark.parametrize("expected_sha256", ["abc", "g" * 64, "a" * 65])
def test_runtime_workspace_restore_rejects_invalid_expected_sha256(
    tmp_path, expected_sha256
):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")
    workspace.write_text("reports", "summary.md", "v1\n")
    workspace.write_text("reports", "summary.md", "v2\n")
    revision_id = workspace.history("reports", "summary.md")["revisions"][0]["revision_id"]

    with pytest.raises(ValueError, match="64 hexadecimal characters"):
        workspace.restore(
            "reports",
            "summary.md",
            revision_id=revision_id,
            expected_current_sha256=expected_sha256,
            expected_revision_sha256=workspace.history("reports", "summary.md")[
                "revisions"
            ][0]["sha256"],
        )


@pytest.mark.parametrize("expected_sha256", ["abc", "g" * 64, "a" * 65])
def test_runtime_workspace_restore_rejects_invalid_expected_revision_sha256(
    tmp_path, expected_sha256
):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")
    first = workspace.write_text("reports", "summary.md", "v1\n")
    current = workspace.write_text("reports", "summary.md", "v2\n")
    revision_id = workspace.history("reports", "summary.md")["revisions"][0][
        "revision_id"
    ]

    with pytest.raises(ValueError, match="expected_revision_sha256"):
        workspace.restore(
            "reports",
            "summary.md",
            revision_id=revision_id,
            expected_current_sha256=current["sha256"],
            expected_revision_sha256=expected_sha256,
        )

    assert workspace.read_text("reports", "summary.md")["sha256"] == current["sha256"]
    assert first["sha256"] != current["sha256"]


def test_runtime_workspace_restore_rejects_sha_conflict_without_writing(tmp_path):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")
    workspace.write_text("reports", "summary.md", "v1\n")
    current = workspace.write_text("reports", "summary.md", "v2\n")
    history_before = workspace.history("reports", "summary.md")

    with pytest.raises(ValueError, match="current SHA-256 does not match"):
        workspace.restore(
            "reports",
            "summary.md",
            revision_id=history_before["revisions"][0]["revision_id"],
            expected_current_sha256="0" * 64,
            expected_revision_sha256=history_before["revisions"][0]["sha256"],
        )

    assert workspace.read_text("reports", "summary.md")["sha256"] == current["sha256"]
    assert workspace.history("reports", "summary.md") == history_before


def test_runtime_workspace_restore_rejects_tampered_revision_without_writing(tmp_path):
    root = tmp_path / "runtime-workspace"
    workspace = RuntimeWorkspace(root)
    first = workspace.write_text("reports", "summary.md", "v1\n")
    current = workspace.write_text("reports", "summary.md", "v2\n")
    history_before = workspace.history("reports", "summary.md")
    revision = history_before["revisions"][0]
    revision_path = (
        root
        / ".versions"
        / "reports"
        / "summary.md"
        / f"{revision['revision_id']}.txt"
    )
    revision_path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="revision SHA-256 does not match"):
        workspace.restore(
            "reports",
            "summary.md",
            revision_id=revision["revision_id"],
            expected_current_sha256=current["sha256"],
            expected_revision_sha256=first["sha256"],
        )

    assert workspace.read_text("reports", "summary.md")["content"] == "v2\n"


def test_runtime_workspace_restore_rejects_noop_without_writing(tmp_path):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")
    first = workspace.write_text("reports", "summary.md", "same\n")
    workspace.write_text("reports", "summary.md", "same\n")
    history_before = workspace.history("reports", "summary.md")

    with pytest.raises(ValueError, match="revision matches current content"):
        workspace.restore(
            "reports",
            "summary.md",
            revision_id=history_before["revisions"][0]["revision_id"],
            expected_current_sha256=first["sha256"],
            expected_revision_sha256=history_before["revisions"][0]["sha256"],
        )

    assert workspace.history("reports", "summary.md") == history_before


@pytest.mark.parametrize("revision_id", ["", "missing-revision"])
def test_runtime_workspace_restore_requires_existing_revision(tmp_path, revision_id):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")
    first = workspace.write_text("reports", "summary.md", "v1\n")
    current = workspace.write_text("reports", "summary.md", "v2\n")

    with pytest.raises(ValueError, match="revision does not exist"):
        workspace.restore(
            "reports",
            "summary.md",
            revision_id=revision_id,
            expected_current_sha256=current["sha256"],
            expected_revision_sha256=first["sha256"],
        )

    assert workspace.read_text("reports", "summary.md")["content"] == "v2\n"
    assert workspace.history("reports", "summary.md")["revisions"][0]["sha256"] == first[
        "sha256"
    ]


def test_runtime_workspace_restore_rejects_escape_and_symlink_paths(tmp_path):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")
    workspace.write_text("reports", "summary.md", "v1\n")
    current = workspace.write_text("reports", "summary.md", "v2\n")
    revision_id = workspace.history("reports", "summary.md")["revisions"][0]["revision_id"]
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    (tmp_path / "runtime-workspace" / "reports" / "outside-link").symlink_to(outside)

    with pytest.raises(ValueError, match="path must stay inside the virtual directory"):
        workspace.restore(
            "reports",
            "../summary.md",
            revision_id=revision_id,
            expected_current_sha256=current["sha256"],
            expected_revision_sha256=workspace.history("reports", "summary.md")[
                "revisions"
            ][0]["sha256"],
        )

    with pytest.raises(ValueError, match="path must not traverse symlinks"):
        workspace.restore(
            "reports",
            "outside-link",
            revision_id=revision_id,
            expected_current_sha256=current["sha256"],
            expected_revision_sha256=workspace.history("reports", "summary.md")[
                "revisions"
            ][0]["sha256"],
        )

    assert outside.read_text(encoding="utf-8") == "outside\n"


def test_runtime_workspace_rejects_symlinked_versions_directory(tmp_path):
    root = tmp_path / "runtime-workspace"
    workspace = RuntimeWorkspace(root)
    workspace.ensure_layout()
    version_kind = root / ".versions" / "reports"
    version_kind.rmdir()
    outside = tmp_path / "outside-versions"
    outside.mkdir()
    version_kind.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="versions path must not contain symlinks"):
        workspace.write_text("reports", "summary.md", "content\n")

    assert list(outside.iterdir()) == []


def test_runtime_workspace_restore_serializes_against_concurrent_write(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "runtime-workspace"
    workspace = RuntimeWorkspace(root)
    workspace.write_text("reports", "summary.md", "v1\n")
    current = workspace.write_text("reports", "summary.md", "v2\n")
    revision_id = workspace.history("reports", "summary.md")["revisions"][0][
        "revision_id"
    ]
    entered_restore_write = threading.Event()
    release_restore_write = threading.Event()
    concurrent_write_finished = threading.Event()
    original_write = workspace_module._write_owner_only_text_file

    def blocking_write(target, content):
        if content == "v1\n" and threading.current_thread().name == "restore-thread":
            entered_restore_write.set()
            assert release_restore_write.wait(timeout=2)
        original_write(target, content)

    monkeypatch.setattr(workspace_module, "_write_owner_only_text_file", blocking_write)

    restore_thread = threading.Thread(
        name="restore-thread",
        target=lambda: workspace.restore(
            "reports",
            "summary.md",
            revision_id=revision_id,
            expected_current_sha256=current["sha256"],
            expected_revision_sha256=workspace.history("reports", "summary.md")[
                "revisions"
            ][0]["sha256"],
        ),
    )
    restore_thread.start()
    assert entered_restore_write.wait(timeout=1)

    def concurrent_write():
        RuntimeWorkspace(root).write_text("reports", "summary.md", "v3\n")
        concurrent_write_finished.set()

    writer_thread = threading.Thread(target=concurrent_write)
    writer_thread.start()
    assert concurrent_write_finished.wait(timeout=0.1) is False
    release_restore_write.set()
    restore_thread.join(timeout=2)
    writer_thread.join(timeout=2)

    assert restore_thread.is_alive() is False
    assert writer_thread.is_alive() is False
    assert concurrent_write_finished.is_set()
    assert workspace.read_text("reports", "summary.md")["content"] == "v3\n"


def test_runtime_workspace_rejects_unknown_kind(tmp_path):
    workspace = RuntimeWorkspace(tmp_path / "runtime-workspace")

    with pytest.raises(ValueError, match="unknown virtual directory kind"):
        workspace.write_text("cache", "x.txt", "no")
