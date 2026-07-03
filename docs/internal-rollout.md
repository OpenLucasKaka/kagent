# Internal Rollout Guide

This guide is the company-internal how-to for promoting the Codex-style
LangGraph runtime from local validation to shared use. It assumes the service
will run behind an internal gateway with TLS, bearer-token auth, trace
persistence, Prometheus scraping, and provider-backed runtime planning.

## Team Access Model

Use one primary operator token and named internal subject tokens:

- `KAGENT_SERVICE_AUTH_TOKEN`: primary operator/admin token.
- `KAGENT_SERVICE_AUTH_TOKENS`: JSON map of stable team subjects to
  bearer tokens, for example `{"team-a":"...","ops":"..."}`.
- `KAGENT_SERVICE_PROTECT_DIAGNOSTICS=true`: protect `/config`,
  `/tools`, `/runtime/tools`, `/metrics`, `/metrics.prom`, `/openapi.json`,
  `/runtime/runs`, and `/runtime/runs/{run_id}` routes.

The primary token can perform operator recovery across subjects. Subject tokens
can list, inspect, and resume only traces owned by the same `auth_subject`;
cross-subject run IDs are hidden as `404 not_found`.

## Runtime Tool Policy

Start with a narrow direct-execution policy and broaden it per team only after
reviewing traces:

```sh
KAGENT_SERVICE_RUNTIME_ALLOWED_TOOLS=note,artifact,task_list
KAGENT_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT='{"ops":"note,artifact,task_list","research":["note","artifact","rubric_score"]}'
```

Unknown tool names fail configuration before startup. Leave `http_request`
outside direct allowlists unless the deployment has an explicit approval path;
policy-gated `http_request` requests produce pending approvals and can be
continued with `POST /runtime/resume`.

## Preflight Gates

Run these before staging or production promotion:

```sh
scripts/run_checks.sh
scripts/smoke_service.sh
scripts/smoke_internal_runtime.sh
scripts/production_readiness_audit.py
kagent-doctor --production --trace-dir /tmp/kagent-traces
# KAGENT_LLM_BASE_URL, KAGENT_LLM_API_KEY, and KAGENT_LLM_MODEL
# must already be set in your shell or secret manager.
KAGENT_SERVICE_RUNTIME_MAX_ITERATIONS=2 \
kagent-doctor --production --require-runtime-provider \
  --trace-dir /tmp/kagent-traces
# KAGENT_LLM_BASE_URL, KAGENT_LLM_API_KEY, and KAGENT_LLM_MODEL
# must already be set in your shell or secret manager.
scripts/smoke_real_llm_runtime.sh \
  >/tmp/kagent-provider-smoke.json
KAGENT_STAGING_BASE_URL="https://staging.example.internal" \
KAGENT_STAGING_TOKEN="$TEAM_A_STAGING_TOKEN" \
scripts/staging_acceptance.sh \
  >/tmp/kagent-staging-acceptance.json
KAGENT_OBSERVABILITY_BASE_URL="https://staging.example.internal" \
KAGENT_OBSERVABILITY_TOKEN="$TEAM_A_STAGING_TOKEN" \
scripts/observability_acceptance.sh \
  >/tmp/kagent-observability-acceptance.json
scripts/internal_rollout_acceptance.py \
  --signoff /tmp/kagent-internal-rollout-signoff.json \
  >/tmp/kagent-internal-rollout.json
scripts/production_readiness_audit.py \
  --provider-smoke-evidence /tmp/kagent-provider-smoke.json \
  --require-provider-smoke \
  --staging-acceptance-evidence /tmp/kagent-staging-acceptance.json \
  --require-staging-acceptance \
  --observability-acceptance-evidence /tmp/kagent-observability-acceptance.json \
  --require-observability-acceptance \
  --internal-rollout-evidence /tmp/kagent-internal-rollout.json \
  --require-internal-rollout
kagent-release-evidence \
  --run-checks-exit-code 0 \
  --readiness-audit /tmp/kagent-production-readiness-audit.json \
  --release-manifest /tmp/kagent-release-manifest.json \
  --provider-smoke-evidence /tmp/kagent-provider-smoke.json \
  --require-provider-smoke \
  --staging-acceptance-evidence /tmp/kagent-staging-acceptance.json \
  --require-staging-acceptance \
  --observability-acceptance-evidence /tmp/kagent-observability-acceptance.json \
  --require-observability-acceptance \
  --internal-rollout-evidence /tmp/kagent-internal-rollout.json \
  --require-internal-rollout \
  --output /tmp/kagent-release-evidence.json
scripts/production_approval_bundle.sh --strict
```

