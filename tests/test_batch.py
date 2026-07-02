import json
import subprocess

from self_correcting_langgraph_agent.ops.batch import run_batch_file


def test_run_batch_file_writes_one_summary_record_per_input_line(tmp_path):
    input_path = tmp_path / "goals.jsonl"
    output_path = tmp_path / "results.jsonl"
    input_path.write_text(
        json.dumps({"id": "sum", "goal": "calculate 2 + 3"}) + "\n"
        + json.dumps({"id": "upper", "goal": "uppercase text in 'agent loop'"}) + "\n"
    )

    report = run_batch_file(input_path, output_path)
    records = [
        json.loads(line)
        for line in output_path.read_text().splitlines()
        if line.strip()
    ]

    assert report == {"processed": "2", "succeeded": "2", "failed": "0"}
    assert records[0]["id"] == "sum"
    assert records[0]["line_number"] == "1"
    assert records[0]["summary"]["status"] == "done"
    assert records[0]["summary"]["answer"] == "5"
    assert records[1]["id"] == "upper"
    assert records[1]["summary"]["answer"] == "AGENT LOOP"


def test_run_batch_file_reports_invalid_json_line_without_stopping(tmp_path):
    input_path = tmp_path / "goals.jsonl"
    output_path = tmp_path / "results.jsonl"
    input_path.write_text(
        "{not-json}\n"
        + json.dumps({"id": "sum", "goal": "calculate 2 + 3"}) + "\n"
    )

    report = run_batch_file(input_path, output_path)
    records = [
        json.loads(line)
        for line in output_path.read_text().splitlines()
        if line.strip()
    ]

    assert report == {"processed": "2", "succeeded": "1", "failed": "1"}
    assert records[0]["status"] == "failed"
    assert records[0]["error"].startswith("invalid JSON")
    assert records[1]["summary"]["status"] == "done"


def test_run_batch_file_can_write_full_traces(tmp_path):
    input_path = tmp_path / "goals.jsonl"
    output_path = tmp_path / "results.jsonl"
    input_path.write_text(json.dumps({"id": "sum", "goal": "calculate 2 + 3"}) + "\n")

    run_batch_file(input_path, output_path, full_trace=True)
    record = json.loads(output_path.read_text())

    assert record["status"] == "done"
    assert record["trace"]["answer"] == "5"
    assert record["trace"]["events"][0]["node"] == "planner"
    assert "summary" not in record


def test_run_batch_file_applies_per_record_agent_config(tmp_path):
    input_path = tmp_path / "goals.jsonl"
    output_path = tmp_path / "results.jsonl"
    input_path.write_text(
        json.dumps(
            {
                "id": "budgeted",
                "goal": "calculate 1 + 1 then calculate 2 + 2",
                "max_steps": 1,
            }
        )
        + "\n"
    )

    report = run_batch_file(input_path, output_path)
    record = json.loads(output_path.read_text())

    assert report == {"processed": "1", "succeeded": "0", "failed": "1"}
    assert record["summary"]["status"] == "failed"
    assert record["summary"]["errors"] == ["planned steps exceed max_steps"]


def test_run_batch_file_rejects_non_integer_per_record_config(tmp_path):
    input_path = tmp_path / "goals.jsonl"
    output_path = tmp_path / "results.jsonl"
    input_path.write_text(
        json.dumps({"id": "bad-float", "goal": "calculate 2 + 3", "max_steps": 2.5})
        + "\n"
        + json.dumps({"id": "bad-bool", "goal": "calculate 2 + 3", "max_retries": True})
        + "\n"
        + json.dumps({"id": "sum", "goal": "calculate 2 + 3"})
        + "\n"
    )

    report = run_batch_file(input_path, output_path)
    records = [json.loads(line) for line in output_path.read_text().splitlines()]

    assert report == {"processed": "3", "succeeded": "1", "failed": "2"}
    assert records[0] == {
        "id": "bad-float",
        "line_number": "1",
        "status": "failed",
        "error": "max_steps must be an integer",
    }
    assert records[1] == {
        "id": "bad-bool",
        "line_number": "2",
        "status": "failed",
        "error": "max_retries must be an integer",
    }
    assert records[2]["summary"]["answer"] == "5"


def test_batch_module_cli_writes_report_and_results(tmp_path):
    input_path = tmp_path / "goals.jsonl"
    output_path = tmp_path / "results.jsonl"
    input_path.write_text(json.dumps({"id": "sum", "goal": "calculate 2 + 3"}) + "\n")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.batch",
            str(input_path),
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stderr == ""
    assert json.loads(completed.stdout) == {
        "processed": "1",
        "succeeded": "1",
        "failed": "0",
    }
    assert json.loads(output_path.read_text())["summary"]["answer"] == "5"


def test_batch_module_cli_can_exit_nonzero_when_batch_has_failures(tmp_path):
    input_path = tmp_path / "goals.jsonl"
    output_path = tmp_path / "results.jsonl"
    input_path.write_text("{not-json}\n")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.batch",
            str(input_path),
            str(output_path),
            "--fail-on-failure",
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["failed"] == "1"
    assert json.loads(output_path.read_text())["status"] == "failed"


def test_batch_module_cli_can_write_full_traces(tmp_path):
    input_path = tmp_path / "goals.jsonl"
    output_path = tmp_path / "results.jsonl"
    input_path.write_text(json.dumps({"id": "sum", "goal": "calculate 2 + 3"}) + "\n")

    subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.batch",
            str(input_path),
            str(output_path),
            "--full-trace",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    record = json.loads(output_path.read_text())
    assert record["trace"]["status"] == "done"
    assert "summary" not in record
