#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-$(pwd)/.venv/bin/python}"
export PYTHON_BIN

"$PYTHON_BIN" - <<'PY'
import json
import os
import subprocess
import tempfile
from pathlib import Path

python_bin = os.environ.get("PYTHON_BIN")
if not python_bin:
    raise SystemExit("PYTHON_BIN is required")

workspace = Path(tempfile.mkdtemp(prefix="self-correcting-apply-patch-smoke."))
target = workspace / "docs" / "agent-created.md"
expected = "# Agent 文件创建测试\n\n这是 runtime 通过 apply_patch 创建的文件。\n"
patch = (
    "*** Begin Patch\n"
    "*** Add File: docs/agent-created.md\n"
    "+# Agent 文件创建测试\n"
    "+\n"
    "+这是 runtime 通过 apply_patch 创建的文件。\n"
    "*** End Patch\n"
)
plan = {
    "actions": [
        {
            "id": "step-1",
            "tool": "apply_patch",
            "input": {"patch": patch},
            "reason": "create a workspace file through a Codex-style patch",
        }
    ],
    "final_answer": "文件已创建",
}

completed = subprocess.run(
    [
        python_bin,
        "-m",
        "self_correcting_langgraph_agent.cli",
        "创建一个测试 markdown 文件",
        "--runtime",
        "--max-iterations",
        "1",
        "--runtime-plan",
        json.dumps(plan, ensure_ascii=False, sort_keys=True),
    ],
    cwd=workspace,
    check=True,
    capture_output=True,
    text=True,
)
payload = json.loads(completed.stdout)

if payload.get("status") != "done":
    raise SystemExit(f"runtime status was not done: {completed.stdout}")
if payload.get("answer") != "文件已创建":
    raise SystemExit(f"unexpected final answer: {payload.get('answer')}")
if not target.exists():
    raise SystemExit(f"expected file was not created: {target}")
content = target.read_text(encoding="utf-8")
if content != expected:
    raise SystemExit(f"unexpected file content: {content!r}")

observations = payload.get("observations", [])
if len(observations) != 1:
    raise SystemExit(f"expected one observation: {observations!r}")
output = observations[0].get("output", {})
changed_files = output.get("changed_files", [])
if output.get("file_count") != 1 or not changed_files:
    raise SystemExit(f"unexpected apply_patch output: {output!r}")
changed_file = changed_files[0]
if changed_file.get("path") != "docs/agent-created.md":
    raise SystemExit(f"unexpected changed path: {changed_file!r}")
if changed_file.get("bytes") != len(expected.encode("utf-8")):
    raise SystemExit(f"unexpected byte count: {changed_file!r}")
if len(str(changed_file.get("sha256", ""))) != 64:
    raise SystemExit(f"missing sha256: {changed_file!r}")

print("apply_patch runtime smoke passed")
print(f"workspace: {workspace}")
print(f"created_file: {target}")
print(f"sha256: {changed_file['sha256']}")
PY