The production doctor must pass with auth, diagnostic protection, trace
persistence, bounded concurrency, rate limiting, full-trace HTTP responses
disabled, and provider configuration present.
The internal runtime smoke must pass without provider credentials; it verifies
named team tokens, `KAGENT_SERVICE_AUTH_TOKENS`,
`KAGENT_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT`, subject-scoped
runtime trace reads, subject-scoped runtime resume, admin resume audit fields,
and per-subject runtime metrics.
Archive the release evidence bundle with the rollout ticket. It ties the local
gate, readiness audit, verified wheel manifest, provider smoke evidence, file
hashes, observability acceptance evidence, package version, and generation
timestamp into one redacted JSON artifact that TL, SRE, and security reviewers
can approve without access to raw provider credentials.
If any external evidence accidentally contains a secret-like key or value, the
bundle is blocked with `evidence_secret_detected`; reviewers only see redacted
`evidence_secret_findings` with the evidence label, JSON path, and reason.
Secret-like keys are rejected even when their values are structured or already
redacted; keep evidence files to non-secret status fields such as
`llm_api_key_configured`. Full `http://` or `https://` values are also blocked;
record only host fields such as `base_url_host` or `llm_base_url_host`.
The same scan runs in `scripts/production_readiness_audit.py`, so bad evidence
is rejected before release evidence generation.

## Internal Sign-off

Capture the rollout approval as JSON and validate it before promotion:

```sh
scripts/internal_rollout_acceptance.py \
  --signoff /tmp/kagent-internal-rollout-signoff.json \
  >/tmp/kagent-internal-rollout.json
```

The source sign-off must include `rollout_id`, `release_version`,
`environment`, `signed_off_at_utc`, `runtime_effective_tool_policy_sha256`,
approver roles `tech_lead`, `sre`, `security`, and `business_owner`, plus
checks for `provider_smoke_attached`, `staging_acceptance_attached`,
`observability_acceptance_attached`,
`tool_policy_reviewed`, `team_access_reviewed`, `trace_retention_reviewed`,
and `rollback_rehearsed`. The validator output keeps only roles, status,
metadata, and `sha256`; approver names and email addresses are not copied into
the release evidence bundle.
By default the validator requires the sign-off `release_version` to match the
installed package version and `environment` to equal `internal-production`.
Use `--expected-version` or `--expected-environment` only for explicit staging
or release-candidate approval flows. Strict readiness and release-evidence
gates require the validator output to include `rollout_id`,
`signed_off_at_utc`, `required_roles_present`, `required_checks_passed`,
`approver_role_count`, `version_matches`, `environment_matches`,
`runtime_effective_tool_policy_sha256`, and `sha256`;
underspecified passing output is rejected as `invalid_evidence`.

Once provider smoke, staging acceptance, observability acceptance, and internal
rollout evidence files are present, run `scripts/production_approval_bundle.sh --strict`
or `make production-approval-bundle`. The script invokes
`scripts/production_readiness_audit.py` and
`kagent-release-evidence` with all strict evidence flags, writes
the JSON artifacts, and prints only their paths plus final status. Evidence
files that are missing are reported together as `evidence_missing` with their
labels and paths; evidence files older than 24 hours are rejected as
`evidence_stale`. Set
`KAGENT_EVIDENCE_MAX_AGE_SECONDS` only when the rollout ticket
documents a different freshness window.
If that freshness window is not a positive integer, the script reports
`evidence_max_age_invalid` as structured JSON.
If the release manifest produced by the standard gate is absent, the script
reports `release_manifest_missing` before running readiness or release-evidence
checks.
The script accepts only the explicit `--strict` argument; unknown arguments
fail as structured `unknown_argument` JSON before evidence files are inspected.
The bundle stdout includes redacted `evidence_files` metadata with path, file
name, size, `sha256`, age, and freshness state for provider smoke, staging
acceptance, observability acceptance, and internal rollout evidence.
When evidence files are present but fail strict semantic validation, the script
still writes readiness and release-evidence artifacts, prints stdout JSON with
`status: "blocked"` and `failed_checks`, and exits with exit code 1. Preflight
errors such as missing files or invalid arguments are reported as stderr JSON
before those artifacts are built.

