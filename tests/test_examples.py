import subprocess
import sys
import threading
from pathlib import Path

from self_correcting_langgraph_agent.service import ServiceConfig, create_server


def test_internal_runtime_client_example_is_linked_and_executable():
    readme = Path("README.md").read_text()
    rollout = Path("docs/internal-rollout.md").read_text()
    example_path = Path("examples/internal_runtime_client.py")

    assert "examples/internal_runtime_client.py" in readme
    assert "examples/internal_runtime_client.py" in rollout
    assert example_path.exists()

    example = example_path.read_text()
    assert "Authorization" in example
    assert "Bearer" in example
    assert "Idempotency-Key" in example
    assert "/runtime/run" in example
    assert "/runtime/resume" in example
    assert "/runtime/approvals" in example
    assert "/runtime/approvals/summary" in example
    assert "/runtime/policy" in example
    assert "/runtime/runs" in example
    assert "/runtime/runs/summary" in example
    assert "approved_action_ids" in example
    assert "auth_subject" in example
    assert "resumed_by_auth_subject" in example
    assert "SELF_CORRECTING_CLIENT_BASE_URL" in example
    assert "SELF_CORRECTING_CLIENT_TOKEN" in example
    assert "sk-" not in example

    completed = subprocess.run(
        [".venv/bin/python", str(example_path), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--base-url" in completed.stdout
    assert "--token" in completed.stdout
    assert "run" in completed.stdout
    assert "resume" in completed.stdout
    assert "approvals" in completed.stdout
    assert "approval-summary" in completed.stdout
    assert "policy" in completed.stdout
    assert "list-runs" in completed.stdout
    assert "summary" in completed.stdout

    policy_help = subprocess.run(
        [".venv/bin/python", str(example_path), "policy", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--tool" in policy_help.stdout
    assert "--approval-required" in policy_help.stdout


def test_internal_runtime_client_example_can_call_local_service(tmp_path):
    sys.path.insert(0, str(Path("examples").resolve()))
    try:
        from internal_runtime_client import RuntimeClient
    finally:
        sys.path.pop(0)

    server = create_server(
        "127.0.0.1",
        0,
        config=ServiceConfig(
            trace_dir=str(tmp_path),
            auth_tokens={"team-a": "team-a-token"},
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    try:
        client = RuntimeClient(
            base_url=f"http://{host}:{port}",
            token="team-a-token",
        )
        run = client.run(
            goal="client example",
            max_iterations=1,
            idempotency_key="client-example-1",
            plan={
                "actions": [
                    {
                        "id": "note-1",
                        "tool": "note",
                        "input": {"text": "client example"},
                        "reason": "verify client example",
                    }
                ],
                "final_answer": "client-done",
            },
        )
        approvals = client.approvals(auth_subject="team-a")
        approval_summary = client.approval_summary(auth_subject="team-a")
        policy = client.policy()
        approval_policy = client.policy(
            tool="http_request",
            approval_required="true",
        )
        runs = client.list_runs(auth_subject="team-a", status="done", limit=5)
        summary = client.summary(auth_subject="team-a", status="done")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert run["status"] == "done"
    assert run["answer"] == "client-done"
    assert run["auth_subject"] == "team-a"
    assert approvals["count"] == "0"
    assert approval_summary["pending_approval_count"] == "0"
    assert policy["auth_subject"] == "team-a"
    assert policy["effective_policy_source"] == "default"
    assert "note" in policy["effective_allowed_tools"]
    assert approval_policy["effective_tool_policy"] == [
        {
            "name": "http_request",
            "allowed": "false",
            "approval_required": "true",
        }
    ]
    assert approval_policy["effective_tool_policy_filter"] == {
        "tool": "http_request",
        "approval_required": "true",
    }
    assert runs["runs"][0]["run_id"] == run["run_id"]
    assert summary["run_count"] == "1"
    assert summary["auth_subject_counts"] == {"team-a": "1"}
