import json
import subprocess

from self_correcting_langgraph_agent.ops.trace_replay import summarize_runtime_trace


def _runtime_trace():
    return {
        "trace_type": "codex_runtime",
        "run_id": "run-123",
        "status": "done",
        "goal": "update plan",
        "started_at": "2026-07-02T09:00:00+00:00",
        "completed_at": "2026-07-02T09:00:02+00:00",
        "duration_seconds": "2.0000",
        "iteration_count": "1",
        "max_iterations": "3",
        "approved_action_count": "0",
        "events": [
            {"node": "planner", "status": "ok", "iteration": "1"},
            {"node": "executor", "status": "ok", "tool": "read_file"},
            {"node": "executor", "status": "ok", "tool": "apply_patch"},
        ],
        "progress_events": [
            {"type": "planner_started", "iteration": "1"},
            {"type": "planner_completed", "action_count": "2"},
            {
                "type": "tool_started",
                "tool": "read_file",
                "action_id": "step-1",
                "secret": "secret progress metadata should not replay",
            },
            {"type": "tool_completed", "tool": "read_file", "status": "ok"},
        ],
        "observations": [
            {
                "action_id": "step-1",
                "tool": "read_file",
                "status": "ok",
                "output": {
                    "path": "docs/plan.md",
                    "content": "secret body should not replay",
                    "bytes": 24,
                    "truncated": False,
                },
            },
            {
                "action_id": "step-2",
                "tool": "apply_patch",
                "status": "ok",
                "output": {
                    "changed_files": [
                        {
                            "path": "docs/plan.md",
                            "operation": "update",
                            "bytes": 22,
                            "sha256": "a" * 64,
                        }
                    ],
                    "file_count": 1,
                },
            },
        ],
        "plans": [
            {
                "actions": [
                    {
                        "id": "step-2",
                        "tool": "apply_patch",
                        "input": {"patch": "secret patch should not replay"},
                    }
                ]
            }
        ],
    }


def test_summarize_runtime_trace_builds_redacted_replay_summary():
    summary = summarize_runtime_trace(_runtime_trace(), trace_path="/tmp/run-123.json")

    assert summary == {
        "trace_path": "/tmp/run-123.json",
        "trace_type": "codex_runtime",
        "run_id": "run-123",
        "status": "done",
        "goal": "update plan",
        "started_at": "2026-07-02T09:00:00+00:00",
        "completed_at": "2026-07-02T09:00:02+00:00",
        "duration_seconds": "2.0000",
        "iterations": "1/3",
        "event_count": "3",
        "progress_event_count": "4",
        "observation_count": "2",
        "approved_action_count": "0",
        "pending_approval": {},
        "tool_counts": {"apply_patch": "1", "read_file": "1"},
        "observation_status_counts": {"ok": "2"},
        "failed_observations": [],
        "changed_files": [
            {
                "action_id": "step-2",
                "path": "docs/plan.md",
                "operation": "update",
                "bytes": "22",
            }
        ],
        "artifacts": [],
        "progress_timeline": [
            {"type": "planner_started", "iteration": "1"},
            {"type": "planner_completed", "action_count": "2"},
            {
                "type": "tool_started",
                "action_id": "step-1",
                "tool": "read_file",
            },
            {"type": "tool_completed", "status": "ok", "tool": "read_file"},
        ],
        "timeline": [
            {
                "action_id": "step-1",
                "tool": "read_file",
                "status": "ok",
                "error_code": "",
                "duration_seconds": "",
            },
            {
                "action_id": "step-2",
                "tool": "apply_patch",
                "status": "ok",
                "error_code": "",
                "duration_seconds": "",
            },
        ],
    }
    assert "secret" not in json.dumps(summary)


def test_trace_replay_module_prints_json_summary(tmp_path):
    trace_path = tmp_path / "run-123.json"
    trace_path.write_text(json.dumps(_runtime_trace()), encoding="utf-8")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.trace_replay",
            str(trace_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert completed.stderr == ""
    assert payload["trace_path"] == str(trace_path)
    assert payload["tool_counts"] == {"apply_patch": "1", "read_file": "1"}
    assert payload["progress_event_count"] == "4"
    assert "secret" not in completed.stdout