## Provider Smoke

Use environment variables only; do not write provider secrets to files.

```sh
# KAGENT_LLM_BASE_URL, KAGENT_LLM_API_KEY, and KAGENT_LLM_MODEL
# must already be set in your shell or secret manager.
scripts/smoke_real_llm_runtime.sh \
  >/tmp/kagent-provider-smoke.json

scripts/production_readiness_audit.py \
  --provider-smoke-evidence /tmp/kagent-provider-smoke.json \
  --require-provider-smoke \
  --staging-acceptance-evidence /tmp/kagent-staging-acceptance.json \
  --require-staging-acceptance \
  --observability-acceptance-evidence /tmp/kagent-observability-acceptance.json \
  --require-observability-acceptance \
  --internal-rollout-evidence /tmp/kagent-internal-rollout.json \
  --require-internal-rollout
```

The smoke verifies CLI runtime planning, HTTP `/runtime/run`, trace
persistence, `/runtime/runs/{run_id}`, timeline lookup, metrics, policy-gated
`http_request`, and approval/resume against the configured model. It prints a
redacted summary and must not expose the raw provider key. The JSON evidence
uses `evidence_schema_version: "1"`, `provider_snapshot` with
`llm_base_url_host`, model, provider, and key-configured state, required run
IDs for approval, CLI, HTTP, and resumed executions, and `capability_checks`
for `cli_runtime`, `http_runtime`, `trace_status`, `timeline`,
`approval_resume`, and `metrics`. It also records
`runtime_effective_tool_policy_sha256` so the real model smoke can be matched
to the reviewed runtime policy boundary. Missing required provider smoke fields
are reported as `invalid_evidence` and block the strict release gate.
The captured JSON is release evidence only: it records status, run IDs,
artifact hashes, and other redacted audit fields, while provider base URL and
API key remain environment-only runtime configuration.

## Observability Acceptance

After the service is deployed behind the internal gateway, verify the live
Prometheus surface and packaged SRE artifacts:

```sh
KAGENT_OBSERVABILITY_BASE_URL="https://staging.example.internal" \
KAGENT_OBSERVABILITY_TOKEN="$TEAM_A_STAGING_TOKEN" \
scripts/observability_acceptance.sh \
  >/tmp/kagent-observability-acceptance.json
```

The script reads the token only from the environment, calls `GET /metrics.prom`,
checks required service/runtime metrics, and validates the packaged Grafana
dashboard and Prometheus rules. Set `KAGENT_PROMETHEUS_BASE_URL`,
optional `KAGENT_PROMETHEUS_TOKEN`, and
`KAGENT_PROMETHEUS_QUERY` to make it verify that Prometheus has scraped
at least one matching sample. Attach the redacted JSON to
`scripts/production_readiness_audit.py` with
`--observability-acceptance-evidence` and enforce it with
`--require-observability-acceptance` before company-wide enablement. The
evidence must include `metrics_status`, `required_metrics_present`,
`required_metric_count`, `missing_required_metrics`,
`required_metrics_sha256`, `metrics_sha256`, `grafana_dashboard_status`,
`grafana_dashboard_sha256`, `prometheus_rules_status`,
`prometheus_rules_sha256`, and `prometheus_query_status`; missing fields produce
`invalid_evidence`, `missing_required_metrics` must be an empty list, and
`required_metrics_sha256` must match the current required metric checklist. The
evidence schema must be `evidence_schema_version: "1"`.

## Staging Acceptance

Run staging with production-shaped config and short-lived test tokens:

```sh
KAGENT_STAGING_BASE_URL="https://staging.example.internal" \
KAGENT_STAGING_TOKEN="$TEAM_A_STAGING_TOKEN" \
scripts/staging_acceptance.sh \
  >/tmp/kagent-staging-acceptance.json
```

The script verifies `/health`, `/ready`, authenticated `/openapi.json`,
`/runtime/tools`, `/runtime/policy`, deterministic `/runtime/run`, persisted
runtime status/list/summary, approval queue summaries, and `/metrics`. It
prints redacted JSON only; do not write staging tokens to files. Strict
readiness and release-evidence gates require the redacted output to include
`evidence_schema_version: "1"`, `health_status`, `ready_status`,
`auth_subject`, `runtime_policy_source`, `runtime_run_status`, `runtime_run_id`,
`runtime_effective_tool_policy_count`,
`runtime_effective_tool_policy_sha256`, `runtime_note_allowed`,
`runtime_http_request_approval_required`, timeline and summary counts,
`metrics_trace_persistence`, and `metrics_runtime_runs_total`; incomplete
passing output is rejected as `invalid_evidence`.

