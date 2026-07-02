#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"

for argument in "$@"; do
    case "$argument" in
        --strict)
            ;;
        *)
            "$PYTHON_BIN" - "$argument" <<'PY'
import json
import sys

print(
    json.dumps(
        {
            "error": "unknown_argument",
            "argument": sys.argv[1],
            "supported_arguments": ["--strict"],
        },
        sort_keys=True,
    ),
    file=sys.stderr,
)
raise SystemExit(2)
PY
            ;;
    esac
done

PROVIDER_SMOKE_EVIDENCE="${SELF_CORRECTING_PROVIDER_SMOKE_EVIDENCE:-/tmp/self-correcting-agent-provider-smoke.json}"
STAGING_ACCEPTANCE_EVIDENCE="${SELF_CORRECTING_STAGING_ACCEPTANCE_EVIDENCE:-/tmp/self-correcting-agent-staging-acceptance.json}"
OBSERVABILITY_ACCEPTANCE_EVIDENCE="${SELF_CORRECTING_OBSERVABILITY_ACCEPTANCE_EVIDENCE:-/tmp/self-correcting-agent-observability-acceptance.json}"
INTERNAL_ROLLOUT_EVIDENCE="${SELF_CORRECTING_INTERNAL_ROLLOUT_EVIDENCE:-/tmp/self-correcting-agent-internal-rollout.json}"
RELEASE_MANIFEST="${SELF_CORRECTING_RELEASE_MANIFEST:-/tmp/self-correcting-agent-release-manifest.json}"
RUN_CHECKS_EXIT_CODE="${SELF_CORRECTING_RUN_CHECKS_EXIT_CODE:-0}"
READINESS_AUDIT_OUTPUT="${SELF_CORRECTING_READINESS_AUDIT_OUTPUT:-/tmp/self-correcting-agent-production-readiness-audit.json}"
RELEASE_EVIDENCE_OUTPUT="${SELF_CORRECTING_RELEASE_EVIDENCE_OUTPUT:-/tmp/self-correcting-agent-release-evidence.json}"
EVIDENCE_MAX_AGE_SECONDS="${SELF_CORRECTING_EVIDENCE_MAX_AGE_SECONDS:-86400}"

"$PYTHON_BIN" - \
    "$PROVIDER_SMOKE_EVIDENCE" "provider_smoke" \
    "$STAGING_ACCEPTANCE_EVIDENCE" "staging_acceptance" \
    "$OBSERVABILITY_ACCEPTANCE_EVIDENCE" "observability_acceptance" \
    "$INTERNAL_ROLLOUT_EVIDENCE" "internal_rollout" <<'PY'
import json
import os
import sys

missing = []
args = sys.argv[1:]
for index in range(0, len(args), 2):
    path = args[index]
    label = args[index + 1]
    if not os.path.isfile(path):
        missing.append({"label": label, "path": path})
if missing:
    print(json.dumps({"error": "evidence_missing", "missing": missing}, sort_keys=True), file=sys.stderr)
    raise SystemExit(2)
PY

"$PYTHON_BIN" - "$EVIDENCE_MAX_AGE_SECONDS" \
    "$PROVIDER_SMOKE_EVIDENCE" "provider_smoke" \
    "$STAGING_ACCEPTANCE_EVIDENCE" "staging_acceptance" \
    "$OBSERVABILITY_ACCEPTANCE_EVIDENCE" "observability_acceptance" \
    "$INTERNAL_ROLLOUT_EVIDENCE" "internal_rollout" <<'PY'
import json
import os
import sys
import time

try:
    max_age_seconds = int(sys.argv[1])
