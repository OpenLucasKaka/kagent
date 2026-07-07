#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

export KAGENT_LLM_CONFIG_PATH=/tmp/kagent-run-checks-provider-config.json

cleanup_local_build_artifacts() {
    rm -rf build dist *.egg-info src/*.egg-info
    rm -f "$KAGENT_LLM_CONFIG_PATH"
}
trap cleanup_local_build_artifacts EXIT

PYTHONWARNINGS=ignore .venv/bin/python -m pip install --no-build-isolation -e '.[dev]' >/tmp/kagent-install.log
PYTHONWARNINGS=ignore .venv/bin/python -m pytest
PYTHONWARNINGS=ignore .venv/bin/python -m ruff check src tests
if command -v npm >/dev/null 2>&1; then
    npm run check >/tmp/kagent-npm-check.log
fi
rm -rf /tmp/kagent-pycache
PYTHONPYCACHEPREFIX=/tmp/kagent-pycache PYTHONWARNINGS=ignore .venv/bin/python -m compileall -q src tests
PYTHONWARNINGS=ignore .venv/bin/kagent --version >/tmp/kagent-entrypoint-version.json
printf '{"id":"sum","goal":"calculate 2 + 3"}\n' >/tmp/kagent-batch-input.jsonl
PYTHONWARNINGS=ignore .venv/bin/kagent-batch /tmp/kagent-batch-input.jsonl /tmp/kagent-batch-output.jsonl --fail-on-failure >/tmp/kagent-batch-report.json
PYTHONWARNINGS=ignore .venv/bin/python -m kagent.cli --version >/tmp/kagent-version.json
KAGENT_SERVICE_IDEMPOTENCY_CACHE_SIZE=17 \
PYTHONWARNINGS=ignore \
    .venv/bin/kagent-doctor \
    --trace-dir /tmp/kagent-doctor-traces \
    >/tmp/kagent-doctor.json
grep '"idempotency_cache_size": "17"' /tmp/kagent-doctor.json >/dev/null
grep '"runtime_policy"' /tmp/kagent-doctor.json >/dev/null
grep '"effective_tool_policy_sha256"' /tmp/kagent-doctor.json >/dev/null
if PYTHONWARNINGS=ignore .venv/bin/kagent-doctor --require-auth >/tmp/kagent-doctor-require-auth.json; then
    echo "doctor --require-auth unexpectedly passed without auth token" >&2
    exit 1
fi
if KAGENT_SERVICE_AUTH_TOKEN=release-gate-token-é \
PYTHONWARNINGS=ignore \
    .venv/bin/kagent-doctor --require-auth \
    >/tmp/kagent-doctor-require-auth-unsafe-token.json; then
    echo "doctor --require-auth unexpectedly passed with unsafe auth token" >&2
    exit 1
fi
grep "auth_token_unsafe" \
    /tmp/kagent-doctor-require-auth-unsafe-token.json >/dev/null
if KAGENT_SERVICE_AUTH_TOKEN=replace-with-a-long-random-token \
PYTHONWARNINGS=ignore \
    .venv/bin/kagent-doctor --require-auth \
    >/tmp/kagent-doctor-require-auth-placeholder-token.json; then
    echo "doctor --require-auth unexpectedly passed with placeholder auth token" >&2
    exit 1
fi
grep "auth_token_placeholder" \
    /tmp/kagent-doctor-require-auth-placeholder-token.json >/dev/null
KAGENT_SERVICE_AUTH_TOKEN=release-gate-token \
KAGENT_SERVICE_RATE_LIMIT_PER_MINUTE=60 \
KAGENT_SERVICE_MAX_CONCURRENT_RUNS=4 \
KAGENT_SERVICE_PROTECT_DIAGNOSTICS=true \
PYTHONWARNINGS=ignore \
    .venv/bin/kagent-doctor --production \
    --trace-dir /tmp/kagent-doctor-production-traces \
    >/tmp/kagent-doctor-production.json
if KAGENT_SERVICE_AUTH_TOKEN=replace-with-a-long-random-token \
KAGENT_SERVICE_RATE_LIMIT_PER_MINUTE=60 \
KAGENT_SERVICE_MAX_CONCURRENT_RUNS=4 \
KAGENT_SERVICE_PROTECT_DIAGNOSTICS=true \
PYTHONWARNINGS=ignore \
    .venv/bin/kagent-doctor --production \
    --trace-dir /tmp/kagent-doctor-placeholder-token-production-traces \
    >/tmp/kagent-doctor-placeholder-token-production.json; then
    echo "doctor --production unexpectedly passed with placeholder auth token" >&2
    exit 1
fi
if KAGENT_SERVICE_AUTH_TOKEN=release-gate-token-é \
KAGENT_SERVICE_RATE_LIMIT_PER_MINUTE=60 \
KAGENT_SERVICE_MAX_CONCURRENT_RUNS=4 \
KAGENT_SERVICE_PROTECT_DIAGNOSTICS=true \
PYTHONWARNINGS=ignore \
    .venv/bin/kagent-doctor --production \
    --trace-dir /tmp/kagent-doctor-unsafe-token-production-traces \
    >/tmp/kagent-doctor-unsafe-token-production.json; then
    echo "doctor --production unexpectedly passed with unsafe auth token" >&2
    exit 1
fi
grep "auth_token_unsafe" \
    /tmp/kagent-doctor-unsafe-token-production.json >/dev/null
if KAGENT_SERVICE_AUTH_TOKEN=release-gate-token \
KAGENT_SERVICE_RATE_LIMIT_PER_MINUTE=60 \
KAGENT_SERVICE_MAX_CONCURRENT_RUNS=4 \
KAGENT_SERVICE_PROTECT_DIAGNOSTICS=true \
KAGENT_SERVICE_ALLOW_FULL_TRACE_RESPONSE=true \
PYTHONWARNINGS=ignore \
    .venv/bin/kagent-doctor --production \
    --trace-dir /tmp/kagent-doctor-full-trace-production-traces \
    >/tmp/kagent-doctor-full-trace-production.json; then
    echo "doctor --production unexpectedly passed with full trace responses enabled" >&2
    exit 1
fi
KAGENT_SERVICE_AUTH_TOKEN=release-gate-token \
KAGENT_SERVICE_RATE_LIMIT_PER_MINUTE=60 \
KAGENT_SERVICE_MAX_CONCURRENT_RUNS=4 \
KAGENT_SERVICE_PROTECT_DIAGNOSTICS=true \
KAGENT_SERVICE_RUNTIME_MAX_ITERATIONS=2 \
KAGENT_LLM_BASE_URL=configured-provider-base \
KAGENT_LLM_API_KEY=x \
KAGENT_LLM_MODEL=agent-runtime-model \
PYTHONWARNINGS=ignore \
    .venv/bin/kagent-doctor --production \
    --require-runtime-provider \
    --trace-dir /tmp/kagent-doctor-runtime-provider-traces \
    >/tmp/kagent-doctor-runtime-provider.json
if KAGENT_SERVICE_AUTH_TOKEN=release-gate-token \
KAGENT_SERVICE_RATE_LIMIT_PER_MINUTE=60 \
KAGENT_SERVICE_MAX_CONCURRENT_RUNS=4 \
KAGENT_SERVICE_PROTECT_DIAGNOSTICS=true \
KAGENT_SERVICE_RUNTIME_MAX_ITERATIONS=1 \
PYTHONWARNINGS=ignore \
    .venv/bin/kagent-doctor --production \
    --require-runtime-provider \
    --trace-dir /tmp/kagent-doctor-runtime-provider-missing-traces \
    >/tmp/kagent-doctor-runtime-provider-missing.json; then
    echo "doctor --require-runtime-provider unexpectedly passed without provider config" >&2
    exit 1
fi
grep "llm_base_url_required" \
    /tmp/kagent-doctor-runtime-provider-missing.json >/dev/null
grep "llm_model_required" \
    /tmp/kagent-doctor-runtime-provider-missing.json >/dev/null
grep "llm_api_key_required" \
    /tmp/kagent-doctor-runtime-provider-missing.json >/dev/null
grep "runtime_iterations_too_low" \
    /tmp/kagent-doctor-runtime-provider-missing.json >/dev/null
if KAGENT_SERVICE_PORT=not-a-port \
PYTHONWARNINGS=ignore \
    .venv/bin/kagent-doctor --production \
    >/tmp/kagent-doctor-invalid-env.stdout \
    2>/tmp/kagent-doctor-invalid-env.stderr; then
    echo "doctor --production unexpectedly passed with invalid env config" >&2
    exit 1
fi
grep "KAGENT_SERVICE_PORT must be an integer" \
    /tmp/kagent-doctor-invalid-env.stderr >/dev/null
if grep "Traceback" /tmp/kagent-doctor-invalid-env.stderr >/dev/null; then
    echo "doctor unexpectedly emitted traceback for invalid env config" >&2
    exit 1
fi
PYTHONWARNINGS=ignore .venv/bin/kagent-serve --help >/tmp/kagent-serve-help.txt
if KAGENT_SERVICE_PORT=not-a-port \
PYTHONWARNINGS=ignore \
    .venv/bin/kagent-serve --help \
    >/tmp/kagent-serve-invalid-env.stdout \
    2>/tmp/kagent-serve-invalid-env.stderr; then
    echo "serve --help unexpectedly passed with invalid env config" >&2
    exit 1
fi
grep "KAGENT_SERVICE_PORT must be an integer" \
    /tmp/kagent-serve-invalid-env.stderr >/dev/null
if grep "Traceback" /tmp/kagent-serve-invalid-env.stderr >/dev/null; then
    echo "serve unexpectedly emitted traceback for invalid env config" >&2
    exit 1
fi
PYTHONWARNINGS=ignore sh scripts/smoke_service.sh
PYTHONWARNINGS=ignore sh scripts/smoke_internal_runtime.sh >/tmp/kagent-internal-runtime-smoke.json
PYTHONWARNINGS=ignore .venv/bin/python -m kagent.cli --deterministic "calculate 2 + 3 then count words in 'ship small reliable agents'" >/tmp/kagent-smoke.json
PYTHONWARNINGS=ignore .venv/bin/python -m kagent.cli "calculate 2 + 3 then subtract 10 - 4" --plan >/tmp/kagent-plan.json
PYTHONWARNINGS=ignore .venv/bin/python -m kagent.cli --deterministic "uppercase text in 'agent loop'" --inject-fault "uppercase text in 'agent loop'=empty-answer" --summary --output /tmp/kagent-summary-output.json >/tmp/kagent-summary.json
rm -rf /tmp/kagent-session-memory-dir
mkdir -p /tmp/kagent-session-memory-dir
chmod 0755 /tmp/kagent-session-memory-dir
printf '我是卡卡\nexit\n' | PYTHONWARNINGS=ignore .venv/bin/python -m kagent.cli \
    --runtime \
    --interactive \
    --max-iterations 1 \
    --runtime-plan '{"actions":[],"final_answer":"你好，卡卡。"}' \
    --session-memory /tmp/kagent-session-memory-dir/session-memory.json \
    >/tmp/kagent-session-memory-smoke.json
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import json
import stat
from pathlib import Path

output = json.load(open("/tmp/kagent-session-memory-smoke.json", encoding="utf-8"))
memory_dir = Path("/tmp/kagent-session-memory-dir")
memory_path = memory_dir / "session-memory.json"
memory = json.loads(memory_path.read_text(encoding="utf-8"))
dir_mode = stat.S_IMODE(memory_dir.stat().st_mode)
mode = stat.S_IMODE(memory_path.stat().st_mode)
if output["status"] != "done" or output["answer"] != "你好，卡卡。":
    raise SystemExit(f"unexpected session memory smoke output: {output}")
if memory["schema_version"] != "2":
    raise SystemExit(f"unexpected session memory schema: {memory}")
for key in ("summary", "facts", "open_items", "compacted_turn_count"):
    if key not in memory:
        raise SystemExit(f"session memory missing compact field {key}: {memory}")
if memory["turns"] != [{"user": "我是卡卡", "assistant": "你好，卡卡。"}]:
    raise SystemExit(f"unexpected session memory turns: {memory}")
if dir_mode != 0o700:
    raise SystemExit(f"unexpected session memory directory mode: {oct(dir_mode)}")
if mode != 0o600:
    raise SystemExit(f"unexpected session memory file mode: {oct(mode)}")
PY
chmod 0644 /tmp/kagent-session-memory-dir/session-memory.json
chmod 0755 /tmp/kagent-session-memory-dir
if printf '我是谁\nexit\n' | PYTHONWARNINGS=ignore .venv/bin/python -m kagent.cli \
    --runtime \
    --interactive \
    --max-iterations 1 \
    --runtime-plan '{"actions":[],"final_answer":"你是卡卡。"}' \
    --session-memory /tmp/kagent-session-memory-dir/session-memory.json \
    >/tmp/kagent-session-memory-unsafe.stdout \
    2>/tmp/kagent-session-memory-unsafe.stderr; then
    echo "interactive runtime unexpectedly loaded unsafe session memory" >&2
    exit 1
fi
grep "session memory file must be owner-only" \
    /tmp/kagent-session-memory-unsafe.stderr >/dev/null
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import stat
from pathlib import Path

memory_dir = Path("/tmp/kagent-session-memory-dir")
dir_mode = stat.S_IMODE(memory_dir.stat().st_mode)
if dir_mode != 0o700:
    raise SystemExit(
        f"session memory load did not tighten directory mode: {oct(dir_mode)}"
    )
PY
if grep "Traceback" /tmp/kagent-session-memory-unsafe.stderr >/dev/null; then
    echo "unsafe session memory unexpectedly emitted traceback" >&2
    exit 1
fi
chmod 0600 /tmp/kagent-session-memory-dir/session-memory.json
rm -f /tmp/kagent-session-memory-link.json /tmp/kagent-session-memory-target.json
printf '{"schema_version":"1","turns":[{"user":"我是卡卡","assistant":"你好，卡卡。"}]}\n' \
    >/tmp/kagent-session-memory-target.json
chmod 0600 /tmp/kagent-session-memory-target.json
ln -s /tmp/kagent-session-memory-target.json /tmp/kagent-session-memory-link.json
if printf '我是谁\nexit\n' | PYTHONWARNINGS=ignore .venv/bin/python -m kagent.cli \
    --runtime \
    --interactive \
    --max-iterations 1 \
    --runtime-plan '{"actions":[],"final_answer":"你是卡卡。"}' \
    --session-memory /tmp/kagent-session-memory-link.json \
    >/tmp/kagent-session-memory-symlink.stdout \
    2>/tmp/kagent-session-memory-symlink.stderr; then
    echo "interactive runtime unexpectedly loaded symlink session memory" >&2
    exit 1
fi
grep "session memory file must not be a symlink" \
    /tmp/kagent-session-memory-symlink.stderr >/dev/null
if grep "Traceback" /tmp/kagent-session-memory-symlink.stderr >/dev/null; then
    echo "symlink session memory unexpectedly emitted traceback" >&2
    exit 1
fi
if printf '/clear\nexit\n' | PYTHONWARNINGS=ignore .venv/bin/python -m kagent.cli \
    --runtime \
    --interactive \
    --max-iterations 1 \
    --runtime-plan '{"actions":[],"final_answer":"unused"}' \
    --session-memory /tmp/kagent-session-memory-link.json \
    >/tmp/kagent-session-memory-symlink-save.stdout \
    2>/tmp/kagent-session-memory-symlink-save.stderr; then
    echo "interactive runtime unexpectedly saved through symlink session memory" >&2
    exit 1
fi
grep "session memory file must not be a symlink" \
    /tmp/kagent-session-memory-symlink-save.stderr >/dev/null
if grep "Traceback" /tmp/kagent-session-memory-symlink-save.stderr >/dev/null; then
    echo "symlink session memory save unexpectedly emitted traceback" >&2
    exit 1
fi
rm -rf /tmp/kagent-session-memory-parent-target /tmp/kagent-session-memory-parent-link
mkdir -p /tmp/kagent-session-memory-parent-target/nested
chmod 0700 /tmp/kagent-session-memory-parent-target
chmod 0700 /tmp/kagent-session-memory-parent-target/nested
ln -s /tmp/kagent-session-memory-parent-target /tmp/kagent-session-memory-parent-link
if printf '我是卡卡\nexit\n' | PYTHONWARNINGS=ignore .venv/bin/python -m kagent.cli \
    --runtime \
    --interactive \
    --max-iterations 1 \
    --runtime-plan '{"actions":[],"final_answer":"你好，卡卡。"}' \
    --session-memory /tmp/kagent-session-memory-parent-link/nested/session-memory.json \
    >/tmp/kagent-session-memory-parent-symlink.stdout \
    2>/tmp/kagent-session-memory-parent-symlink.stderr; then
    echo "interactive runtime unexpectedly used symlink session memory parent" >&2
    exit 1
fi
grep "session memory path must not contain symlinks" \
    /tmp/kagent-session-memory-parent-symlink.stderr >/dev/null
if grep "Traceback" /tmp/kagent-session-memory-parent-symlink.stderr >/dev/null; then
    echo "symlink session memory parent unexpectedly emitted traceback" >&2
    exit 1
fi
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import io
import sys

from kagent.cli import _run_runtime_interactive

api_key = "sk-" + "runtime" + "-memory" + "-secret"
bearer = "runtime" + "-memory" + "-bearer" + "-token"
calls = []


class FakeTTYInput:
    def __init__(self):
        self.lines = [
            f"记住 {api_key} 和 https://user:pass@example.com/v1\n",
            "复述上一轮\n",
            "exit\n",
        ]

    def isatty(self):
        return True

    def readline(self):
        return self.lines.pop(0) if self.lines else ""


def fake_run_runtime_agent(goal, **_kwargs):
    calls.append(goal)
    return {"status": "done", "answer": f"Authorization: Bearer {bearer}"}


original_stdin = sys.stdin
original_stdout = sys.stdout
original_stderr = sys.__stderr__
try:
    sys.stdin = FakeTTYInput()
    sys.stdout = io.StringIO()
    sys.__stderr__ = io.StringIO()
    _run_runtime_interactive(
        provider=object(),
        run_runtime_agent=fake_run_runtime_agent,
        max_iterations=1,
        fail_on_agent_failure=False,
    )
finally:
    sys.stdin = original_stdin
    sys.stdout = original_stdout
    sys.__stderr__ = original_stderr

memory_prompt = calls[1]
if api_key in memory_prompt:
    raise SystemExit("interactive memory leaked API key")
if bearer in memory_prompt:
    raise SystemExit("interactive memory leaked bearer token")
if "user:pass@example.com" in memory_prompt:
    raise SystemExit("interactive memory leaked URL credentials")
for marker in (
    "[REDACTED_API_KEY]",
    "Bearer [REDACTED_TOKEN]",
    "https://[REDACTED_CREDENTIALS]@example.com/v1",
):
    if marker not in memory_prompt:
        raise SystemExit(f"interactive memory missing redaction marker: {marker}")
PY
PYTHONWARNINGS=ignore .venv/bin/python -m kagent.eval.evaluator --fail-on-failure >/tmp/kagent-eval.json
PYTHONWARNINGS=ignore .venv/bin/kagent-eval --list-cases >/tmp/kagent-entrypoint-eval-cases.json
PYTHONWARNINGS=ignore .venv/bin/python -m kagent.eval.evaluator --list-cases >/tmp/kagent-eval-cases.json
PYTHONWARNINGS=ignore .venv/bin/python -m kagent.eval.evaluator --category recovery >/tmp/kagent-eval-recovery.json
PYTHONWARNINGS=ignore .venv/bin/python -m kagent.eval.evaluator --case subtraction_tool_success >/tmp/kagent-eval-subtraction.json
printf '{"iteration":1,"duration_seconds":"1","status":"passed","checks_exit_code":0,"evaluator_passed":14,"evaluator_failed":0,"evaluator_slowest_case":"multi_step_success","evaluator_recovered_cases":"4","evaluator_recovery_rate":"0.29","evaluator_category_counts":{"failure":"3","recovery":"4","tool":"6","workflow":"1"}}\n' >/tmp/kagent-metrics.jsonl
PYTHONWARNINGS=ignore .venv/bin/python -m kagent.ops.metrics /tmp/kagent-metrics.jsonl --output /tmp/kagent-metrics-summary-output.json >/tmp/kagent-metrics-summary.json
PYTHONWARNINGS=ignore .venv/bin/kagent-metrics /tmp/kagent-metrics.jsonl --require-recent-health healthy >/tmp/kagent-entrypoint-metrics-summary.json
rm -rf /tmp/kagent-trace-prune-smoke
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import os
from pathlib import Path

trace_dir = Path("/tmp/kagent-trace-prune-smoke")
trace_dir.mkdir(parents=True)
old_trace = trace_dir / "old.json"
fresh_trace = trace_dir / "fresh.json"
note = trace_dir / "old.txt"
old_trace.write_text("{}\n", encoding="utf-8")
fresh_trace.write_text("{}\n", encoding="utf-8")
note.write_text("keep\n", encoding="utf-8")
os.utime(old_trace, (1_000.0, 1_000.0))
os.utime(fresh_trace, (4_102_444_800.0, 4_102_444_800.0))
os.utime(note, (1_000.0, 1_000.0))
PY
PYTHONWARNINGS=ignore .venv/bin/kagent-trace-prune \
    /tmp/kagent-trace-prune-smoke \
    --max-age-days 1 \
    >/tmp/kagent-trace-prune-dry-run.json
PYTHONWARNINGS=ignore .venv/bin/kagent-trace-prune \
    /tmp/kagent-trace-prune-smoke \
    --max-age-days 1 \
    --delete \
    >/tmp/kagent-trace-prune-delete.json
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

trace_dir = Path("/tmp/kagent-trace-prune-smoke")
dry_run = json.load(open("/tmp/kagent-trace-prune-dry-run.json", encoding="utf-8"))
deleted = json.load(open("/tmp/kagent-trace-prune-delete.json", encoding="utf-8"))
if dry_run["dry_run"] is not True or dry_run["deleted"] != 0 or dry_run["matched"] != 1:
    raise SystemExit(f"unexpected trace prune dry-run summary: {dry_run}")
if deleted["dry_run"] is not False or deleted["deleted"] != 1:
    raise SystemExit(f"unexpected trace prune delete summary: {deleted}")
if (trace_dir / "old.json").exists():
    raise SystemExit("old trace was not pruned")
if not (trace_dir / "fresh.json").exists():
    raise SystemExit("fresh trace was pruned")
if not (trace_dir / "old.txt").exists():
    raise SystemExit("non-json trace sidecar was pruned")
if str(deleted["deleted"]) != "1":
    raise SystemExit("deleted count mismatch")
runtime_done = trace_dir / "runtime-done.json"
runtime_pending = trace_dir / "runtime-pending.json"
runtime_legacy = trace_dir / "runtime-legacy.json"
runtime_done.write_text(
    '{"trace_type":"codex_runtime","run_id":"runtime-done","status":"done"}\n',
    encoding="utf-8",
)
runtime_pending.write_text(
    '{"trace_type":"codex_runtime","run_id":"runtime-pending","status":"requires_approval"}\n',
    encoding="utf-8",
)
runtime_legacy.write_text(
    '{"run_id":"runtime-legacy","status":"done"}\n',
    encoding="utf-8",
)
for path in [runtime_done, runtime_pending, runtime_legacy]:
    os.utime(path, (1_000.0, 1_000.0))
PY
PYTHONWARNINGS=ignore .venv/bin/kagent-trace-prune \
    /tmp/kagent-trace-prune-smoke \
    --max-age-days 1 \
    --runtime-only \
    >/tmp/kagent-runtime-trace-prune-dry-run.json
PYTHONWARNINGS=ignore .venv/bin/kagent-trace-prune \
    /tmp/kagent-trace-prune-smoke \
    --max-age-days 1 \
    --runtime-only \
    --delete \
    >/tmp/kagent-runtime-trace-prune-delete.json
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import json
from pathlib import Path

trace_dir = Path("/tmp/kagent-trace-prune-smoke")
runtime_dry_run = json.load(open("/tmp/kagent-runtime-trace-prune-dry-run.json", encoding="utf-8"))
runtime_deleted = json.load(open("/tmp/kagent-runtime-trace-prune-delete.json", encoding="utf-8"))
if runtime_dry_run["dry_run"] is not True or runtime_dry_run["matched"] != 1:
    raise SystemExit(f"unexpected runtime trace prune dry-run summary: {runtime_dry_run}")
if runtime_dry_run["protected_pending"] != 1:
    raise SystemExit(f"pending runtime trace was not protected: {runtime_dry_run}")
if runtime_deleted["dry_run"] is not False or runtime_deleted["deleted"] != 1:
    raise SystemExit(f"unexpected runtime trace prune delete summary: {runtime_deleted}")
if runtime_deleted["matched_by_status"] != {"done": "1"}:
    raise SystemExit(f"unexpected runtime status match counts: {runtime_deleted}")
if (trace_dir / "runtime-done.json").exists():
    raise SystemExit("old terminal runtime trace was not pruned")
if not (trace_dir / "runtime-pending.json").exists():
    raise SystemExit("pending runtime trace was pruned")
if not (trace_dir / "runtime-legacy.json").exists():
    raise SystemExit("non-runtime trace was pruned by runtime-only mode")
PY
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import json
from pathlib import Path

trace_path = Path("/tmp/kagent-trace-replay.json")
trace_path.write_text(
    json.dumps(
        {
            "trace_type": "codex_runtime",
            "run_id": "runtime-replay",
            "status": "done",
            "goal": "update plan",
            "duration_seconds": "1.5000",
            "iteration_count": "1",
            "max_iterations": "3",
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
                        "bytes": 29,
                        "truncated": False,
                        "sha256": "a" * 64,
                    },
                },
                {
                    "action_id": "step-2",
                    "tool": "apply_patch",
                    "status": "ok",
                    "output": {
                        "changed_files": [
                            {
                                "path": "docs/final-plan.md",
                                "previous_path": "docs/plan.md",
                                "operation": "move",
                                "bytes": 22,
                                "sha256": "b" * 64,
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
    )
    + "\n",
    encoding="utf-8",
)
PY
PYTHONWARNINGS=ignore .venv/bin/kagent-trace-replay \
    /tmp/kagent-trace-replay.json \
    >/tmp/kagent-trace-replay-summary.json
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import json

summary_text = open(
    "/tmp/kagent-trace-replay-summary.json", encoding="utf-8"
).read()
summary = json.loads(summary_text)
if summary["tool_counts"] != {"apply_patch": "1", "read_file": "1"}:
    raise SystemExit(f"unexpected trace replay tool counts: {summary}")
if summary["changed_files"][0]["operation"] != "move":
    raise SystemExit(f"unexpected trace replay changed files: {summary}")
if summary["changed_files"][0]["previous_path"] != "docs/plan.md":
    raise SystemExit(f"unexpected trace replay changed files: {summary}")
if len(str(summary["changed_files"][0]["sha256"])) != 64:
    raise SystemExit(f"unexpected trace replay changed file digest: {summary}")
if summary["progress_event_count"] != "4":
    raise SystemExit(f"unexpected trace replay progress count: {summary}")
if "secret body should not replay" in summary_text:
    raise SystemExit("trace replay leaked read_file content")
if "secret patch should not replay" in summary_text:
    raise SystemExit("trace replay leaked action input patch")
if "secret progress metadata should not replay" in summary_text:
    raise SystemExit("trace replay leaked progress metadata")
PY
rm -rf /tmp/kagent-wheelhouse
PYTHONWARNINGS=ignore .venv/bin/python -m pip wheel --no-deps --no-build-isolation . -w /tmp/kagent-wheelhouse >/tmp/kagent-wheel-build.log
ls /tmp/kagent-wheelhouse/kagent-0.1.0-*.whl >/dev/null
PYTHONWARNINGS=ignore .venv/bin/kagent-release-manifest \
    /tmp/kagent-wheelhouse/kagent-0.1.0-*.whl \
    --output /tmp/kagent-release-manifest.json \
    >/tmp/kagent-release-manifest.stdout.json
PYTHONWARNINGS=ignore .venv/bin/kagent-release-manifest \
    --verify /tmp/kagent-release-manifest.json \
    >/tmp/kagent-release-manifest-verify.json
PYTHONWARNINGS=ignore .venv/bin/python scripts/production_readiness_audit.py \
    >/tmp/kagent-production-readiness-audit.json
PYTHONWARNINGS=ignore .venv/bin/python -m kagent.ops.release_evidence \
    --run-checks-exit-code 0 \
    --readiness-audit /tmp/kagent-production-readiness-audit.json \
    --release-manifest /tmp/kagent-release-manifest.json \
    --output /tmp/kagent-release-evidence.json \
    >/tmp/kagent-release-evidence.stdout.json
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import json

manifest = json.load(open("/tmp/kagent-release-manifest.json", encoding="utf-8"))
evidence = json.load(open("/tmp/kagent-release-evidence.json", encoding="utf-8"))
if manifest["package"] != "kagent":
    raise SystemExit("release manifest package mismatch")
if manifest["version"] != "0.1.0":
    raise SystemExit("release manifest version mismatch")
if manifest["artifact_count"] != "1":
    raise SystemExit("release manifest artifact count mismatch")
artifact = manifest["artifacts"][0]
if len(artifact["sha256"]) != 64:
    raise SystemExit("release manifest sha256 length mismatch")
if int(artifact["size_bytes"]) <= 0:
    raise SystemExit("release manifest artifact size mismatch")
if evidence["status"] != "ready":
    raise SystemExit("release evidence bundle not ready")
if evidence["run_checks"]["status"] != "passed":
    raise SystemExit("release evidence run_checks mismatch")
if evidence["readiness_audit"]["status"] != "passed":
    raise SystemExit("release evidence readiness mismatch")
if evidence["release_manifest"]["status"] != "verified":
    raise SystemExit("release evidence manifest mismatch")
PY
printf '{not-json' >/tmp/kagent-release-manifest-invalid.json
if PYTHONWARNINGS=ignore .venv/bin/kagent-release-manifest \
    --verify /tmp/kagent-release-manifest-invalid.json \
    >/tmp/kagent-release-manifest-invalid.stdout \
    2>/tmp/kagent-release-manifest-invalid.stderr; then
    echo "release manifest unexpectedly passed with invalid JSON" >&2
    exit 1
fi
grep "invalid release manifest JSON" \
    /tmp/kagent-release-manifest-invalid.stderr >/dev/null
if grep "Traceback" /tmp/kagent-release-manifest-invalid.stderr >/dev/null; then
    echo "release manifest unexpectedly emitted traceback for invalid JSON" >&2
    exit 1
fi
printf '{"package":"kagent","version":"0.1.0","artifact_count":"1","artifacts":[{"sha256":"abc","size_bytes":"123"}]}\n' >/tmp/kagent-release-manifest-missing-path.json
if PYTHONWARNINGS=ignore .venv/bin/kagent-release-manifest \
    --verify /tmp/kagent-release-manifest-missing-path.json \
    >/tmp/kagent-release-manifest-missing-path.stdout \
    2>/tmp/kagent-release-manifest-missing-path.stderr; then
    echo "release manifest unexpectedly passed with a missing artifact path" >&2
    exit 1
fi
grep "artifact path missing" \
    /tmp/kagent-release-manifest-missing-path.stdout >/dev/null
if grep "Traceback" /tmp/kagent-release-manifest-missing-path.stderr >/dev/null; then
    echo "release manifest unexpectedly emitted traceback for missing artifact path" >&2
    exit 1
fi
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import json

manifest = {
    "package": "kagent",
    "version": "0.1.0",
    "artifact_count": "1",
    "artifacts": [
        {
            "path": "bad\x00path",
            "sha256": "abc",
            "size_bytes": "123",
        }
    ],
}
with open("/tmp/kagent-release-manifest-invalid-path.json", "w", encoding="utf-8") as handle:
    json.dump(manifest, handle)
    handle.write("\n")
PY
if PYTHONWARNINGS=ignore .venv/bin/kagent-release-manifest \
    --verify /tmp/kagent-release-manifest-invalid-path.json \
    >/tmp/kagent-release-manifest-invalid-path.stdout \
    2>/tmp/kagent-release-manifest-invalid-path.stderr; then
    echo "release manifest unexpectedly passed with an invalid artifact path" >&2
    exit 1
fi
grep "artifact path invalid" \
    /tmp/kagent-release-manifest-invalid-path.stdout >/dev/null
if grep "Traceback" /tmp/kagent-release-manifest-invalid-path.stderr >/dev/null; then
    echo "release manifest unexpectedly emitted traceback for invalid artifact path" >&2
    exit 1
fi
rm -rf /tmp/kagent-release-manifest-artifact-dir
mkdir -p /tmp/kagent-release-manifest-artifact-dir
printf '{"package":"kagent","version":"0.1.0","artifact_count":"1","artifacts":[{"path":"/tmp/kagent-release-manifest-artifact-dir","sha256":"abc","size_bytes":"123"}]}\n' >/tmp/kagent-release-manifest-directory-path.json
if PYTHONWARNINGS=ignore .venv/bin/kagent-release-manifest \
    --verify /tmp/kagent-release-manifest-directory-path.json \
    >/tmp/kagent-release-manifest-directory-path.stdout \
    2>/tmp/kagent-release-manifest-directory-path.stderr; then
    echo "release manifest unexpectedly passed with a directory artifact path" >&2
    exit 1
fi
grep "artifact is not a file" \
    /tmp/kagent-release-manifest-directory-path.stdout >/dev/null
if grep "Traceback" /tmp/kagent-release-manifest-directory-path.stderr >/dev/null; then
    echo "release manifest unexpectedly emitted traceback for directory artifact path" >&2
    exit 1
fi
rm -rf /tmp/kagent-isolated-wheelhouse
if ! PYTHONWARNINGS=ignore .venv/bin/python -m pip wheel --no-deps . -w /tmp/kagent-isolated-wheelhouse >/tmp/kagent-isolated-wheel-build.log 2>&1; then
    echo "isolated wheel build failed; retrying without build isolation" >&2
    PYTHONWARNINGS=ignore .venv/bin/python -m pip wheel --no-deps --no-build-isolation . -w /tmp/kagent-isolated-wheelhouse >/tmp/kagent-isolated-wheel-build-fallback.log
fi
ls /tmp/kagent-isolated-wheelhouse/kagent-0.1.0-*.whl >/dev/null
rm -rf /tmp/kagent-wheel-install-venv
PYTHONWARNINGS=ignore .venv/bin/python -m venv /tmp/kagent-wheel-install-venv
PYTHONWARNINGS=ignore /tmp/kagent-wheel-install-venv/bin/python -m pip install --no-deps /tmp/kagent-wheelhouse/kagent-0.1.0-*.whl >/tmp/kagent-wheel-install.log
PYTHONWARNINGS=ignore /tmp/kagent-wheel-install-venv/bin/python - <<'PY' >/tmp/kagent-wheel-install-smoke.json
import importlib.metadata
import json

import kagent as package

distribution = importlib.metadata.distribution("kagent")
console_scripts = sorted(
    entry_point.name
    for entry_point in distribution.entry_points
    if entry_point.group == "console_scripts"
)
expected_scripts = [
    "kagent",
    "kagent-batch",
    "kagent-doctor",
    "kagent-eval",
    "kagent-metrics",
    "kagent-release-evidence",
    "kagent-release-manifest",
    "kagent-serve",
    "kagent-trace-prune",
    "kagent-trace-replay",
]
missing_scripts = sorted(set(expected_scripts) - set(console_scripts))
if package.__version__ != "0.1.0":
    raise SystemExit(f"unexpected package version: {package.__version__}")
if missing_scripts:
    raise SystemExit(f"missing console scripts: {missing_scripts}")
print(
    json.dumps(
        {
            "console_scripts": console_scripts,
            "version": package.__version__,
        },
        sort_keys=True,
    )
)
PY