During rollout, verify `/runtime/tools` exposes `approval_required_by_default`.
Direct local tools such as `artifact` should report `false`, while
policy-gated tools such as `http_request` and `shell_command` should report
`true` unless an explicit deployment allowlist changes the runtime policy path.
If a rollout enables `shell_command`, verify its guardrails still reject
destructive local commands, environment/secret exposure, pipe-to-shell
installers, and network-capable shell clients.
Also verify
`/runtime/policy` for each team token and confirm `effective_tool_policy`
matches the intended execution boundary: allowed tools report
`approval_required=false`, and blocked tools report `approval_required=true`.

1. Confirm `/ready` is `ready` and includes trace and idempotency persistence.
2. Confirm `/config` requires auth and redacts provider secrets.
3. Submit `/runtime/run` as each team subject and verify persisted
   `auth_subject`.
4. Verify subject-scoped runtime trace reads: team A can read team A traces and
   receives `404 not_found` for team B run IDs.
5. Verify subject-scoped runtime resume: subject tokens can resume only their
   own pending approval traces.
6. Verify primary-token admin resume preserves the original run owner in
   `auth_subject` and records `resumed_by_auth_subject=default`.
7. Check access logs for `auth_subject`, `runtime_owner_auth_subject`, and
   `resumed_by_auth_subject` without raw bearer tokens.

Use `examples/internal_runtime_client.py` as the starting point for internal
team integrations. It demonstrates Bearer auth, `Idempotency-Key`,
`POST /runtime/run`, `POST /runtime/resume`, `GET /runtime/policy`,
`GET /runtime/runs`, `auth_subject` filters, `approved_action_ids`, and
`resumed_by_auth_subject` handling with only the Python standard library.
The `policy` command supports `--tool` and `--approval-required` filters for
operator checks such as confirming `http_request` still requires approval for a
team subject before rollout expansion.

## Observability Wiring

Install and scrape:

- `deploy/prometheus/kagent-rules.yaml`
- `deploy/prometheus/kagent-servicemonitor.yaml`
- `deploy/grafana/kagent-dashboard.json`

Add Grafana panels for:

- Request rate and 5xx rate from `kagent_requests_total` and
  `kagent_responses_total`.
- Runtime latency from
  `kagent_runtime_run_duration_seconds_bucket`.
- Team usage from
  `kagent_runtime_runs_by_auth_subject_total`.
- Team outcomes from
  `kagent_runtime_run_status_by_auth_subject_total`.
- Resume activity from
  `kagent_runtime_resumes_by_auth_subject_total`.
- Approval pressure from
  `kagent_runtime_approval_required_total`.
- Stale pending approval queue depth from
  `kagent_runtime_stale_pending_approvals_current`; alert
  `SelfCorrectingAgentRuntimeStalePendingApprovals` should notify owners when
  pending approvals exceed the configured age threshold.
- Tool failures from
  `kagent_runtime_observation_errors_total`.

Alert routes should page the owner for service down, high 5xx rate, trace
persistence failures, runtime run failures, stale pending approvals, and tool
execution timeouts.
Informational notifications are enough for rate limiting, malformed requests,
idempotency conflicts, and per-subject resume activity during early rollout.

## Rollback

Rollback must preserve trace and idempotency volumes:

1. Stop sending new traffic through the gateway.
2. Revert to the previous immutable image tag.
3. Keep the failed image and trace directory available for incident review.
4. Verify `/ready`, `/metrics.prom`, and one compact `/runtime/run` before
   restoring traffic.
5. Compare access logs by `request_id`, `run_id`, `auth_subject`,
   `runtime_owner_auth_subject`, and `resumed_by_auth_subject`.

## Sign-off

Before opening the service to an internal team, record:

- Service version and image tag.
- Owning team and on-call channel.
- Team subjects configured in `KAGENT_SERVICE_AUTH_TOKENS`.
- Runtime tool allowlists and approval-required tools.
- Provider model, base URL hostname, timeout, retry count, and retry backoff.
- Evidence links for `scripts/run_checks.sh`, production doctor, provider
  smoke, release evidence bundle, staging acceptance, Prometheus scrape,
  Grafana dashboard, and rollback rehearsal.