except ValueError:
    print(
        json.dumps(
            {
                "error": "evidence_max_age_invalid",
                "environment_variable": "SELF_CORRECTING_EVIDENCE_MAX_AGE_SECONDS",
                "reason": "must_be_integer",
                "value": sys.argv[1],
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    raise SystemExit(2)
if max_age_seconds <= 0:
    print(
        json.dumps(
            {
                "error": "evidence_max_age_invalid",
                "environment_variable": "SELF_CORRECTING_EVIDENCE_MAX_AGE_SECONDS",
                "reason": "must_be_positive",
                "value": sys.argv[1],
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    raise SystemExit(2)

now = time.time()
stale = []
args = sys.argv[2:]
for index in range(0, len(args), 2):
    path = args[index]
    label = args[index + 1]
    age_seconds = max(0, int(now - os.path.getmtime(path)))
    if age_seconds > max_age_seconds:
        stale.append(
            {
                "label": label,
                "age_seconds": str(age_seconds),
                "max_age_seconds": str(max_age_seconds),
            }
        )
if stale:
    print(json.dumps({"error": "evidence_stale", "stale": stale}, sort_keys=True), file=sys.stderr)
    raise SystemExit(1)
PY

"$PYTHON_BIN" - "$RELEASE_MANIFEST" <<'PY'
import json
import os
import sys

path = sys.argv[1]
if not os.path.isfile(path):
    print(
        json.dumps(
            {"error": "release_manifest_missing", "path": path},
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    raise SystemExit(2)
PY

if "$PYTHON_BIN" scripts/production_readiness_audit.py \
    --provider-smoke-evidence "$PROVIDER_SMOKE_EVIDENCE" \
    --require-provider-smoke \
    --staging-acceptance-evidence "$STAGING_ACCEPTANCE_EVIDENCE" \
    --require-staging-acceptance \
    --observability-acceptance-evidence "$OBSERVABILITY_ACCEPTANCE_EVIDENCE" \
    --require-observability-acceptance \
    --internal-rollout-evidence "$INTERNAL_ROLLOUT_EVIDENCE" \
    --require-internal-rollout \
    >"$READINESS_AUDIT_OUTPUT"; then
    :
fi

if "$PYTHON_BIN" -m self_correcting_langgraph_agent.ops.release_evidence \
    --run-checks-exit-code "$RUN_CHECKS_EXIT_CODE" \
    --readiness-audit "$READINESS_AUDIT_OUTPUT" \
    --release-manifest "$RELEASE_MANIFEST" \
    --provider-smoke-evidence "$PROVIDER_SMOKE_EVIDENCE" \
    --require-provider-smoke \
    --staging-acceptance-evidence "$STAGING_ACCEPTANCE_EVIDENCE" \
    --require-staging-acceptance \
    --observability-acceptance-evidence "$OBSERVABILITY_ACCEPTANCE_EVIDENCE" \
    --require-observability-acceptance \
    --internal-rollout-evidence "$INTERNAL_ROLLOUT_EVIDENCE" \
    --require-internal-rollout \
    --output "$RELEASE_EVIDENCE_OUTPUT" \
    >/tmp/self-correcting-agent-production-approval-bundle-release-evidence.stdout.json; then
    :
fi
# release_evidence blocks secret-bearing evidence with evidence_secret_detected.

"$PYTHON_BIN" - "$READINESS_AUDIT_OUTPUT" "$RELEASE_EVIDENCE_OUTPUT" \
    "$EVIDENCE_MAX_AGE_SECONDS" \
    "$PROVIDER_SMOKE_EVIDENCE" "provider_smoke" \
    "$STAGING_ACCEPTANCE_EVIDENCE" "staging_acceptance" \
    "$OBSERVABILITY_ACCEPTANCE_EVIDENCE" "observability_acceptance" \
    "$INTERNAL_ROLLOUT_EVIDENCE" "internal_rollout" <<'PY'
import hashlib
import json
import os
import sys
import time

readiness_path = sys.argv[1]
release_path = sys.argv[2]
max_age_seconds = int(sys.argv[3])
release = json.load(open(release_path, encoding="utf-8"))

evidence_files = {}
now = time.time()
args = sys.argv[4:]
for index in range(0, len(args), 2):
    path = args[index]
    label = args[index + 1]
    data = open(path, "rb").read()
    age_seconds = max(0, int(now - os.path.getmtime(path)))
    evidence_files[label] = {
        "path": path,
        "file_name": os.path.basename(path),
        "size_bytes": str(len(data)),
        "sha256": hashlib.sha256(data).hexdigest(),
        "age_seconds": str(age_seconds),
        "max_age_seconds": str(max_age_seconds),
        "fresh": str(age_seconds <= max_age_seconds).lower(),
    }

payload = {
    "status": release.get("status", "unknown"),
    "readiness_audit": readiness_path,
    "release_evidence": release_path,
    "failed_checks": release.get("summary", {}).get("failed_checks", []),
    "evidence_max_age_seconds": str(max_age_seconds),
    "evidence_files": evidence_files,
}
print(json.dumps(payload, indent=2, sort_keys=True))
if payload["status"] != "ready":
    raise SystemExit(1)
PY
