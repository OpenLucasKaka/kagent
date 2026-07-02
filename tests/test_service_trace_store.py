import json
import os
import subprocess
import sys
from pathlib import Path
from stat import S_IMODE

import pytest

from self_correcting_langgraph_agent.service import trace_store as service_trace_store
from self_correcting_langgraph_agent.service.trace_store import (
    load_trace_by_run_id,
    persist_trace,
    prune_runtime_traces,
    prune_traces,
)


def test_persist_trace_writes_json_trace_inside_configured_directory(tmp_path):
    trace_dir = tmp_path / "traces"

    trace_path = Path(
        persist_trace(
            {"run_id": "run-123", "status": "done", "events": [{"node": "planner"}]},
            str(trace_dir),
        )
    )

    assert trace_path.parent == trace_dir
    assert trace_path.name == "run-123.json"
    assert json.loads(trace_path.read_text()) == {
        "run_id": "run-123",
        "status": "done",
        "events": [{"node": "planner"}],
    }


def test_persist_trace_writes_owner_only_trace_file_permissions(tmp_path):
    trace_dir = tmp_path / "traces"

    trace_path = Path(
        persist_trace(
            {"run_id": "private-run", "status": "done"},
            str(trace_dir),
        )
    )

    assert S_IMODE(trace_path.stat().st_mode) == 0o600


def test_persist_trace_uses_owner_only_trace_directory_permissions(tmp_path):
    trace_dir = tmp_path / "traces"

    persist_trace({"run_id": "private-dir", "status": "done"}, str(trace_dir))

    assert S_IMODE(trace_dir.stat().st_mode) == 0o700


def test_persist_trace_tightens_existing_trace_directory_permissions(tmp_path):
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    trace_dir.chmod(0o755)

    persist_trace({"run_id": "existing-dir", "status": "done"}, str(trace_dir))

    assert S_IMODE(trace_dir.stat().st_mode) == 0o700


def test_persist_trace_sanitizes_run_id_before_building_output_path(tmp_path):
    trace_dir = tmp_path / "traces"
    outside_path = tmp_path / "outside.json"

    trace_path = Path(
        persist_trace(
            {"run_id": "../outside", "status": "done"},
            str(trace_dir),
        )
    )

    assert trace_path.parent == trace_dir
    assert trace_path.name != "../outside.json"
    assert json.loads(trace_path.read_text())["run_id"] == "../outside"
    assert not outside_path.exists()


def test_load_trace_by_run_id_reads_sanitized_trace_file(tmp_path):
    trace_dir = tmp_path / "traces"
    persist_trace({"run_id": "../outside", "status": "requires_approval"}, str(trace_dir))

    loaded = load_trace_by_run_id("../outside", str(trace_dir))

    assert loaded == {"run_id": "../outside", "status": "requires_approval"}
    assert not (tmp_path / "outside.json").exists()


def test_load_trace_by_run_id_returns_none_for_missing_trace(tmp_path):
    assert load_trace_by_run_id("missing", str(tmp_path)) is None


def test_persist_trace_replaces_existing_trace_without_temp_artifacts(tmp_path):
    trace_dir = tmp_path / "traces"

    first_path = Path(persist_trace({"run_id": "repeat", "status": "first"}, str(trace_dir)))
    second_path = Path(persist_trace({"run_id": "repeat", "status": "second"}, str(trace_dir)))

    assert first_path == second_path
    assert json.loads(second_path.read_text())["status"] == "second"
    assert sorted(path.name for path in trace_dir.iterdir()) == ["repeat.json"]


def test_persist_trace_preserves_existing_trace_when_write_fails(tmp_path, monkeypatch):
    trace_dir = tmp_path / "traces"
    trace_path = Path(persist_trace({"run_id": "stable", "status": "old"}, str(trace_dir)))

    def failing_fsync(_fd):
        raise OSError("disk full")

    monkeypatch.setattr(service_trace_store.os, "fsync", failing_fsync)

    with pytest.raises(OSError, match="disk full"):
        persist_trace({"run_id": "stable", "status": "new"}, str(trace_dir))

    assert json.loads(trace_path.read_text())["status"] == "old"
    assert sorted(path.name for path in trace_dir.iterdir()) == ["stable.json"]


def test_prune_traces_dry_run_reports_old_trace_files_without_deleting(tmp_path):
    old_trace = tmp_path / "old.json"
    fresh_trace = tmp_path / "fresh.json"
    note = tmp_path / "note.txt"
    old_trace.write_text("{}\n", encoding="utf-8")
    fresh_trace.write_text("{}\n", encoding="utf-8")
    note.write_text("keep\n", encoding="utf-8")

    old_time = 1_000.0
    fresh_time = 9_500.0
    old_trace.touch()
    fresh_trace.touch()
    note.touch()
    os.utime(old_trace, (old_time, old_time))
    os.utime(fresh_trace, (fresh_time, fresh_time))
    os.utime(note, (old_time, old_time))

    summary = prune_traces(
        tmp_path,
        max_age_seconds=3_600,
        now=10_000.0,
        dry_run=True,
    )

    assert summary == {
        "trace_dir": str(tmp_path),
        "max_age_seconds": 3600,
        "dry_run": True,
        "scanned": 2,
        "matched": 1,
        "deleted": 0,
        "kept": 1,
        "errors": [],
    }
    assert old_trace.exists()
    assert fresh_trace.exists()
    assert note.exists()


