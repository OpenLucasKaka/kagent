#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

cleanup_local_build_artifacts() {
    rm -rf build dist *.egg-info src/*.egg-info
}
trap cleanup_local_build_artifacts EXIT

PYTHONWARNINGS=ignore .venv/bin/python -m pip install -e '.[dev]' >/tmp/self-correcting-agent-install.log
PYTHONWARNINGS=ignore .venv/bin/python -m pytest
PYTHONWARNINGS=ignore .venv/bin/python -m ruff check src tests
rm -rf /tmp/self-correcting-agent-pycache
PYTHONPYCACHEPREFIX=/tmp/self-correcting-agent-pycache PYTHONWARNINGS=ignore .venv/bin/python -m compileall -q src tests
PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent --version >/tmp/self-correcting-agent-entrypoint-version.json
printf '{"id":"sum","goal":"calculate 2 + 3"}\n' >/tmp/self-correcting-agent-batch-input.jsonl
PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent-batch /tmp/self-correcting-agent-batch-input.jsonl /tmp/self-correcting-agent-batch-output.jsonl --fail-on-failure >/tmp/self-correcting-agent-batch-report.json
PYTHONWARNINGS=ignore .venv/bin/python -m self_correcting_langgraph_agent.cli --version >/tmp/self-correcting-agent-version.json
SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_SIZE=17 \
PYTHONWARNINGS=ignore \
    .venv/bin/self-correcting-agent-doctor \
    --trace-dir /tmp/self-correcting-agent-doctor-traces \
    >/tmp/self-correcting-agent-doctor.json
grep '"idempotency_cache_size": "17"' /tmp/self-correcting-agent-doctor.json >/dev/null
grep '"runtime_policy"' /tmp/self-correcting-agent-doctor.json >/dev/null
grep '"effective_tool_policy_sha256"' /tmp/self-correcting-agent-doctor.json >/dev/null
if PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent-doctor --require-auth >/tmp/self-correcting-agent-doctor-require-auth.json; then
    echo "doctor --require-auth unexpectedly passed without auth token" >&2
    exit 1
fi
if SELF_CORRECTING_SERVICE_AUTH_TOKEN=release-gate-token-é \
PYTHONWARNINGS=ignore \
    .venv/bin/self-correcting-agent-doctor --require-auth \
    >/tmp/self-correcting-agent-doctor-require-auth-unsafe-token.json; then
    echo "doctor --require-auth unexpectedly passed with unsafe auth token" >&2
    exit 1
fi
grep "auth_token_unsafe" \
    /tmp/self-correcting-agent-doctor-require-auth-unsafe-token.json >/dev/null
if SELF_CORRECTING_SERVICE_AUTH_TOKEN=replace-with-a-long-random-token \
PYTHONWARNINGS=ignore \
    .venv/bin/self-correcting-agent-doctor --require-auth \
    >/tmp/self-correcting-agent-doctor-require-auth-placeholder-token.json; then
    echo "doctor --require-auth unexpectedly passed with placeholder auth token" >&2
    exit 1
fi
grep "auth_token_placeholder" \
    /tmp/self-correcting-agent-doctor-require-auth-placeholder-token.json >/dev/null
SELF_CORRECTING_SERVICE_AUTH_TOKEN=release-gate-token \
SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE=60 \
SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS=4 \
SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS=true \
PYTHONWARNINGS=ignore \
    .venv/bin/self-correcting-agent-doctor --production \
    --trace-dir /tmp/self-correcting-agent-doctor-production-traces \
    >/tmp/self-correcting-agent-doctor-production.json
if SELF_CORRECTING_SERVICE_AUTH_TOKEN=replace-with-a-long-random-token \
SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE=60 \
SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS=4 \
SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS=true \
PYTHONWARNINGS=ignore \
    .venv/bin/self-correcting-agent-doctor --production \
    --trace-dir /tmp/self-correcting-agent-doctor-placeholder-token-production-traces \
    >/tmp/self-correcting-agent-doctor-placeholder-token-production.json; then
    echo "doctor --production unexpectedly passed with placeholder auth token" >&2
    exit 1
fi
if SELF_CORRECTING_SERVICE_AUTH_TOKEN=release-gate-token-é \
SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE=60 \
SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS=4 \
SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS=true \
PYTHONWARNINGS=ignore \
    .venv/bin/self-correcting-agent-doctor --production \
    --trace-dir /tmp/self-correcting-agent-doctor-unsafe-token-production-traces \
    >/tmp/self-correcting-agent-doctor-unsafe-token-production.json; then
    echo "doctor --production unexpectedly passed with unsafe auth token" >&2
    exit 1
fi
grep "auth_token_unsafe" \
    /tmp/self-correcting-agent-doctor-unsafe-token-production.json >/dev/null
if SELF_CORRECTING_SERVICE_AUTH_TOKEN=release-gate-token \
SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE=60 \
SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS=4 \
SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS=true \
SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE=true \
PYTHONWARNINGS=ignore \
    .venv/bin/self-correcting-agent-doctor --production \
    --trace-dir /tmp/self-correcting-agent-doctor-full-trace-production-traces \
    >/tmp/self-correcting-agent-doctor-full-trace-production.json; then
    echo "doctor --production unexpectedly passed with full trace responses enabled" >&2
    exit 1
fi
RUN_CHECKS_PROVIDER_VALUE=configured-provider-value
SELF_CORRECTING_SERVICE_AUTH_TOKEN=release-gate-token \
SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE=60 \
SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS=4 \
SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS=true \
SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS=2 \
SELF_CORRECTING_LLM_BASE_URL=configured-provider-base \
SELF_CORRECTING_LLM_API_KEY="$RUN_CHECKS_PROVIDER_VALUE" \
SELF_CORRECTING_LLM_MODEL=agent-runtime-model \
PYTHONWARNINGS=ignore \
    .venv/bin/self-correcting-agent-doctor --production \
    --require-runtime-provider \
    --trace-dir /tmp/self-correcting-agent-doctor-runtime-provider-traces \
    >/tmp/self-correcting-agent-doctor-runtime-provider.json
if SELF_CORRECTING_SERVICE_AUTH_TOKEN=release-gate-token \
SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE=60 \
SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS=4 \
SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS=true \
SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS=1 \
PYTHONWARNINGS=ignore \
    .venv/bin/self-correcting-agent-doctor --production \
    --require-runtime-provider \
    --trace-dir /tmp/self-correcting-agent-doctor-runtime-provider-missing-traces \
    >/tmp/self-correcting-agent-doctor-runtime-provider-missing.json; then
    echo "doctor --require-runtime-provider unexpectedly passed without provider config" >&2
    exit 1
fi
grep "llm_base_url_required" \
    /tmp/self-correcting-agent-doctor-runtime-provider-missing.json >/dev/null
grep "llm_model_required" \
    /tmp/self-correcting-agent-doctor-runtime-provider-missing.json >/dev/null
grep "llm_api_key_required" \
    /tmp/self-correcting-agent-doctor-runtime-provider-missing.json >/dev/null
grep "runtime_iterations_too_low" \
    /tmp/self-correcting-agent-doctor-runtime-provider-missing.json >/dev/null
if SELF_CORRECTING_SERVICE_PORT=not-a-port \
PYTHONWARNINGS=ignore \
    .venv/bin/self-correcting-agent-doctor --production \
    >/tmp/self-correcting-agent-doctor-invalid-env.stdout \
    2>/tmp/self-correcting-agent-doctor-invalid-env.stderr; then
    echo "doctor --production unexpectedly passed with invalid env config" >&2
    exit 1
fi
grep "SELF_CORRECTING_SERVICE_PORT must be an integer" \
    /tmp/self-correcting-agent-doctor-invalid-env.stderr >/dev/null
if grep "Traceback" /tmp/self-correcting-agent-doctor-invalid-env.stderr >/dev/null; then
    echo "doctor unexpectedly emitted traceback for invalid env config" >&2
    exit 1
fi
PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent-serve --help >/tmp/self-correcting-agent-serve-help.txt
if SELF_CORRECTING_SERVICE_PORT=not-a-port \
PYTHONWARNINGS=ignore \
    .venv/bin/self-correcting-agent-serve --help \
    >/tmp/self-correcting-agent-serve-invalid-env.stdout \
    2>/tmp/self-correcting-agent-serve-invalid-env.stderr; then
    echo "serve --help unexpectedly passed with invalid env config" >&2
    exit 1
fi
grep "SELF_CORRECTING_SERVICE_PORT must be an integer" \
    /tmp/self-correcting-agent-serve-invalid-env.stderr >/dev/null
if grep "Traceback" /tmp/self-correcting-agent-serve-invalid-env.stderr >/dev/null; then
    echo "serve unexpectedly emitted traceback for invalid env config" >&2
    exit 1
fi
PYTHONWARNINGS=ignore sh scripts/smoke_service.sh
PYTHONWARNINGS=ignore sh scripts/smoke_internal_runtime.sh >/tmp/self-correcting-agent-internal-runtime-smoke.json
PYTHONWARNINGS=ignore .venv/bin/python -m self_correcting_langgraph_agent.cli "calculate 2 + 3 then count words in 'ship small reliable agents'" >/tmp/self-correcting-agent-smoke.json
PYTHONWARNINGS=ignore .venv/bin/python -m self_correcting_langgraph_agent.cli "calculate 2 + 3 then subtract 10 - 4" --plan >/tmp/self-correcting-agent-plan.json
PYTHONWARNINGS=ignore .venv/bin/python -m self_correcting_langgraph_agent.cli "uppercase text in 'agent loop'" --inject-fault "uppercase text in 'agent loop'=empty-answer" --summary --output /tmp/self-correcting-agent-summary-output.json >/tmp/self-correcting-agent-summary.json
rm -f /tmp/self-correcting-agent-session-memory.json
printf '我是卡卡\nexit\n' | PYTHONWARNINGS=ignore .venv/bin/python -m self_correcting_langgraph_agent.cli \
    --runtime \
    --interactive \
    --max-iterations 1 \
    --runtime-plan '{"actions":[],"final_answer":"你好，卡卡。"}' \
    --session-memory /tmp/self-correcting-agent-session-memory.json \
    >/tmp/self-correcting-agent-session-memory-smoke.json
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import json
import stat
from pathlib import Path

output = json.load(open("/tmp/self-correcting-agent-session-memory-smoke.json", encoding="utf-8"))
memory_path = Path("/tmp/self-correcting-agent-session-memory.json")
memory = json.loads(memory_path.read_text(encoding="utf-8"))
mode = stat.S_IMODE(memory_path.stat().st_mode)
if output["status"] != "done" or output["answer"] != "你好，卡卡。":
    raise SystemExit(f"unexpected session memory smoke output: {output}")
if memory["schema_version"] != "1":
    raise SystemExit(f"unexpected session memory schema: {memory}")
if memory["turns"] != [{"user": "我是卡卡", "assistant": "你好，卡卡。"}]:
    raise SystemExit(f"unexpected session memory turns: {memory}")
if mode != 0o600:
    raise SystemExit(f"unexpected session memory file mode: {oct(mode)}")
PY
PYTHONWARNINGS=ignore .venv/bin/python -m self_correcting_langgraph_agent.eval.evaluator --fail-on-failure >/tmp/self-correcting-agent-eval.json
PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent-eval --list-cases >/tmp/self-correcting-agent-entrypoint-eval-cases.json
PYTHONWARNINGS=ignore .venv/bin/python -m self_correcting_langgraph_agent.eval.evaluator --list-cases >/tmp/self-correcting-agent-eval-cases.json
PYTHONWARNINGS=ignore .venv/bin/python -m self_correcting_langgraph_agent.eval.evaluator --category recovery >/tmp/self-correcting-agent-eval-recovery.json
PYTHONWARNINGS=ignore .venv/bin/python -m self_correcting_langgraph_agent.eval.evaluator --case subtraction_tool_success >/tmp/self-correcting-agent-eval-subtraction.json
printf '{"iteration":1,"duration_seconds":"1","status":"passed","checks_exit_code":0,"evaluator_passed":14,"evaluator_failed":0,"evaluator_slowest_case":"multi_step_success","evaluator_recovered_cases":"4","evaluator_recovery_rate":"0.29","evaluator_category_counts":{"failure":"3","recovery":"4","tool":"6","workflow":"1"}}\n' >/tmp/self-correcting-agent-metrics.jsonl
PYTHONWARNINGS=ignore .venv/bin/python -m self_correcting_langgraph_agent.ops.metrics /tmp/self-correcting-agent-metrics.jsonl --output /tmp/self-correcting-agent-metrics-summary-output.json >/tmp/self-correcting-agent-metrics-summary.json
PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent-metrics /tmp/self-correcting-agent-metrics.jsonl --require-recent-health healthy >/tmp/self-correcting-agent-entrypoint-metrics-summary.json
rm -rf /tmp/self-correcting-agent-trace-prune-smoke
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import os
from pathlib import Path

trace_dir = Path("/tmp/self-correcting-agent-trace-prune-smoke")
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
PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent-trace-prune \
    /tmp/self-correcting-agent-trace-prune-smoke \
    --max-age-days 1 \
    >/tmp/self-correcting-agent-trace-prune-dry-run.json
PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent-trace-prune \
    /tmp/self-correcting-agent-trace-prune-smoke \
    --max-age-days 1 \
    --delete \
    >/tmp/self-correcting-agent-trace-prune-delete.json
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

trace_dir = Path("/tmp/self-correcting-agent-trace-prune-smoke")
dry_run = json.load(open("/tmp/self-correcting-agent-trace-prune-dry-run.json", encoding="utf-8"))
deleted = json.load(open("/tmp/self-correcting-agent-trace-prune-delete.json", encoding="utf-8"))
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
PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent-trace-prune \
    /tmp/self-correcting-agent-trace-prune-smoke \
    --max-age-days 1 \
    --runtime-only \
    >/tmp/self-correcting-agent-runtime-trace-prune-dry-run.json
PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent-trace-prune \
    /tmp/self-correcting-agent-trace-prune-smoke \
    --max-age-days 1 \
    --runtime-only \
    --delete \
    >/tmp/self-correcting-agent-runtime-trace-prune-delete.json
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import json
from pathlib import Path

trace_dir = Path("/tmp/self-correcting-agent-trace-prune-smoke")
runtime_dry_run = json.load(open("/tmp/self-correcting-agent-runtime-trace-prune-dry-run.json", encoding="utf-8"))
runtime_deleted = json.load(open("/tmp/self-correcting-agent-runtime-trace-prune-delete.json", encoding="utf-8"))
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

trace_path = Path("/tmp/self-correcting-agent-trace-replay.json")
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
                                "path": "docs/plan.md",
                                "operation": "update",
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
PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent-trace-replay \
    /tmp/self-correcting-agent-trace-replay.json \
    >/tmp/self-correcting-agent-trace-replay-summary.json
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import json

summary_text = open(
    "/tmp/self-correcting-agent-trace-replay-summary.json", encoding="utf-8"
).read()
summary = json.loads(summary_text)
if summary["tool_counts"] != {"apply_patch": "1", "read_file": "1"}:
    raise SystemExit(f"unexpected trace replay tool counts: {summary}")
if summary["changed_files"][0]["operation"] != "update":
    raise SystemExit(f"unexpected trace replay changed files: {summary}")
if summary["progress_event_count"] != "4":
    raise SystemExit(f"unexpected trace replay progress count: {summary}")
if "secret body should not replay" in summary_text:
    raise SystemExit("trace replay leaked read_file content")
if "secret patch should not replay" in summary_text:
    raise SystemExit("trace replay leaked action input patch")
if "secret progress metadata should not replay" in summary_text:
    raise SystemExit("trace replay leaked progress metadata")
PY
rm -rf /tmp/self-correcting-agent-wheelhouse
PYTHONWARNINGS=ignore .venv/bin/python -m pip wheel --no-deps --no-build-isolation . -w /tmp/self-correcting-agent-wheelhouse >/tmp/self-correcting-agent-wheel-build.log
ls /tmp/self-correcting-agent-wheelhouse/self_correcting_langgraph_agent-0.1.0-*.whl >/dev/null
PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent-release-manifest \
    /tmp/self-correcting-agent-wheelhouse/self_correcting_langgraph_agent-0.1.0-*.whl \
    --output /tmp/self-correcting-agent-release-manifest.json \
    >/tmp/self-correcting-agent-release-manifest.stdout.json
PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent-release-manifest \
    --verify /tmp/self-correcting-agent-release-manifest.json \
    >/tmp/self-correcting-agent-release-manifest-verify.json
PYTHONWARNINGS=ignore .venv/bin/python scripts/production_readiness_audit.py \
    >/tmp/self-correcting-agent-production-readiness-audit.json
PYTHONWARNINGS=ignore .venv/bin/python -m self_correcting_langgraph_agent.ops.release_evidence \
    --run-checks-exit-code 0 \
    --readiness-audit /tmp/self-correcting-agent-production-readiness-audit.json \
    --release-manifest /tmp/self-correcting-agent-release-manifest.json \
    --output /tmp/self-correcting-agent-release-evidence.json \
    >/tmp/self-correcting-agent-release-evidence.stdout.json
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import json

manifest = json.load(open("/tmp/self-correcting-agent-release-manifest.json", encoding="utf-8"))
evidence = json.load(open("/tmp/self-correcting-agent-release-evidence.json", encoding="utf-8"))
if manifest["package"] != "self-correcting-langgraph-agent":
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
printf '{not-json' >/tmp/self-correcting-agent-release-manifest-invalid.json
if PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent-release-manifest \
    --verify /tmp/self-correcting-agent-release-manifest-invalid.json \
    >/tmp/self-correcting-agent-release-manifest-invalid.stdout \
    2>/tmp/self-correcting-agent-release-manifest-invalid.stderr; then
    echo "release manifest unexpectedly passed with invalid JSON" >&2
    exit 1
fi
grep "invalid release manifest JSON" \
    /tmp/self-correcting-agent-release-manifest-invalid.stderr >/dev/null
if grep "Traceback" /tmp/self-correcting-agent-release-manifest-invalid.stderr >/dev/null; then
    echo "release manifest unexpectedly emitted traceback for invalid JSON" >&2
    exit 1
fi
printf '{"package":"self-correcting-langgraph-agent","version":"0.1.0","artifact_count":"1","artifacts":[{"sha256":"abc","size_bytes":"123"}]}\n' >/tmp/self-correcting-agent-release-manifest-missing-path.json
if PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent-release-manifest \
    --verify /tmp/self-correcting-agent-release-manifest-missing-path.json \
    >/tmp/self-correcting-agent-release-manifest-missing-path.stdout \
    2>/tmp/self-correcting-agent-release-manifest-missing-path.stderr; then
    echo "release manifest unexpectedly passed with a missing artifact path" >&2
    exit 1
fi
grep "artifact path missing" \
    /tmp/self-correcting-agent-release-manifest-missing-path.stdout >/dev/null
if grep "Traceback" /tmp/self-correcting-agent-release-manifest-missing-path.stderr >/dev/null; then
    echo "release manifest unexpectedly emitted traceback for missing artifact path" >&2
    exit 1
fi
PYTHONWARNINGS=ignore .venv/bin/python - <<'PY'
import json

manifest = {
    "package": "self-correcting-langgraph-agent",
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
with open("/tmp/self-correcting-agent-release-manifest-invalid-path.json", "w", encoding="utf-8") as handle:
    json.dump(manifest, handle)
    handle.write("\n")
PY
if PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent-release-manifest \
    --verify /tmp/self-correcting-agent-release-manifest-invalid-path.json \
    >/tmp/self-correcting-agent-release-manifest-invalid-path.stdout \
    2>/tmp/self-correcting-agent-release-manifest-invalid-path.stderr; then
    echo "release manifest unexpectedly passed with an invalid artifact path" >&2
    exit 1
fi
grep "artifact path invalid" \
    /tmp/self-correcting-agent-release-manifest-invalid-path.stdout >/dev/null
if grep "Traceback" /tmp/self-correcting-agent-release-manifest-invalid-path.stderr >/dev/null; then
    echo "release manifest unexpectedly emitted traceback for invalid artifact path" >&2
    exit 1
fi
rm -rf /tmp/self-correcting-agent-release-manifest-artifact-dir
mkdir -p /tmp/self-correcting-agent-release-manifest-artifact-dir
printf '{"package":"self-correcting-langgraph-agent","version":"0.1.0","artifact_count":"1","artifacts":[{"path":"/tmp/self-correcting-agent-release-manifest-artifact-dir","sha256":"abc","size_bytes":"123"}]}\n' >/tmp/self-correcting-agent-release-manifest-directory-path.json
if PYTHONWARNINGS=ignore .venv/bin/self-correcting-agent-release-manifest \
    --verify /tmp/self-correcting-agent-release-manifest-directory-path.json \
    >/tmp/self-correcting-agent-release-manifest-directory-path.stdout \
    2>/tmp/self-correcting-agent-release-manifest-directory-path.stderr; then
    echo "release manifest unexpectedly passed with a directory artifact path" >&2
    exit 1
fi
grep "artifact is not a file" \
    /tmp/self-correcting-agent-release-manifest-directory-path.stdout >/dev/null
if grep "Traceback" /tmp/self-correcting-agent-release-manifest-directory-path.stderr >/dev/null; then
    echo "release manifest unexpectedly emitted traceback for directory artifact path" >&2
    exit 1
fi
rm -rf /tmp/self-correcting-agent-isolated-wheelhouse
PYTHONWARNINGS=ignore .venv/bin/python -m pip wheel --no-deps . -w /tmp/self-correcting-agent-isolated-wheelhouse >/tmp/self-correcting-agent-isolated-wheel-build.log
ls /tmp/self-correcting-agent-isolated-wheelhouse/self_correcting_langgraph_agent-0.1.0-*.whl >/dev/null
rm -rf /tmp/self-correcting-agent-wheel-install-venv
PYTHONWARNINGS=ignore .venv/bin/python -m venv /tmp/self-correcting-agent-wheel-install-venv
PYTHONWARNINGS=ignore /tmp/self-correcting-agent-wheel-install-venv/bin/python -m pip install --no-deps /tmp/self-correcting-agent-wheelhouse/self_correcting_langgraph_agent-0.1.0-*.whl >/tmp/self-correcting-agent-wheel-install.log
PYTHONWARNINGS=ignore /tmp/self-correcting-agent-wheel-install-venv/bin/python - <<'PY' >/tmp/self-correcting-agent-wheel-install-smoke.json
import importlib.metadata
import json

import self_correcting_langgraph_agent as package

distribution = importlib.metadata.distribution("self-correcting-langgraph-agent")
console_scripts = sorted(
    entry_point.name
    for entry_point in distribution.entry_points
    if entry_point.group == "console_scripts"
)
expected_scripts = [
    "self-correcting-agent",
    "self-correcting-agent-batch",
    "self-correcting-agent-doctor",
    "self-correcting-agent-eval",
    "self-correcting-agent-metrics",
    "self-correcting-agent-release-evidence",
    "self-correcting-agent-release-manifest",
    "self-correcting-agent-serve",
    "self-correcting-agent-trace-prune",
    "self-correcting-agent-trace-replay",
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