def test_prune_traces_delete_removes_only_old_trace_json_files(tmp_path):
    old_trace = tmp_path / "old.json"
    fresh_trace = tmp_path / "fresh.json"
    old_text = tmp_path / "old.txt"
    old_trace.write_text("{}\n", encoding="utf-8")
    fresh_trace.write_text("{}\n", encoding="utf-8")
    old_text.write_text("keep\n", encoding="utf-8")

    os.utime(old_trace, (1_000.0, 1_000.0))
    os.utime(fresh_trace, (9_500.0, 9_500.0))
    os.utime(old_text, (1_000.0, 1_000.0))

    summary = prune_traces(
        tmp_path,
        max_age_seconds=3_600,
        now=10_000.0,
        dry_run=False,
    )

    assert summary["matched"] == 1
    assert summary["deleted"] == 1
    assert not old_trace.exists()
    assert fresh_trace.exists()
    assert old_text.exists()


def test_prune_runtime_traces_dry_run_matches_only_old_terminal_runtime_traces(
    tmp_path,
):
    old_done = Path(
        persist_trace(
            {"trace_type": "codex_runtime", "run_id": "old-done", "status": "done"},
            str(tmp_path),
        )
    )
    old_failed = Path(
        persist_trace(
            {"trace_type": "codex_runtime", "run_id": "old-failed", "status": "failed"},
            str(tmp_path),
        )
    )
    old_cancelled = Path(
        persist_trace(
            {
                "trace_type": "codex_runtime",
                "run_id": "old-cancelled",
                "status": "cancelled",
            },
            str(tmp_path),
        )
    )
    old_pending = Path(
        persist_trace(
            {
                "trace_type": "codex_runtime",
                "run_id": "old-pending",
                "status": "requires_approval",
            },
            str(tmp_path),
        )
    )
    old_legacy = Path(
        persist_trace(
            {"run_id": "old-legacy", "status": "done"},
            str(tmp_path),
        )
    )
    fresh_done = Path(
        persist_trace(
            {"trace_type": "codex_runtime", "run_id": "fresh-done", "status": "done"},
            str(tmp_path),
        )
    )
    for path in [old_done, old_failed, old_cancelled, old_pending, old_legacy]:
        os.utime(path, (1_000.0, 1_000.0))
    os.utime(fresh_done, (9_900.0, 9_900.0))

    summary = prune_runtime_traces(
        tmp_path,
        max_age_seconds=3_600,
        now=10_000.0,
        dry_run=True,
    )

    assert summary == {
        "trace_dir": str(tmp_path),
        "max_age_seconds": 3600,
        "dry_run": True,
        "statuses": ["cancelled", "done", "failed"],
        "scanned": 6,
        "runtime_scanned": 5,
        "matched": 3,
        "deleted": 0,
        "kept": 3,
        "protected_pending": 1,
        "skipped_non_runtime": 1,
        "skipped_fresh": 1,
        "skipped_status": 1,
        "unreadable": 0,
        "matched_by_status": {"cancelled": "1", "done": "1", "failed": "1"},
        "errors": [],
    }
    assert old_done.exists()
    assert old_failed.exists()
    assert old_cancelled.exists()
    assert old_pending.exists()
    assert old_legacy.exists()
    assert fresh_done.exists()


def test_prune_runtime_traces_delete_removes_only_old_terminal_runtime_traces(
    tmp_path,
):
    old_done = Path(
        persist_trace(
            {"trace_type": "codex_runtime", "run_id": "old-done", "status": "done"},
            str(tmp_path),
        )
    )
    old_pending = Path(
        persist_trace(
            {
                "trace_type": "codex_runtime",
                "run_id": "old-pending",
                "status": "requires_approval",
            },
            str(tmp_path),
        )
    )
    old_legacy = Path(persist_trace({"run_id": "old-legacy", "status": "done"}, str(tmp_path)))
    for path in [old_done, old_pending, old_legacy]:
        os.utime(path, (1_000.0, 1_000.0))

    summary = prune_runtime_traces(
        tmp_path,
        max_age_seconds=3_600,
        now=10_000.0,
        dry_run=False,
    )

    assert summary["matched"] == 1
    assert summary["deleted"] == 1
    assert summary["protected_pending"] == 1
    assert summary["skipped_non_runtime"] == 1
    assert not old_done.exists()
    assert old_pending.exists()
    assert old_legacy.exists()


def test_trace_store_module_prunes_traces_in_dry_run_mode(tmp_path):
    old_trace = tmp_path / "old.json"
    old_trace.write_text("{}\n", encoding="utf-8")
    os.utime(old_trace, (1_000.0, 1_000.0))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "self_correcting_langgraph_agent.service.trace_store",
            str(tmp_path),
            "--max-age-days",
            "1",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["dry_run"] is True
    assert payload["matched"] == 1
    assert payload["deleted"] == 0
    assert old_trace.exists()


def test_trace_store_module_prunes_runtime_traces_in_dry_run_mode(tmp_path):
    old_trace = Path(
        persist_trace(
            {"trace_type": "codex_runtime", "run_id": "old-done", "status": "done"},
            str(tmp_path),
        )
    )
    os.utime(old_trace, (1_000.0, 1_000.0))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "self_correcting_langgraph_agent.service.trace_store",
            str(tmp_path),
            "--max-age-days",
            "1",
            "--runtime-only",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload["dry_run"] is True
    assert payload["statuses"] == ["cancelled", "done", "failed"]
    assert payload["runtime_scanned"] == 1
    assert payload["matched"] == 1
    assert payload["deleted"] == 0
    assert old_trace.exists()
