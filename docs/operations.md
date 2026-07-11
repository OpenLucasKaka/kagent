# Operations Runbook

This runbook covers local and CI operation for the bounded LangGraph agent.

## Daily checks

Use the standard gate before shipping changes:

```sh
scripts/run_checks.sh
```

The same command runs in CI. It covers tests, Ruff linting, byte-compilation,
CLI smoke checks, a real service smoke check, evaluator smoke checks, metrics
smoke checks, no-build-isolation and isolated wheel builds, an offline fallback
for local package-index outages during the isolated build, and clean wheel
install metadata smoke. It also writes
`/tmp/kagent-release-manifest.json` with artifact `sha256`
hashes through `kagent-release-manifest` so release automation
can compare the shipped wheel against the gate output. Use
`kagent-release-manifest --verify /tmp/kagent-release-manifest.json`
to verify that the artifact still matches the manifest before publishing or
rolling back. Verification fails on `package mismatch`, `version mismatch`,
`sha256`, size, missing artifact, `artifact_count mismatch`, and
`artifacts must be a list`, `artifact entry must be an object`,
`artifact path missing`, `artifact path invalid`, or `artifact is not a file`
errors so wrong-package, wrong-version, truncated, or hand-edited manifests do
not silently pass release checks.

Run only the service smoke check with:

```sh
scripts/smoke_service.sh
```

Run the opt-in real LLM runtime smoke before promoting a provider-backed
deployment:

```sh
# KAGENT_LLM_BASE_URL, KAGENT_LLM_API_KEY, and KAGENT_LLM_MODEL
# must already be set in your shell or secret manager.
scripts/smoke_real_llm_runtime.sh
```

This real LLM runtime smoke is intentionally not part of `scripts/run_checks.sh`
because it needs network access, provider credentials, and a live
OpenAI-compatible model. It verifies CLI runtime planning, HTTP `/runtime/run`,
trace persistence, `/runtime/runs/{run_id}`, timeline lookup, metrics, and the
approval/resume path. Its JSON output includes `evidence_schema_version`,
`provider_snapshot` with `llm_base_url_host`, model, and key-configured state,
required approval, CLI, HTTP, and resumed run IDs, plus `capability_checks` for
`cli_runtime`, `http_runtime`, `trace_status`, `timeline`, `approval_resume`,
and `metrics`, plus `runtime_effective_tool_policy_sha256` from
`/runtime/policy`. Missing required fields are treated as `invalid_evidence`
by strict readiness and release-evidence gates. It must not contain the raw
API key or full provider base URL.
The script reads credentials only from environment variables and prints a
redacted JSON summary without the API key.

Use the staging acceptance script after deploying the service and before
opening it to internal users:

```sh
KAGENT_STAGING_BASE_URL="https://staging.example.internal" \
KAGENT_STAGING_TOKEN="$TEAM_A_STAGING_TOKEN" \
scripts/staging_acceptance.sh \
  >/tmp/kagent-staging-acceptance.json
```

It verifies authenticated diagnostics, runtime policy, deterministic runtime
execution, persisted status/list/summary reads, approval queue summaries, and
metrics against the deployed service without printing the staging token. Strict
promotion gates reject passing staging output as `invalid_evidence` unless it
includes `evidence_schema_version: "1"`, live health/ready statuses, auth
subject, runtime policy source, `runtime_effective_tool_policy_count`,
`runtime_effective_tool_policy_sha256`, `runtime_note_allowed`,
`runtime_http_request_approval_required`, run status and ID, timeline/summary
counts, trace-persistence metrics, and runtime run totals.
When strict production gates receive provider smoke, staging acceptance, and
internal rollout evidence together, every attached
`runtime_effective_tool_policy_sha256` must match. If the fingerprints differ,
rerun the stale evidence producer before promotion; the gates report
`runtime_policy_fingerprint_mismatch` instead of accepting mixed policy
approval.

Run observability acceptance after the deployment is reachable from the same
network path Prometheus will use:

```sh
KAGENT_OBSERVABILITY_BASE_URL="https://staging.example.internal" \
KAGENT_OBSERVABILITY_TOKEN="$TEAM_A_STAGING_TOKEN" \
scripts/observability_acceptance.sh \
  >/tmp/kagent-observability-acceptance.json
```

The script verifies live `GET /metrics.prom`, required Prometheus metric names,
and packaged Grafana/Prometheus artifacts. When
`KAGENT_PROMETHEUS_BASE_URL` is set, it also calls Prometheus
`/api/v1/query` with `KAGENT_PROMETHEUS_QUERY` and requires at least
one result. It prints redacted JSON only, so the observability acceptance output
can be attached to the release evidence bundle. Strict gates require metrics
schema `1`, metrics status, required metric count, metrics scrape hash, Grafana
dashboard status and hash, Prometheus rules status and hash, and Prometheus
query status; `missing_required_metrics` must be an empty list and
`required_metrics_sha256` must match the current required metric checklist.
Missing or contradictory required fields are reported as `invalid_evidence`.

Validate internal rollout sign-off before company-wide enablement:

```sh
scripts/internal_rollout_acceptance.py \
  --signoff /tmp/kagent-internal-rollout-signoff.json \
  >/tmp/kagent-internal-rollout.json
```

The validator requires TL, SRE, security, and business owner roles plus
provider smoke, staging acceptance, observability acceptance, runtime tool
policy, team access, trace retention, and rollback rehearsal checks. The JSON
output is redacted and suitable for `--internal-rollout-evidence`. It defaults
to the installed package version and `internal-production`; use
`--expected-version` and `--expected-environment` for explicit non-production
approval rehearsals. Strict gates require rollout metadata, version/environment
match flags, role/check booleans, approver role count,
`runtime_effective_tool_policy_sha256`, sign-off hash, and
`evidence_schema_version: "1"`; incomplete passing output is reported as
`invalid_evidence`.

Build the final approval bundle after all external evidence exists:

```sh
scripts/production_approval_bundle.sh --strict
```

Use `KAGENT_PROVIDER_SMOKE_EVIDENCE`,
`KAGENT_STAGING_ACCEPTANCE_EVIDENCE`,
`KAGENT_OBSERVABILITY_ACCEPTANCE_EVIDENCE`,
`KAGENT_INTERNAL_ROLLOUT_EVIDENCE`, and output-path environment
variables when release automation stores artifacts outside `/tmp`.
The bundle reports all missing external evidence files as `evidence_missing`
with their labels and paths. It rejects stale evidence older than 24 hours by
default and reports `evidence_stale` with the affected evidence labels. Override
`KAGENT_EVIDENCE_MAX_AGE_SECONDS` only when the release window is
explicitly approved.
If that freshness window is not a positive integer, the script reports
`evidence_max_age_invalid` as structured JSON.
If the release manifest from the standard gate is missing, the script reports
`release_manifest_missing` before running readiness or release-evidence checks.
The script accepts only the explicit `--strict` argument; unknown arguments fail
as structured `unknown_argument` JSON before evidence files are inspected.
The bundle also blocks external evidence files that accidentally contain
secret-like keys or values. In that case `failed_checks` includes
`evidence_secret_detected`, and `evidence_secret_findings` contains only the
evidence label, JSON path, and reason, never the secret value.
Full `http://` or `https://` values are treated as sensitive evidence values;
capture host-only fields such as `base_url_host` or `llm_base_url_host`
instead of provider or internal service base URLs.
When evidence files are present but fail strict semantic validation, the script
still writes readiness and release-evidence artifacts, prints a redacted stdout
JSON payload with `status: "blocked"` and `failed_checks`, and exits with
exit code 1. Preflight errors such as missing files or invalid arguments are
reported as stderr JSON before those artifacts are built.
`scripts/production_readiness_audit.py` runs the same scan, so evidence can be
rejected before the final release evidence bundle is built.
The successful bundle stdout includes redacted `evidence_files` metadata:
`path`, `file_name`, `size_bytes`, `sha256`, `age_seconds`, `max_age_seconds`,
and `fresh` for every external evidence file.

For provider-backed production promotion, run the static doctor gate before the
live smoke:

```sh
# KAGENT_LLM_BASE_URL, KAGENT_LLM_API_KEY, and KAGENT_LLM_MODEL
# must already be set in your shell or secret manager.
KAGENT_SERVICE_RUNTIME_MAX_ITERATIONS=2 \
kagent-doctor --production --require-runtime-provider \
  --trace-dir /tmp/kagent-traces
```

`--require-runtime-provider` fails without provider configuration using
`llm_base_url_required`, `llm_model_required`, or `llm_api_key_required`. It
also fails with `runtime_iterations_too_low` when
`KAGENT_SERVICE_RUNTIME_MAX_ITERATIONS` is lower than `2`, because a
single-iteration runtime cannot perform a corrective replan after an
observation.

## Continuous iteration

Use `scripts/continuous_iterate.sh` for long hardening loops:

```sh
scripts/continuous_iterate.sh 10800 60 /tmp/kagent.log /tmp/kagent.jsonl
```

Arguments are duration seconds, interval seconds, text log path, and JSONL
metrics path. Every iteration clears stale evaluator output before running the
check command, then appends a metrics record.

Custom check commands are supported:

```sh
KAGENT_CHECK_COMMAND="scripts/run_checks.sh" \
KAGENT_EVAL_FILE="/tmp/kagent-eval.json" \
scripts/continuous_iterate.sh 3600 60 /tmp/agent.log /tmp/agent.jsonl
```

## Metrics summary

Summarize a JSONL metrics file with:

```sh
.venv/bin/python -m kagent.ops.metrics /tmp/kagent.jsonl --output /tmp/metrics-summary.json --require-recent-health healthy
```

The `kagent.ops.metrics` report includes:

- `latest_status`
- `recent_health`
- `consecutive_passes`
- `failed_iterations`
- `latest_evaluator_passed`
- `latest_evaluator_failed`
- `latest_category_counts`
- `recommendations`

## Failure triage

Use this order when an iteration fails:

1. Check `latest_status` and `consecutive_passes`.
2. Use `recent_health` to separate current instability from old red windows.
3. If the latest run recovered, inspect the failed iteration numbers later.
4. If the latest run failed before a fresh evaluator report, inspect the text
   log around that iteration first.
5. If `latest_evaluator_failed` is non-zero, rerun the exact evaluator case
   with `--case`.
6. If `malformed_lines` is non-empty, inspect the JSONL producer or any manual
   edits to the metrics file.

Targeted evaluator examples:

```sh
.venv/bin/python -m kagent.eval.evaluator --list-cases
.venv/bin/python -m kagent.eval.evaluator --category recovery
.venv/bin/python -m kagent.eval.evaluator --case subtraction_tool_success --output /tmp/evaluator.json
.venv/bin/python -m kagent.eval.evaluator --fail-on-failure
```

## Artifact capture

The CLI writes JSON to stdout by default. Use `--output PATH` to also write the
same payload to an artifact file:

```sh
.venv/bin/python -m kagent.cli --deterministic "calculate 2 + 3" --summary --output /tmp/agent-summary.json
```

When paired with `--fail-on-agent-failure`, the output file is written before
the process exits `1`.
Use `--trace-dir PATH` with `--runtime` to persist service-compatible full traces
named by `run_id`. One-shot runs write one trace; interactive sessions write one
trace for each submitted goal. Persisted traces include `trace_path`, use
owner-only trace directory/file permissions through the shared trace store, and
are intended for local audit capture outside the HTTP service.

## Batch jobs

For repeatable job-style execution, write one JSON object per line with an `id`
and `goal`, then run the batch entry point:

```sh
printf '{"id":"sum","goal":"calculate 2 + 3"}\n' >/tmp/goals.jsonl
kagent-batch /tmp/goals.jsonl /tmp/results.jsonl --fail-on-failure
```

Malformed JSON and missing goals become failed output records. The batch keeps
processing later lines so one bad input does not stop the whole job. Add
`--fail-on-failure` when the scheduler should mark the overall batch failed.
Add `--full-trace` when operators need complete per-run traces for audit or
debugging.
Input records can include `max_steps` and `max_retries` when one job needs a
different budget from the defaults. These values must be JSON integers; strings,
floats, and booleans become failed batch records without stopping later jobs.

## Service operation

Start the local HTTP service with the installed console script:

```sh
kagent-serve --host 127.0.0.1 --port 8000
```

## Codex-style runtime configuration

The Codex-style runtime can use a fake provider for deterministic tests or an
OpenAI-compatible chat-completions endpoint for real planning. Configure real
planning with:

- `KAGENT_LLM_BASE_URL`: base URL such as `https://api.example.com/v1`.
- `KAGENT_LLM_API_KEY`: bearer token for the provider.
- `KAGENT_LLM_MODEL`: model name sent to the chat-completions API.
- `KAGENT_LLM_TIMEOUT_SECONDS`: provider request timeout, default `30`.
- `KAGENT_LLM_MAX_RETRIES`: retry count for transient 429 and 5xx
  provider errors, default `2`.
- `KAGENT_LLM_RETRY_BACKOFF_SECONDS`: fixed sleep between provider
  retry attempts, default `0.25`. Numeric provider `Retry-After` response
  headers take precedence for retryable HTTP failures.

Provider config snapshots expose only whether an API key is configured; the key
value is never returned in snapshots, traces, logs, metrics, or docs examples.
Keep the runtime identity boundary clear during operator testing: the product
identity is `kagent`, an automation agent running in the current CLI or service
process. Provider details stay behind the configuration boundary unless the
user explicitly asks about provider setup. Identity and deployment questions
should describe kagent and its local/service process boundary, not the
provider's model brand or hosting location. If the runtime corrects a
provider-branded identity
or deployment answer, responses include `final_answer_guardrail` with a
machine-readable reason and `original_answer_omitted=true`, so operators can
audit the correction without replaying the misleading provider answer.
The same guardrail surface records `unresolved_failure_boundary` when a
provider tries to return `final_answer` after the latest observation still
failed.
Use `kagent-doctor --production --require-runtime-provider` to
turn these settings into a release gate. Missing provider settings report
`llm_base_url_required`, `llm_model_required`, or `llm_api_key_required`; a
runtime budget lower than two iterations reports `runtime_iterations_too_low`.
Phase 1 exposes the runtime through Python APIs while the existing deterministic
HTTP `/run` surface remains stable. `POST /runtime/run` exposes the same
runtime over HTTP and reuses the service trust boundary for `Content-Type`,
request-size limits, auth, rate limiting, concurrency, and idempotency.
Use `max_iterations` to allow bounded plan-act-observe replanning. Runtime
responses include the latest `plan`, the full `plans` sequence, and accumulated
`observations`, which lets operators audit how the agent moved from each
planner output to each tool result. They also include `iteration_count`,
`max_iterations`, and `iteration_budget_remaining` so dashboards can alert on
runs that repeatedly spend most of their iteration budget. When a planner
returns `final_answer`, the runtime also returns that value as top-level
`answer` for clients that only need the final result. If a planner returns
actions and `final_answer` together, the runtime executes those actions once
and stops after they all succeed instead of spending the remaining iteration
budget on duplicate tool calls.
Tool input or execution failures are kept as observations and can drive another
planner iteration while `max_iterations` budget remains. For deterministic
replay of these correction loops over HTTP, send `plan_sequence` as an ordered
array of strict plans; it is mutually exclusive with `plan`.
`approved_action_ids` is accepted only with deterministic `plan` or
`plan_sequence` payloads, and every approved id must match an action id in that
replay payload. Live provider actions must first return `requires_approval`;
approve them through `POST /runtime/resume` so the service executes the
persisted pending action rather than pre-approving a future model choice.
If the latest observation is still failed, the runtime rejects an empty-action
`final_answer` and keeps the run failed, which prevents a provider from
claiming success after an unresolved tool or planner failure.
Planner parse failures and invalid plan shapes are kept as `invalid_plan`
observations. Provider request failures, provider timeouts, and malformed
provider responses are kept as `llm_provider_error` observations. Both can drive
another planner iteration while budget remains, but the split lets operators
separate prompt/schema drift from provider instability.
When the provider exposes diagnostics, runtime responses include
`llm_provider_request` with redacted request metadata: attempt count, retry count,
status, stream mode, duration, error type, HTTP status, and retryable reason
such as `model_unloaded`. It intentionally omits prompts, headers, API keys,
and provider response bodies.
Artifact observations are compacted before they are included in replanning
prompts: metadata is retained and `content_omitted=true` is set, but the
artifact body is not sent back to the provider. Persisted traces and artifact
lookup endpoints still retain the full artifact body for audit and downstream
delivery. Other long observation strings are compacted into `text_prefix`,
`original_chars`, and `truncated_chars` fields before provider calls.
Runtime responses include `prompt_observation_compaction`; check it when
debugging why a provider did not receive a full previous artifact or long text
output in the replanning prompt.
If a terminal tool failure exhausts the iteration budget, the final failed
observation's `error_code` and `error` are promoted to the top-level runtime
response and persisted status summary. Corrected failures stay in observations
only, so clients should branch on top-level `error_code` for final run failure
handling and inspect observations for recovery history.
Each strict plan must use unique action IDs within that plan. Duplicate IDs are
rejected as `invalid_plan` so approval and resume workflows cannot confuse two
different actions. Action IDs and tool names must not contain surrounding
whitespace; those plans are also rejected as `invalid_plan` to keep approval
and trace correlation unambiguous.
Use `depends_on` when an action depends on the output of earlier actions. Each
dependency must reference a prior action ID in the same plan; unknown, later,
duplicate, or malformed dependencies fail as `invalid_plan`.
Policy and executor events for dependent actions include `depends_on` plus
compact `dependency_statuses`, allowing trace timelines to explain dependency
state without exposing dependency outputs.
Unknown top-level plan fields and unknown action fields also fail as
`invalid_plan`; use this when triaging model schema drift or prompt regressions.
Strict plan action lists are capped by `MAX_PLAN_ACTIONS`; oversized plans fail
as `invalid_plan` before any tool execution, protecting traces, approvals, and
executor capacity from one unbounded planner response.
Action `reason` fields and planner `final_answer` are capped by
`MAX_ACTION_REASON_CHARS` and `MAX_PLAN_FINAL_ANSWER_CHARS`; oversized plan
metadata fails as `invalid_plan`. Long-form reports, decisions, data, and
messages should be returned through the bounded `artifact` tool.
`KAGENT_SERVICE_RUNTIME_MAX_ITERATIONS` caps accepted
`max_iterations` for `/runtime/run` and `/runtime/resume`; requests above that
cap return `400 invalid_request_body` before the provider is called.
When a runtime action is blocked by policy, the response status is
`requires_approval` and includes `pending_approval`. Resubmit the same request
with `approved_action_ids` containing only the reviewed action IDs to continue
without changing the default tool policy. Approved IDs must be unique, non-empty action IDs without surrounding whitespace.
Runtime responses and compact persisted summaries include `approved_action_count`
and `approved_action_ids` as consumed approval audit metadata, reporting only
approval IDs that actually bypassed policy.
They also include `approved_tool_counts` so dashboards can separate approval
consumption by policy-gated tool.
If trace persistence is enabled, `POST /runtime/resume` can resume from a
persisted pending run by `run_id` and `approved_action_ids`; resume accepts
only the pending approval action from that trace. Resume starts at that action
and preserves every later action from the persisted plan; it does not replay the
completed action prefix. Dependencies on completed prefix actions are treated as
satisfied and removed from the resumable plan, while dependencies between the
remaining actions are preserved. The persisted `pending_approval` payload must
exactly match the full plan action with the same ID before execution resumes.
Only that matching pending action is approved: every later sensitive action is
checked against policy again and returns `requires_approval` when another human
decision is required. Resumed responses include `resumed_from_run_id` and a new
`trace_path`. Operator/admin resumes keep the original run owner in
`auth_subject` and record the approver in `resumed_by_auth_subject`,
`approved_by_auth_subject`, and `approved_at`.
`/runtime/run trace persistence` uses `KAGENT_SERVICE_TRACE_DIR` too:
persisted runtime responses include `trace_path`, HTTP responses include
`X-Trace-Path`, and write failures return `trace_persistence_failed`. Runtime
trace files include `trace_type: "codex_runtime"`. `GET /runtime/runs`,
`GET /runtime/runs/{run_id}`, and `POST /runtime/resume` require that marker
and treat other JSON trace files as not found, which keeps older deterministic
`/run` artifacts from appearing in runtime dashboards or approval workflows.
Runtime status and list responses derive `trace_path` from the configured trace
store path and `run_id`; they do not trust a `trace_path` value embedded inside
the trace JSON.
`GET /runtime/runs` skips unreadable trace files so one corrupted artifact does
not break dashboards; direct status or resume requests for an unreadable trace
return `trace_read_failed`.

Run the deployment self-check before or after service startup:

```sh
kagent-doctor --trace-dir /tmp/kagent-traces
```

The doctor command returns JSON with `status`, `version`, readiness checks,
redacted runtime configuration, registered tool count, and a `runtime_policy`
summary containing the default subject's effective policy source, allowed tool
count, approval-required tool count, and `effective_tool_policy_sha256`. It exits `0` when
all checks are ready and exits `1` when any readiness or required policy check
fails. Use `--require-auth` in release automation for externally exposed
deployments so missing bearer auth fails the self-check. `--require-auth` rejects
tokens that cannot be sent as safe HTTP header values with `auth_token_unsafe`.
`--require-auth` rejects placeholder tokens with `auth_token_placeholder`.
Use `--production` for stricter release gates that also require diagnostic
endpoint protection, trace persistence, per-client rate limiting, and bounded
run concurrency. Production gates require bearer tokens to be at least 16
characters and reject common placeholder values such as
`replace-with-a-long-random-token` with `auth_token_placeholder`. Tokens that
cannot be sent as safe HTTP header values fail with `auth_token_unsafe`.
Use `--production --require-runtime-provider` in provider-backed deployments so
missing LLM base URL, model, API key, or insufficient runtime iteration budget
cannot pass release automation.
If service environment variables contain invalid values, service and doctor
CLIs exit with an argparse configuration error without a Python traceback. The
standard gate exercises this invalid environment configuration path for both
service and doctor entrypoints so initContainer and CI failures remain
readable.

Check process liveness:

```sh
curl -s http://127.0.0.1:8000/health
curl -I http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/ready
curl -I http://127.0.0.1:8000/ready
```

Inspect runtime metadata:

```sh
curl -s http://127.0.0.1:8000/config
curl -s http://127.0.0.1:8000/version
curl -s http://127.0.0.1:8000/tools
curl -s http://127.0.0.1:8000/runtime/tools
curl -s http://127.0.0.1:8000/runtime/policy
curl -s 'http://127.0.0.1:8000/runtime/approvals?tool=http_request'
curl -s 'http://127.0.0.1:8000/runtime/approvals/summary?tool=http_request'
curl -s 'http://127.0.0.1:8000/runtime/runs?limit=20'
curl -s 'http://127.0.0.1:8000/runtime/runs/summary?has_pending_approval=true'
curl -s http://127.0.0.1:8000/runtime/runs/<run-id>
curl -s http://127.0.0.1:8000/runtime/runs/<run-id>/timeline
curl -s http://127.0.0.1:8000/runtime/runs/<run-id>/artifacts
curl -s http://127.0.0.1:8000/runtime/runs/<run-id>/artifacts/<artifact-id>
curl -s -X POST http://127.0.0.1:8000/runtime/runs/<run-id>/cancel \
  -H 'Content-Type: application/json' \
  -d '{"reason":"stale approval cleanup"}'
curl -s http://127.0.0.1:8000/metrics
curl -s http://127.0.0.1:8000/metrics.prom
curl -s http://127.0.0.1:8000/openapi.json
curl -i -X OPTIONS http://127.0.0.1:8000/run
curl -s -X POST http://127.0.0.1:8000/runtime/run \
  -H 'Content-Type: application/json' \
  -d '{"goal":"capture hello","max_iterations":1,"plan":{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"}}]}}'
.venv/bin/python -m kagent.cli "capture hello" \
  --runtime-plan '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"},"reason":"capture"}],"final_answer":"captured"}'
.venv/bin/python -m kagent.cli
.venv/bin/python -m kagent.cli --interactive-json
.venv/bin/python -m kagent.cli "create README" \
  --runtime-plan '{"actions":[{"id":"step-1","tool":"apply_patch","input":{"patch":"*** Begin Patch\n*** Add File: README.agent.md\n+# Agent file\n+\n+Created through apply_patch.\n*** End Patch\n"},"reason":"create workspace file"}],"final_answer":"created"}'
curl -s 'http://127.0.0.1:8000/runtime/runs?tag=internal-smoke&limit=20'
curl -s 'http://127.0.0.1:8000/runtime/runs/summary?metadata_key=workflow&metadata_value=internal'
curl -s -X POST http://127.0.0.1:8000/runtime/resume \
  -H 'Content-Type: application/json' \
  -d '{"run_id":"<pending-run-id>","approved_action_ids":["step-1"]}'
```

The installed `kagent` command opens the React/Ink terminal client by default.
It launches one private Python stdio runtime, displays a compact `◆ kagent`
identity, keeps the prompt visible below the transcript, and renders only
user-facing answers, command results, permissions, and concise lifecycle
status. Internal tool identifiers and raw JSON traces are not shown in the
normal transcript.
The private stdio runtime enables final-answer streaming. Only plans with an
empty action list stream answer deltas, so executable plans never display a
premature final answer before their actions complete.

Run `kagent "goal"` for a one-shot runtime turn. Use `--deterministic` only for
the legacy, LLM-free LangGraph regression path.

The input editor is grapheme-aware, so long Chinese text, emoji, pasted text,
Backspace, forward Delete, Home, End, and history navigation remain usable when
the prompt wraps. PageUp/PageDown page through the bounded visible transcript;
new messages return the view to the latest page. Multiline and bracketed paste
preserve line boundaries. Shift+Enter, Option+Enter, and Ctrl+J insert a line
break; Enter submits the prompt. Typing `/` opens the command palette; Up/Down
changes the selection and Tab completes it. The layout budgets wrapped prompt
rows and remains responsive down to a 40-column terminal. Ctrl-C during a run
requests cooperative cancellation without discarding the Python session;
Ctrl-C at a permission prompt denies the action; Ctrl-C while idle exits.
While a run is active, the prompt remains editable. Enter sends a bounded
latest-wins steering instruction, which is applied only after a planner or tool
boundary and can add a bounded replanning iteration. Escape requests the same
cooperative cancellation as Ctrl-C. Steering text is not persisted separately
and is never injected during an active tool call.

Presentable tool outcomes use a strict server-side projection before reaching
the terminal. The projection exposes only a redacted title, short detail, and
at most 4000 characters of optional content; tool names, action IDs, inputs,
artifact IDs, and raw trace objects remain hidden. Ctrl+O toggles the latest
expandable result. Read/list/note operations and failed internal attempts stay
out of the normal transcript.

Virtual workspace rollback is optimistic and approval-gated. Inspect
`workspace_history` or `workspace_diff`, then call `workspace_restore` with the
selected revision ID, revision SHA-256, and current asset SHA-256. A mismatched
current or revision SHA rejects the restore without writing; a successful
restore saves the displaced content as a new revision so operators can redo it.
Kind-directory advisory locks serialize cooperating Kagent processes. Do not
allow unrelated same-UID processes to mutate the owner-only runtime workspace;
use a dedicated service account or container when that boundary is unacceptable.

External effects are permission-gated in the Ink client. The prompt shows a
human title and target, accepts `y` to allow, `n` to deny, and `d` to reveal the
reason, without exposing the internal tool name. If the Python child crashes,
the client reports a concise failure and attempts one controlled restart while
preserving the visible transcript. Repeated crashes stop recovery instead of
looping indefinitely.

Use `kagent --classic` or `.venv/bin/python -m kagent.cli` for the classic
Python terminal and its detailed operator commands such as `/json`, `/compact`,
`/last`, `/trace`, `/save-trace PATH`, and `/doctor`. Both terminal paths share
the same provider config, runtime policy, session commands, and persisted
memory. Unknown slash commands and invalid arguments are handled locally and
are not sent to the model as runtime goals.

The default turn budget is three planning iterations; add
`--max-iterations N` only when a workflow needs a
different budget. TTY sessions persist compact memory across shell restarts by
default at `${XDG_STATE_HOME:-~/.local/state}/kagent/session-memory.json`;
piped interactive runs keep memory in-process and do not write a default file.
Add `--session-memory PATH` for an explicit memory file. Set
`KAGENT_SESSION_MEMORY_PATH` to override the default location, or set it to an
empty value to disable default persistence for TTY sessions. The memory file is
loaded and written owner-only; parent directories are created or tightened to
`0700`, symlink memory files, symlink parent directories, and existing files
with group or world permissions are rejected before parsing, and `/clear` also
clears the persisted file. The CLI tightens the parent directory on both memory
load and save paths. Before reusing session memory in later turns or
writing it to disk, the CLI redacts common API keys, bearer tokens, and URL
credentials so accidental provider or service secrets are not sent back to the
model or preserved in the memory file. Session memory uses a v2 compact layout:
older turns are folded into a bounded summary, durable facts, and open items,
while recent turns remain available verbatim for follow-up resolution.

TTY prompt history is persisted separately at
`${XDG_STATE_HOME:-~/.local/state}/kagent/history`, with the same owner-only
directory and file permissions. Set `KAGENT_HISTORY_PATH` to override that
location, or set it to an empty value to disable persisted prompt history.
Prompt history is redacted before writes and again while loading, so common API
keys, bearer tokens, and URL credentials are not replayed through history.
Use `/reset` before switching sensitive tasks when both remembered turns and
prompt history should be cleared together.

`/openapi.json` includes named schemas for production integration, including
`RunRequest`, `RunResponse`, readiness, config, tools, version, metrics, and
structured error responses. It also declares common response headers such as
`X-Request-ID`, `Cache-Control`, `X-Content-Type-Options`,
`Referrer-Policy`, `Content-Security-Policy`, and `X-Frame-Options`, so
generated clients and gateway checks can validate the same contract the
service emits. `ReadinessResponse` includes a structured `failed_checks` array
so probes and release automation can identify failing dependencies without
parsing human-readable check strings.
`/config`, `/metrics`, and Prometheus `kagent_build_info` also
expose `security_response_headers` plus the current header policy values such
as `content_security_policy_header` and `x_frame_options_header`, so rollout
audits can compare the live runtime against gateway and OpenAPI expectations.
The same surfaces expose trace permission policy fields
(`trace_directory_permissions`, `trace_file_permissions`, and
`trace_probe_file_permissions`) so rollout checks can verify trace storage
hardening without inspecting the filesystem on every pod. The OpenAPI
`ConfigResponse` and `MetricsResponse` schemas also declare those fields for
generated clients and gateway contract checks.
They also expose redacted LLM provider state through `llm_provider`,
`llm_provider_display_name`, `llm_base_url`, `llm_base_url_configured`,
`llm_model`, `llm_api_key_configured`, and `llm_timeout_seconds`, plus retry
audit fields `llm_max_retries` and `llm_retry_backoff_seconds`. Embedding
provider diagnostics use the same redacted pattern: `embedding_provider`,
`embedding_base_url`, `embedding_base_url_configured`, `embedding_model`, and
`embedding_api_key_configured`. Operational rule: raw API keys and raw provider endpoints are never exposed.
Operators should use configured/not-configured fields only to confirm whether
endpoints and keys are present.
Probe and integration endpoints such as `HEAD /health`, `HEAD /ready`,
`OPTIONS /run`, and `GET /metrics.prom` also declare response headers and
content types in the OpenAPI document.
Every OpenAPI operation also has a stable `operationId`, such as `postRun`,
for generated clients and gateway contract checks.
Use those schema names for generated clients, contract review, and downstream
smoke tests.
Use `GET /runtime/graph` to inspect the deployed LangGraph runtime topology and
confirm the service is running the expected `prepare -> runtime_loop -> finalize`
graph shell. Use `GET /runtime/tools` to inspect Codex-style runtime tool names,
descriptions, `input_schema`, `output_schema`, and `timeout_seconds` values
before generating or validating plans.
Runtime run detail responses include `graph_phase_count`; the expected value is
`3` for the current graph shell. If it is missing or lower than expected, inspect
the full trace for graph startup/finalization failures before debugging planner
or tool behavior. The `/runtime/runs/summary` endpoint aggregates
`graph_phase_count` across the filtered fleet, which is useful for checking
whether new graph-phase instrumentation is present across recent internal runs.
It also returns `graph_phase_node_counts` so operators can compare
`prepare`, `runtime_loop`, and `finalize` coverage directly and identify which
phase is missing from incomplete traces.
Set `KAGENT_SERVICE_RUNTIME_ALLOWED_TOOLS` to a comma-separated
allowlist when a deployment should execute only selected runtime tools without
human approval. Leave it empty for the default policy. Unknown tool names fail
service and doctor configuration before startup, and `/config`, `/metrics`,
and Prometheus `kagent_build_info` expose the active
`runtime_allowed_tools` value as non-secret audit metadata.
Set `KAGENT_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT` to a JSON object
when different internal teams need different direct-execution boundaries. Keys
are authenticated `auth_subject` values, and values are comma-separated tool
lists or arrays of tool names. Matching subject entries override the global
allowlist; unmatched subjects fall back to the global or default policy.
`/config`, `/metrics`, and Prometheus build info expose
`runtime_allowed_tools_by_subject_count`, not the raw bearer tokens.
Use `GET /runtime/policy` before onboarding a team or changing tool policy.
Subject tokens see only their own `effective_allowed_tools` and matching
subject override; the primary token sees the default policy, global allowlist,
and all subject overrides. The response includes subject identifiers and tool
names but never bearer tokens. For operator consoles and approval bots, prefer
the `effective_tool_policy` array: it lists every registered runtime tool with
the current subject's `allowed` and `approval_required` flags after policy
precedence is resolved.
Those schemas include execution-enforced constraints such as `required`, `enum`,
`minItems`, `maxItems`, `minLength`, and `maxLength`, so clients and planners can
reject malformed or oversized tool arguments before a run starts. Output
schemas document structured observation shapes for generated clients and
downstream automation. Number
schemas also support `minimum` and `maximum` for bounded scores and weights,
and boolean schemas support pass/fail rubric fields.
The built-in direct-execution local tools are `artifact`, `decision_matrix`,
`note`, `rubric_score`, `task_list`, and `transform_text`.
Tools that affect the local desktop, network, or shell require approval by
default: `open_app`, `open_url`, `http_request`, and `shell_command`.
In the terminal agent, approval prompts accept `d` to print the pending action
JSON before the operator answers `y` to approve or `n` to skip.
`http_request` performs approved HTTP GET fetches with bounded response bytes
and returns response metadata plus text. `open_app` opens local macOS
applications by app name and rejects paths or shell-like input. `open_url` is
the separate local browser-opening tool for `http://` and `https://` URLs. It
uses Google Chrome automation first, falls back to macOS `open`, and does not
fetch page content into the runtime trace. `shell_command` executes only after
policy approval, uses workspace-confined cwd, strips host secrets by replacing
the inherited environment with a minimal sandbox environment, rejects
network-capable shell clients and common inline interpreter network APIs, and
runs through an OS-aware sandbox backend. macOS uses Seatbelt via
`sandbox-exec` when available, Linux uses `bubblewrap` when available, and
other platforms or missing native tools fall back to a declared soft sandbox.
The observation output includes `sandbox.backend`, `sandbox.enforced`,
`sandbox.filesystem`, `sandbox.network`, and `sandbox.env_policy`. Approval does
not bypass SSRF
protection: `http_request` rejects private, loopback, and link-local URL
targets before opening a socket, including `localhost`, literal private IPs,
link-local metadata addresses, and hostnames that resolve to blocked
addresses. It does not follow redirects; 3xx responses are returned as
observations so a public URL cannot silently redirect execution to a blocked
target. Both `http_request` and `open_url` reject url credentials and
secret-like query or fragment fields, so userinfo tokens, bearer tokens, or
passwords cannot be copied into runtime observations or traces. Runtime result
payloads also redact secret-like URL query and fragment values, plain API-key
strings, and bearer-token strings before CLI output, HTTP responses, or
persisted traces expose `plan`, `plans`, `observations`, shell command output,
or `pending_approval` fields.
`artifact` records
structured reports, plans, decisions, data, or messages with a stable
`artifact_id`, normalized tags, content format, and byte count.
Workspace file tools keep execution local: `read_file` and `apply_patch` resolve
paths inside the current workspace and reject symlink paths, while `list_files`
skips symlink entries so external file metadata is not exposed through directory
listings. Runtime virtual-workspace tools `workspace_write`, `workspace_read`,
`workspace_list`, `workspace_search`, `workspace_history`, and `workspace_diff`
keep generated reports, logs, policies, and memory assets under the configured
runtime workspace with bounded reads, bounded listings, bounded text search,
overwrite history, and unified change review. `workspace_restore` restores a
selected revision only when its expected current and revision SHA-256 values
still match, records the displaced content for redo, and requires approval by
default. `apply_patch`
supports audited add, update, move, and delete
operations; move operations use `*** Move to: PATH` and report
`operation=move`, changed-file `path`, `previous_path`, `bytes`, and `sha256`
in observations. Multi-file patches use a workspace advisory lock, same-directory
atomic replacement, and compensating rollback so a failed commit does not leave
partially updated files. Each successful patch records an owner-only checkpoint
under `${KAGENT_PATCH_STATE_DIR:-${XDG_STATE_HOME:-~/.local/state}/kagent/patches}`.
Checkpoint manifests are authenticated with a generated owner-only HMAC key.
If a process exits during a multi-file commit, the next patch history, apply, or
revert operation detects the prepared journal and restores every file to its
recorded before state; recovery stops without writing if any file has diverged.
Use `patch_history` to inspect checkpoint IDs and affected paths, then
`revert_patch` with those exact reviewed paths. Revert is approval-gated, rejects
current SHA conflicts and symlink substitution, and records a new checkpoint so
the same flow can redo the change.
`decision_matrix` ranks options with weighted criteria for structured tradeoff
decisions, `rubric_score` returns score percentages, failed criteria, and
blocking failures for structured self-review, while `task_list` returns
normalized task items plus status counts for planning and handoff workflows.
`task_transition` validates lifecycle events including `fail`, so operators can
distinguish failed work from blocked, cancelled, or completed work in structured
task artifacts.
Runtime tool execution enforces the declared schema subset before calling
handlers, so undeclared fields, missing required values, invalid enum values,
malformed nested items, and non-numeric `number` fields return
`invalid_tool_input`. Handler outputs are validated against `output_schema`;
tool contract violations return `invalid_tool_output` and can trigger bounded
replanning while iteration budget remains. Slow handlers that exceed their
declared `timeout_seconds` return `tool_execution_timeout`, preserving the
overall runtime run instead of letting one tool block the planner loop.
Runtime observations and planner, policy, and executor events include
action-level timing (`started_at`, `completed_at`, and `duration_seconds`),
which lets operators separate slow provider calls, policy checks, and tool calls
inside one run before comparing them with service-level agent run duration
metrics. Runtime responses and compact persisted run summaries also include
run-level duration as `duration_seconds`, which is the first field to sort by
when triaging slow `/runtime/run` or `/runtime/resume` traffic.
Use `GET /runtime/runs` to list recent persisted runtime summaries; `limit`
defaults to `50`, is bounded to `1..100`, and is applied after filtering for
`trace_type: "codex_runtime"`. It also supports `auth_subject=team-a`,
`status=cancelled`, `status=failed`,
`tool=artifact`, `error_code=invalid_tool_input`,
`latest_failed_error_code=invalid_tool_input`,
	`latest_failed_action_id=fetch-site`, `latest_failed_tool=planner`,
	`iteration_budget_remaining=0`,
	`llm_provider_status=failed`, `llm_provider_error_type=http_error`,
	`llm_provider_http_status=429`,
	`llm_provider_retryable_reason=model_unloaded`,
	`has_llm_provider_retries=true`,
	`artifact_kind=report`,
`artifact_format=markdown`, `artifact_tag=release`, `has_artifacts=true`, and
`tag=internal-smoke`, `metadata_key=workflow`, `metadata_value=internal`,
`has_errors=true`, `has_failures=true`, `has_approvals=true`,
`has_pending_approval=true`,
`has_final_answer_guardrail=true`,
`final_answer_guardrail_reason=runtime_identity_boundary`,
`approved_action_id=step-1`, and `resumed_from_run_id=pending-run`,
`pending_approval_tool=http_request`, and `pending_approval_action_id=step-1`
filters, with `limit` applied after all
filters. Use `auth_subject=team-a` to answer who initiated a persisted runtime run
without reading full traces or exposing bearer tokens. When `has_more` is `true`, pass `next_cursor` back as `cursor` with
the same filters to continue scanning older matching runs. Use
`tag=internal-smoke` or `metadata_key=workflow&metadata_value=internal` to
partition internal workflows without creating high-cardinality metrics labels.
Runtime metadata is limited to small non-secret string maps; keys that look like
tokens, passwords, API keys, or authorization headers are rejected before the
run starts. Values that look like API keys, bearer tokens, or URLs with embedded
credentials are also rejected, so metadata remains safe to expose in compact
status and filtering surfaces. Compact summaries expose `metadata_keys` and
`tags` but never accept arbitrary nested metadata objects. CLI runtime runs use
the same validation via repeated `--tag TAG` and `--metadata KEY=VALUE` flags,
and interactive sessions attach those labels to each submitted goal.
	Use
	`llm_provider_status=failed` to list runs whose latest provider request failed,
	`llm_provider_error_type=http_error` or `llm_provider_http_status=429` to isolate
	rate-limit and gateway clusters,
	`llm_provider_retryable_reason=model_unloaded` to isolate provider model unload
	events, and `has_llm_provider_retries=true` to find runs that consumed retry
	budget before completing or failing. These filters use redacted scalar
	diagnostics only and never expose prompts, headers, API keys, provider base
	URLs, or response bodies.
Use
`has_errors=true` to find runs with observation-level
`error_code_counts` or a run-level `error_code` before narrowing to a specific
error code. Use `has_failures=true` to find runs with failed observations,
excluding run-level-only errors. Use `has_approvals=true` to find runs whose
compact approval audit
	metadata includes approved actions, then `approved_action_id=step-1` to trace
	one reviewed action across runs. Use `resumed_from_run_id=pending-run` to find
	resume attempts for a persisted pending run. Use `resumed_by_auth_subject` to
	separate the run owner from the subject that performed the resume, for example
	`resumed_by_auth_subject=default` for primary-token admin resumes. Use
	`approved_by_auth_subject=default` to filter the same runs by approver audit
	metadata, and inspect `approved_at` to see when the approval was consumed. Use
	`pending_approval_tool=http_request` or `pending_approval_action_id=step-1` to
partition active approval queues without opening full traces; lists omit full `pending_approval` payloads, and `GET /runtime/runs/{run_id}` remains the
approval detail endpoint. Invalid filter values, including a blank
`auth_subject`, return
`400 invalid_request_body`. The
endpoint also skips unreadable trace files instead of failing the whole list.
Use `lifecycle_state=waiting_approval`, `lifecycle_state=running`, or
`lifecycle_state=failed` when dashboards need operator-facing phase filters
instead of raw terminal status filters.
When diagnostic endpoints are protected, the primary token is treated as an
operator/admin diagnostic token and can list all persisted runtime traces.
Tokens from
`KAGENT_SERVICE_AUTH_TOKENS` are subject-scoped: `team-a` can list only
runtime traces whose persisted `auth_subject` is `team-a`, and cross-subject run IDs are hidden as `404 not_found`.
Use `GET /runtime/runs/summary` to build a lightweight operations dashboard or
approval queue badge without loading individual runs. It applies subject
	visibility and compact list filters, then returns `run_count`, `status_counts`,
	`lifecycle_state_counts`, `runtime_engine_counts`, `auth_subject_counts`,
	`approved_by_auth_subject_counts`, `tool_counts`, `error_code_counts`,
	`failed_observation_count`, `llm_provider_request_count`,
	`llm_provider_request_attempt_count`, `llm_provider_request_retry_count`,
	`llm_provider_request_status_counts`,
	`llm_provider_request_error_type_counts`,
	`llm_provider_request_http_status_counts`,
	`llm_provider_request_retryable_reason_counts`, `approval_required_count`,
	`pending_approval_count`, `artifact_count`, `artifact_total_bytes`,
	`tag_counts`, and `metadata_key_counts`.
Subject tokens see only their own runtime traces; the primary token can inspect
the full internal aggregate.
Use `GET /runtime/approvals` for a compact pending approval queue. The response
omits `pending_approval.input` and exposes only routing fields such as
`run_id`, `auth_subject`, `goal`, `trace_path`,
`pending_approval_action_id`, `pending_approval_tool`, and
`pending_age_seconds`, so internal approval UIs and bots can route work without
leaking tool inputs. Add `min_pending_age_seconds=3600` to find approvals that
have been waiting for at least an hour before cancelling or escalating them.
Use `GET /runtime/approvals/summary` for dashboard badges and alerts over that
same queue. It returns `pending_approval_count`, `stale_pending_count`,
`max_pending_age_seconds`, `auth_subject_counts`, and `tool_counts`, applies
subject visibility plus `auth_subject`, `tool`, and
`min_pending_age_seconds=3600` filters, and does not return trace bodies or
pending tool inputs.
Use `POST /runtime/runs/{run_id}/cancel` to clean up stale non-terminal
runtime runs, especially pending approvals that should no longer be resumed.
The endpoint removes `pending_approval`, marks the trace `cancelled`, appends a
compact control event, and exposes `cancelled_by_auth_subject`,
`cancelled_at`, and optional `cancel_reason` on compact run status responses.
The optional reason is a short operator-visible audit field capped at 500
characters; put longer investigation notes in the external incident or rollout
record and reference that record from the reason.
Terminal `done`, `failed`, or already `cancelled` runs return
`409 invalid_request_body` so operators do not accidentally rewrite historical
outcomes.
`Idempotency-Key` retries for this endpoint are scoped to the concrete
`run_id`, so retrying one cancellation can replay safely without blocking or
replaying cancellation of a different run.

For a multi-replica service, cancellation is valid only when every replica
mounts the same `KAGENT_SERVICE_TRACE_DIR`. The request can land on a non-owner
replica: that replica persists a cancellation signal, and the owner worker
cooperatively observes it at its next cancellation boundary. Per-run file locks
serialize the cancel writer, owner completion, failure persistence, and startup
recovery. Once the shared trace reaches terminal `cancelled`, a late worker
result must not replace it with `done` or `failed`.

After a cross-replica cancel returns success, poll
`GET /runtime/runs/{run_id}` until it reports `status=cancelled`; do not use the
HTTP response alone as proof that an in-flight provider or tool call has already
returned. Expected convergence is bounded by the next cooperative cancellation
check plus the active provider/tool timeout. Record the `run_id`, request time,
owner `runtime_instance_id`, `cancelled_at`, and `cancel_reason` in the incident
or change record.
Use `GET /runtime/runs/{run_id}` to inspect a persisted runtime run status
summary without returning full trace internals; `auth_subject` is included when
the run was started by a named internal bearer token, while raw tokens are never
persisted. Dynamic run IDs are normalized
to `/runtime/runs/{run_id}` in request path metrics, cancel requests are
normalized to `/runtime/runs/{run_id}/cancel`, while artifact lookups are
normalized to `/runtime/runs/{run_id}/artifacts/{artifact_id}`. Runtime status
summaries include `iteration_count`, `max_iterations`,
`iteration_budget_remaining`, `plan_count`, `observation_count`, and
`event_count` plus derived `lifecycle_state` for low-cardinality dashboard triage without exposing full event
or observation bodies. When a run is waiting for approval, the
pending approval detail schema is limited to `id`, `tool`, `input`, and optional `reason`;
unknown action fields are omitted while `pending_approval.input` remains
available for operator review before resume. They also include
`failed_observation_count`, `approval_required_count`,
`planner_failure_count`, `tool_failure_count`, `latest_failed_action_id`,
`latest_failed_tool`, `latest_failed_error_code`, `error_code_counts`,
`latest_plan_action_count`, `latest_plan_action_ids`, `dependency_edge_count`,
	`tool_names`, `final_answer_guardrail`, `artifact_kinds`, `artifact_formats`, `artifact_tags`,
	`artifact_total_bytes`, `artifact_bytes_by_kind`,
	`llm_provider_request_status`, `llm_provider_request_attempt_count`,
	`llm_provider_request_retry_count`, `llm_provider_request_error_type`,
	`llm_provider_request_http_status`, `llm_provider_request_retryable_reason`, and
	`llm_provider_request_duration_seconds` so
	operators can separate planner failures, tool failures, approval queues,
	error-code clusters, latest plan shape, dependency-heavy plans, tool-specific
	clusters, final-answer guardrail corrections, artifact categories, artifact
	formats, artifact tags, artifact byte volume, provider retry pressure, and
	provider HTTP/error-type/retry-reason clusters before opening full traces.
summary scalar metadata is limited to strings and non-boolean numbers for run,
plan, observation, and artifact index fields; nested objects and arrays are
omitted from dashboard summaries instead of being stringified.
optional status fields such as answer, error, resume, cancel, timestamp, and
duration metadata follow the same scalar-only rule; malformed object values are
omitted from status and list responses.
guardrail metadata is limited to the string fields `applied`, `reason`, and
`original_answer_omitted`; malformed nested values are omitted before status,
list, summary, or metrics aggregation.
	Use `GET /runtime/runs/summary` to aggregate
	`final_answer_guardrail_applied_count` and
`final_answer_guardrail_reason_counts` across visible traces without exposing
the original provider answer that triggered the correction. Add
`has_final_answer_guardrail=true` or
`final_answer_guardrail_reason=runtime_identity_boundary` to the same endpoint
	when an operations dashboard needs to aggregate only corrected runs.
	The same summary endpoint aggregates provider diagnostics through
	`llm_provider_request_status_counts`,
	`llm_provider_request_error_type_counts`,
	`llm_provider_request_http_status_counts`, and
	`llm_provider_request_retryable_reason_counts`; add
	`llm_provider_status=failed`, `llm_provider_error_type=http_error`,
	`llm_provider_retryable_reason=model_unloaded`, or
	`has_llm_provider_retries=true` when a dashboard should focus on provider-side
	instability instead of tool or policy failures.
	Artifact-producing runs also
expose `artifact_count` and `artifact_ids`, which downstream workflows can use
to discover non-coding deliverables without loading full observation bodies. Use
`GET /runtime/runs/{run_id}/timeline` for a compact timeline of planner,
policy, executor, and observation status fields without full inputs or outputs.
timeline scalar metadata is limited to strings and non-boolean numbers; nested
objects, arrays, and booleans are omitted so malformed trace files cannot leak
object representations into operator timelines.
child endpoint run_id values for timeline, artifact lists, and artifact detail
responses are derived from the requested URL and trace store path, not from
mutable trace JSON metadata.
Timeline responses also include redacted `progress_events` and
`progress_event_count`, which are safe for operations dashboards because they
exclude tool inputs, patch bodies, and observation outputs. Each progress event
includes `run_id`, so streaming sinks and timeline UIs can correlate planner,
policy, tool, and completion events without copying context from the outer
response. If an in-process progress event sink fails, the runtime continues the
run and reports `progress_event_sink_failure_count` in the response for
operator triage; persisted runtime status, list, and summary responses surface
the same count so dashboards can alert on broken event delivery without opening
full traces. Runtime hook callback failures are isolated the same way through
`hook_failure_count` and `kagent_runtime_hook_failures_total`, so audit,
middleware, or notification hook outages stay visible without crashing the
primary run.
Use
`GET /runtime/runs/{run_id}/artifacts` to list artifact metadata without
content before selecting a specific deliverable. The listing normalizes tags to
non-empty string tags only, so malformed trace metadata cannot leak nested
objects through operator dashboards. It also accepts only scalar metadata fields
that are strings, such as artifact ID, title, kind, format, action ID, and tool name;
malformed object values are returned as empty strings or skipped when the
artifact ID itself is invalid. Byte counts are returned only when they parse as
non-negative integer values. Use
`GET /runtime/runs/{run_id}/artifacts/{artifact_id}` to fetch one persisted
artifact body by ID without returning the full trace; the response includes
`trace_path` for audit correlation. The artifact detail schema is fixed to
artifact ID, title, kind, format, content, string tags, and byte count; unknown
or malformed metadata fields are omitted instead of being forwarded from trace
JSON. If the target trace cannot be decoded or read, the endpoint returns
`500 trace_read_failed` without exposing local file paths or parser details.

Use `agent_runs_by_status`, `average_agent_run_duration_seconds`, and
`max_agent_run_duration_seconds` to distinguish healthy agent completions from
agent exceptions or timeouts. Prometheus scrapes expose the same signals through
`kagent_runs_total`, `kagent_run_status_total`,
and the agent run duration gauges. Use
`kagent_agent_run_duration_seconds_bucket`,
`kagent_agent_run_duration_seconds_count`, and
`kagent_agent_run_duration_seconds_sum` for histogram queries
over internal agent execution latency. Compare this histogram with the HTTP
request duration histogram to separate agent work from HTTP transport,
auth, rate-limit, and trace persistence overhead.
Use `requests_by_method` and
`kagent_requests_by_method_total` to separate probe, diagnostic,
preflight, and `/run` traffic by HTTP method during rollout or gateway debugging.
Known HTTP methods are normalized to uppercase, and unknown HTTP methods are
aggregated under `__unknown__` to keep method metrics bounded while access logs
still keep the original method for request-level triage.
Use `requests_by_auth_subject` and
`kagent_requests_by_auth_subject_total` for internal usage dashboards
that show which configured teams or service accounts are using the agent. This
dimension is populated only after a named internal bearer token is authenticated
through `KAGENT_SERVICE_AUTH_TOKENS`; raw tokens are never recorded,
and unauthenticated probe traffic is omitted from the subject counter to keep
labels bounded.
Use `kagent_request_duration_seconds_bucket`,
`kagent_request_duration_seconds_count`, and
`kagent_request_duration_seconds_sum` for Prometheus histogram
queries over HTTP request latency. These bucketed metrics support percentile
and SLO burn-rate views that average and max gauges cannot provide on their own.
Use `kagent_runtime_runs_total` and
`kagent_runtime_run_status_total` to trend Codex-style runtime
traffic separately from the deterministic `/run` path. Use
`runtime_runs_by_lifecycle_state` and
`kagent_runtime_run_lifecycle_state_total` for operator-facing lifecycle
dashboards over `waiting_approval`, `running`, `succeeded`, and `failed`
phases. Use
`runtime_runs_by_auth_subject`, `runtime_runs_by_auth_subject_status`,
`runtime_runs_by_auth_subject_lifecycle_state`,
`runtime_resumes_by_auth_subject`, `runtime_approvals_by_auth_subject`,
`kagent_runtime_runs_by_auth_subject_total`, and
`kagent_runtime_run_status_by_auth_subject_total` plus
`kagent_runtime_run_lifecycle_state_by_auth_subject_total` to build
per-team runtime outcome dashboards for success, failure, and approval rates
without exposing bearer tokens. Use
`kagent_runtime_resumes_by_auth_subject_total` to trend
subject/admin resume activity separately from run ownership, and
`kagent_runtime_approvals_by_auth_subject_total` to trend who actually
consumed pending approvals. Use
`kagent_runtime_failed_observations_total` for tool or planner
failure pressure,
`kagent_runtime_progress_event_sink_failures_total` for progress
event delivery failures in streaming, webhook, or operator UI sinks,
`kagent_runtime_hook_failures_total` for runtime hook callback failures,
`kagent_runtime_reconciliation_runs_total{status="..."}` for startup recovery
availability, `kagent_runtime_reconciliation_traces_scanned_total` for recovery
scan volume, `kagent_runtime_reconciliation_outcomes_total{outcome="..."}` for
recovered runs, reopened approvals, live-owner protection, and lock skips, and
`kagent_runtime_reconciliation_errors_total` for trace inspection or recovery
errors. Alert on reconciliation errors immediately; treat
`outcome="recovered_running"` as a restart or instance-failure signal that
requires checking the recovered run timeline and the previous instance health.
Use `kagent_runtime_run_status_total{status="cancelled"}` and
`kagent_runtime_run_status_by_auth_subject_total{status="cancelled"}` to trend
accepted terminal cancellations. These counters do not measure cancellation
propagation latency. Investigate propagation with the persisted run status,
owner heartbeat, service logs, and storage health rather than inventing a
derived metric that the service does not export.
`kagent_runtime_approval_required_total` for human approval queue
pressure, and
`kagent_runtime_failed_budget_exhaustions_total` to alert on
failed runtime runs that spent their whole iteration budget.
Use `kagent_runtime_final_answer_guardrails_total` and
`kagent_runtime_final_answer_guardrails_by_reason_total` to
alert on final-answer boundary corrections, including model identity/deployment
drift and unresolved failure claims, without replaying the provider's original
misleading answer.
Use `kagent_runtime_pending_approvals_current`,
`kagent_runtime_stale_pending_approvals_current`,
`kagent_runtime_max_pending_approval_age_seconds`, and
`kagent_runtime_pending_approval_stale_seconds` as gauges for
the current persisted approval queue. These metrics are derived from compact
runtime traces, so they show whether approval work is still pending now, while
`kagent_runtime_approval_required_total` remains a historical
counter of policy gates encountered by runs.
Use `kagent_runtime_observation_errors_total{error_code="..."}`
to separate runtime observation failures by stable error code, including
`tool_execution_timeout`, `invalid_tool_input`, `invalid_tool_output`, and
`tool_not_allowed`.
Use `runtime_tool_executions_by_tool_status` and
`kagent_runtime_tool_executions_total{tool="...",status="..."}` to identify
which bounded runtime tool is succeeding, failing, or stopping at an approval
boundary. Unknown tool names are collapsed to `unknown`, and unknown statuses
are collapsed to `other`, keeping Prometheus labels low-cardinality while still
showing the operational hotspot.
Use `runtime_planner_attempts_by_status`,
`kagent_runtime_planner_attempts_total`,
`runtime_planner_failures_total`,
`runtime_planner_failures_by_error_code`,
`kagent_runtime_planner_failures_total`, and
`kagent_runtime_planner_failures_by_error_code_total` to separate planner
schema/provider failures from runtime tool failures and build planner failure
rate dashboards. Spikes here usually point to prompt contract drift, invalid
JSON, or provider instability before any tool has been executed. In the
error-code breakdown, `invalid_plan` means planner JSON/schema drift and
`llm_provider_error` means the provider call or provider response failed.
	Use `runtime_llm_provider_requests_total`,
	`runtime_llm_provider_request_attempts_total`,
	`runtime_llm_provider_request_retries_total`,
	`runtime_llm_provider_requests_by_status`,
	`runtime_llm_provider_request_errors_by_type`,
	`runtime_llm_provider_request_http_status`,
	`runtime_llm_provider_request_retryable_reason`, and the Prometheus
	`kagent_runtime_llm_provider_*` metrics to monitor provider instability,
	retry pressure, status-code clusters, retryable reason clusters, and provider
	latency without using high cardinality labels or exposing provider payloads.
	For trace-backed incident review, use
	`GET /runtime/runs?llm_provider_retryable_reason=model_unloaded&limit=20`
	and `GET /runtime/runs/summary?llm_provider_retryable_reason=model_unloaded`
	to line up the same provider symptoms with persisted run IDs.
Use `kagent_runtime_run_duration_seconds_bucket`,
`kagent_runtime_run_duration_seconds_count`, and
`kagent_runtime_run_duration_seconds_sum` for percentile and SLO
views over Codex-style runtime latency, separate from HTTP transport latency and
the deterministic `/run` histogram.
Unknown HTTP paths are aggregated under `__unknown__` in request path metrics
to avoid high-cardinality labels from scanners or malformed client URLs; access
logs still keep the original path for request-level triage.
Use `active_rate_limit_windows` to estimate current per-client rate-limit
cardinality after expired rate-limit windows have been pruned from the metrics
snapshot.
Use `error_responses_by_code` and
`kagent_error_responses_total` to trend client errors,
authentication failures, rate limiting, and service-side agent failures by
stable `error_code`. Use `service_version`, `bind_host`, `bind_port`,
`auth_required`, `trace_persistence`, `trace_directory_permissions`,
`trace_file_permissions`, `trace_probe_file_permissions`, `max_request_bytes`,
`trust_forwarded_for`, `embedding_provider`, `embedding_base_url_configured`,
`llm_provider`, `llm_base_url_configured`, `llm_model`,
`llm_api_key_configured`, `llm_timeout_seconds`, `llm_max_retries`, and
`llm_retry_backoff_seconds` in `/metrics`, plus
`kagent_build_info` in Prometheus scrapes, to audit rollout
version, trace storage policy, and key runtime controls without exposing the
bearer token. Structured
access logs include `error_code` on failed
responses for request-level correlation. Successful `/run` access log records
include `run_id`, and include `trace_path` when trace persistence is enabled,
so operators can correlate HTTP requests, compact responses, and persisted
trace artifacts without parsing response bodies from client logs.
`POST /run` access logs also include `idempotency_key_present` when a client
sent `Idempotency-Key`; the raw key is never logged.
Successful `/run` responses also include `X-Run-ID`, matching the `run_id`
field in the JSON body and access log record, so clients can propagate the run
identifier through their own logs even when they do not persist full response
bodies. When trace persistence is enabled and the response contains
`trace_path`, `/run` responses also include `X-Trace-Path` so gateways and APM
systems can index the persisted trace artifact path without parsing JSON bodies.
Persisted `/runtime/run` responses follow the same `trace_path` and
`X-Trace-Path` convention, with runtime `events`, `plans`, and `observations`
inside the trace artifact.
The access log schema has required fields `event`, `method`, `path`,
`status_code`, `duration_seconds`, `request_id`, and `remote_addr`. Optional
fields are `error_code` for failed responses and `run_id`/`trace_path` for
successful persisted `/run` responses, plus `idempotency_key_present` for
retry correlation without exposing retry keys. `auth_subject` is present when a
request authenticates through the default token or a named internal token,
without exposing the bearer token itself. For persisted runtime responses, the
optional `runtime_owner_auth_subject` field records the runtime trace owner from
the response payload, which can differ from the caller during primary-token
admin recovery. The optional
`resumed_by_auth_subject access log field` is present on successful
`POST /runtime/resume` responses so operators can correlate admin or team
resume activity with persisted trace ownership without logging raw bearer
tokens.

Run one agent goal through the service:

```sh
curl -s -X POST http://127.0.0.1:8000/run \
  -H 'Content-Type: application/json' \
  -d '{"goal":"calculate 2 + 3","max_steps":6,"max_retries":2}'
```

The service returns compact run summaries and structured JSON errors. Failed
responses include `status`, stable `error_code`, and human-readable `error`;
use `error_code` for client branching, dashboards, and alerts. Use HTTP 400
responses for malformed JSON, missing goals, and invalid config. Use HTTP 404
responses for unknown routes. Unsupported methods return structured HTTP `405`
responses with `Allow: GET, HEAD, OPTIONS, POST`. Full trace HTTP responses
are disabled by default: a `/run` request with `"full_trace": true` returns
`403 full_trace_disabled` unless
`KAGENT_SERVICE_ALLOW_FULL_TRACE_RESPONSE=true` is configured. Prefer
persisted traces through `KAGENT_SERVICE_TRACE_DIR` for production
debugging because it returns `trace_path` without exposing internal event bodies
to API clients.
Use `kagent-trace-prune TRACE_DIR --max-age-days 7` to dry-run
trace retention before deleting anything. Add `--delete` only after reviewing
the JSON summary; the command scans top-level `*.json` trace files, skips
symlink trace files, and leaves other files untouched.
For Codex-style runtime retention, prefer
`kagent-trace-prune TRACE_DIR --max-age-days 7 --runtime-only`.
Runtime-only mode scans only `trace_type: "codex_runtime"` files and, by
default, matches old `done`, `failed`, and `cancelled` traces while protecting
`requires_approval` traces. Its JSON summary includes `protected_pending`,
`matched_by_status`, `runtime_scanned`, `skipped_non_runtime`, and
`skipped_status` so operators can review exactly what a retention job would
delete before adding `--delete`.
Add `--fail-on-errors` for cron, CI, and Kubernetes CronJobs so unreadable
traces or delete failures still write the JSON summary and then exit with
status `1` for alerting.
Use `kagent-trace-replay TRACE.json` when debugging a persisted
Codex-style runtime trace. The replay command emits a redacted summary with run
status, tool counts, failed observations, changed files, artifacts, and timeline
metadata. Changed-file entries include `previous_path` for move operations and
`sha256` for content integrity checks so operators can audit rename provenance
from a redacted trace, but the command does not replay `read_file` contents,
action inputs, or patch bodies into stdout.
`max_steps` and `max_retries` must be JSON integers, not strings, floats, or
booleans; invalid values return `400 invalid_agent_config` before the agent
runner starts. `full_trace` must be a JSON boolean; strings such as `"true"`
return `400 invalid_request_body` before the agent runner starts. `goal` is
capped by `KAGENT_SERVICE_MAX_GOAL_CHARS` and oversized goals return
`413 goal_too_large` before the agent runner starts.
The `kagentHighRequestLatency` alert fires when the 95th
percentile HTTP request latency from
`kagent_request_duration_seconds_bucket` stays above 2 seconds.
Check downstream run duration, trace storage latency, concurrency saturation,
and gateway retries before raising timeout or concurrency limits.
The `kagentSlowAgentRuns` alert fires when the 95th percentile
internal agent execution latency from
`kagent_agent_run_duration_seconds_bucket` stays above 2
seconds. If this fires without `kagentHighRequestLatency`, focus on
planner, tool, verifier, and retry behavior rather than HTTP transport.
The `kagentSlowRuntimeRuns` alert fires when the 95th percentile
Codex-style runtime run latency from
`kagent_runtime_run_duration_seconds_bucket` stays above 5
seconds. If this fires without `kagentSlowAgentRuns`, focus on
runtime planning depth, approval gates, external tool latency, and iteration
budget pressure rather than the deterministic `/run` path.
The `kagentMalformedRunRequests` alert fires when malformed
`/run` requests persist, including invalid `Content-Length`, incomplete bodies,
or missing/duplicated/non-JSON `Content-Type`. Check gateway normalization,
client HTTP libraries, and whether probes or scanners are reaching `/run`.
The `kagentOversizedRunRequests` alert fires when
`request_too_large` or `goal_too_large` responses persist. Check whether a
client is sending unbounded prompts, whether a gateway body limit is higher
than the service limit, or whether `KAGENT_SERVICE_MAX_REQUEST_BYTES`
and `KAGENT_SERVICE_MAX_GOAL_CHARS` need an intentional rollout
change.
Set `KAGENT_SERVICE_IDEMPOTENCY_CACHE_SIZE` above `0` to enable
execution-route response reuse for clients that send
`Idempotency-Key` to `POST /run`, `POST /runtime/run`, or
`POST /runtime/resume`. The same key with the same request body on the same
route returns the cached response; the same key with a different body on that
route and authenticated internal subject returns
`409 idempotency_key_conflict`. The cache scopes keys by execution route and
authenticated internal subject so the same key and body on a different route or
for a different team run independently. Anonymous traffic uses a separate
anonymous scope. Raw idempotency keys and bearer tokens are never logged. Keys
must be single-valued 1-128 printable ASCII characters or the service returns
`400 invalid_idempotency_key`. Set
`KAGENT_SERVICE_IDEMPOTENCY_CACHE_PATH` to a SQLite file when retry
responses must survive restarts or be shared by same-volume service replicas;
leave it empty for the in-memory per-process cache. When this path is set,
`/ready` and `kagent-doctor` validate
`idempotency_cache_persistence` by initializing the SQLite file before the
service accepts traffic.

Matching concurrent requests use single-flight execution. The first request
claims ownership, and later requests with the same scoped key and body wait for
its result. The lease and wait window are bounded by the configured execution
and request timeouts. If the owner completes, waiters receive the same response,
including the same `run_id`; if the wait window expires first, the waiter gets
`409 idempotency_request_in_progress`. A caller may take over an expired lease,
and the old owner cannot overwrite the takeover result. In-memory ownership is
process-local; use the SQLite backend on storage shared by all replicas when
single-flight behavior must span service processes.

Monitor `kagent_idempotency_cache_claims`,
`kagent_idempotency_cache_waits`,
`kagent_idempotency_cache_wait_timeouts`, and
`kagent_idempotency_cache_takeovers`. `kagentIdempotencyWaitTimeouts` means
matching retries waited through the full single-flight window: inspect agent or
provider latency, owner process health, request timeout alignment, and shared
SQLite I/O before increasing timeouts. `kagentIdempotencyTakeovers` means a
claim lease expired: correlate replica restarts, termination events, long agent
runs, SQLite lock latency, and run timeout metrics. Repeated takeovers without
restarts usually indicate the lease window is shorter than real execution time
or an owner is failing to release claims.

### Cross-Replica Cancellation Triage

When a cancel request succeeds but the run does not converge to `cancelled`:

1. Confirm all service pods have the same `KAGENT_SERVICE_TRACE_DIR` and mount
   the same `ReadWriteMany` volume at that path. Compare the PVC name and mount
   path from every pod, not only the Deployment template.
2. Read `GET /runtime/runs/{run_id}` through more than one replica. Different
   status or timestamps indicate broken shared-volume visibility or stale
   client-side caching.
3. Inspect the trace's `runtime_instance_id` and the matching heartbeat under
   `.runtime-instances`. A fresh heartbeat with no cancellation convergence
   points to a worker blocked inside a provider/tool call until its timeout; a
   stale heartbeat points to owner loss and startup reconciliation.
4. Check `kagent_error_responses_total{error_code="trace_persistence_failed"}`,
   `kagent_runtime_reconciliation_errors_total`, and
   `kagent_runtime_reconciliation_outcomes_total`. The packaged
   `kagentTracePersistenceFailures` and `kagentRuntimeReconciliationErrors`
   alerts cover shared trace write/read failures without adding a cancellation
   metric that does not exist.
5. Verify the storage class supports cross-client read-after-write visibility,
   atomic rename, and POSIX advisory file locks. File-lock failures or a
   node-local mount invalidate terminal-write serialization.
6. Inspect the final trace timeline. A terminal `cancelled` trace followed by a
   late worker completion event is acceptable only when the terminal status
   remains `cancelled`; any later `done` or `failed` status is a release blocker.

Do not delete the persisted cancellation signal, per-run lock state, or owner
heartbeat while the owner may still be active. Preserve the trace directory for
incident analysis and allow normal cooperative stop or stale-owner recovery to
complete.

### Error Code Catalog

- `agent_run_failed`: the agent runner raised an unexpected exception.
- `agent_run_timeout`: an execution route exceeded
  `KAGENT_SERVICE_RUN_TIMEOUT_SECONDS`.
- `full_trace_disabled`: a client requested `full_trace=true` while HTTP full trace
  responses are disabled.
- `goal_too_large`: `/run` goal text exceeded `KAGENT_SERVICE_MAX_GOAL_CHARS`.
- `expectation_failed`: HTTP `Expect` is present; the service does not support
  continue-style request body negotiation.
- `idempotency_key_conflict`: `Idempotency-Key` was reused with a different
  request body on the same execution route.
- `idempotency_request_in_progress`: a matching request still owns the scoped
  idempotency key after the single-flight wait window expired; retry with the
  same key and body after a bounded delay.
- `incomplete_request_body`: client closed the request before sending the
  declared `Content-Length` bytes.
- `invalid_idempotency_key`: `Idempotency-Key` is duplicated, empty, too long,
  or contains non-printable characters.
- `invalid_agent_config`: request-provided `max_steps` or `max_retries` is invalid.
- `invalid_content_length`: HTTP `Content-Length` is malformed, negative, or
  duplicated.
- `invalid_transfer_encoding`: `Transfer-Encoding` is present; the service
  accepts only bounded `Content-Length` request bodies.
- `invalid_json`: request body is not valid JSON.
- `invalid_request_body`: request body JSON is not an object.
- `method_not_allowed`: HTTP method is unsupported.
- `missing_goal`: `/run` request omitted a non-empty `goal`.
- `not_found`: route is unknown.
- `rate_limit_exceeded`: per-client `/run` rate limit rejected the request.
- `readiness_failed`: `/ready` found one or more failed dependency checks; use
  `failed_checks` for the specific dependency names.
- `request_body_timeout`: client did not finish sending the declared request
  body before `KAGENT_SERVICE_REQUEST_TIMEOUT_SECONDS`.
- `request_too_large`: request body exceeded `KAGENT_SERVICE_MAX_REQUEST_BYTES`.
- `too_many_concurrent_runs`: service-level run concurrency cap is full.
- `trace_persistence_failed`: configured trace directory could not persist the run trace.
- `trace_read_failed`: a persisted runtime trace could not be decoded or read.
- `unauthorized`: bearer token is missing or invalid.
- `unsupported_media_type`: `Content-Type` is missing, duplicated, or not a
  single-valued `application/json` header.

Set `KAGENT_SERVICE_AUTH_TOKEN` to require `Authorization: Bearer ...`
for `POST /run`; unauthorized responses include `WWW-Authenticate: Bearer` for
standard client and gateway handling. `kagent-doctor
--production` requires this token to be at least 16 characters and rejects
placeholder values with `auth_token_placeholder`. Malformed or non-ASCII `Authorization`
header values are treated as unauthorized, not internal service errors. Raw HTTP
requests must use a single-valued `Authorization` header. Tokens
that cannot be represented as safe HTTP header values fail production doctor
with `auth_token_unsafe`. For internal company use, set
`KAGENT_SERVICE_AUTH_TOKENS` to a JSON object mapping stable subjects
to bearer tokens, such as `{"team-a":"...","ops":"..."}`. Matching subjects are
used for rate-limit isolation, access log `auth_subject` fields, and
subject-scoped runtime trace reads; raw tokens are never logged or returned by
`/config`. `POST /runtime/resume` enforces subject-scoped runtime resume: a
subject token can resume only pending runtime traces with the same
`auth_subject`, while the primary bearer token remains the operator/admin
resume token. `POST /runtime/runs/{run_id}/cancel` enforces subject-scoped
runtime cancel: a subject token can cancel only non-terminal runtime traces
with the same `auth_subject`, while the primary bearer token can perform
operator cleanup across subjects and the trace records
`cancelled_by_auth_subject`. Set
`KAGENT_SERVICE_PROTECT_DIAGNOSTICS=true` to require the same bearer
token for diagnostic GET endpoints: `/config`, `/tools`, `/metrics`,
`/metrics.prom`, and `/openapi.json`. `/health`, `/ready`, and `/version`
remain public for probes and rollout checks. `kagent-doctor
--production` requires diagnostic protection to be enabled.
Set
`KAGENT_SERVICE_MAX_REQUEST_BYTES` to cap request body size before the
agent runs. Set `KAGENT_SERVICE_MAX_GOAL_CHARS` to cap accepted goal
length independently of the raw HTTP body size. Set
`KAGENT_SERVICE_IDEMPOTENCY_CACHE_SIZE` to bound how many successful
execution-route responses can be reused by `Idempotency-Key`; the cache is
in-memory by default or SQLite-backed when
`KAGENT_SERVICE_IDEMPOTENCY_CACHE_PATH` is set, with keys scoped by
execution route and authenticated internal subject for `/run`, `/runtime/run`,
and `/runtime/resume`. Anonymous traffic uses a separate anonymous scope.
`/config`, `/metrics`, and `/metrics.prom` expose whether the idempotency cache
backend is `memory` or `sqlite` without exposing the SQLite path. Cache entries,
hits, misses, conflicts, stores, evictions, claims, waits, wait timeouts, and
takeovers help operators
distinguish healthy retry reuse from key misuse and undersized cache capacity.
Rising evictions during the expected client retry window usually means the
cache size is too small or retry traffic is being spread across too many
service processes. Set `KAGENT_SERVICE_RUNTIME_ALLOWED_TOOLS` to
control which runtime tools execute without approval in this deployment. Set
`KAGENT_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT` when different
`auth_subject` teams need stricter or broader runtime tool policies. Set
`KAGENT_SERVICE_RUNTIME_MAX_ITERATIONS` to cap
the accepted planner iteration budget for Codex-style runtime requests. Set
`KAGENT_SERVICE_RATE_LIMIT_PER_MINUTE` to cap per-client `/run`
traffic. By default the limiter uses the socket remote address and ignores
caller-supplied `X-Forwarded-For`; set
`KAGENT_SERVICE_TRUST_FORWARDED_FOR=true` only behind a trusted reverse
proxy that overwrites that header. Empty, overlong, or control-character
unsafe `X-Forwarded-For` values, plus non-IP forwarded client values, fall
back to the socket remote address so
malformed headers cannot create unbounded rate-limit keys. Valid forwarded
client IPs are normalized to canonical address strings before rate limiting so
equivalent IPv6 spellings share the same quota. Rate-limited `429`
responses include
dynamic `Retry-After` headers and a JSON `retry_after_seconds` field based on
the current fixed-window reset. `/run` concurrency-saturation `503` responses
include `Retry-After: 1` and `retry_after_seconds: "1"` for the same client
backoff path. Stalled request-body `408 request_body_timeout` responses also
include `Retry-After: 1` and `retry_after_seconds: "1"`. The
service writes structured access logs to
stderr, flushes each JSON log record after writing, and echoes safe
`X-Request-ID` values for request correlation. Empty, control-character, or
longer-than-128-character request IDs are replaced with service-generated UUIDs
before logging or response echoing. `POST /run` access log records include
`request_body_bytes` so operators can distinguish empty, truncated, oversized,
and normal request bodies without logging body contents.
Responses include `Cache-Control: no-store` so runtime config, metrics, run
results, and structured errors are not retained by clients or intermediaries.
Responses also include `Referrer-Policy: no-referrer` to reduce accidental path
or query leakage in browser-like clients and proxy chains.
Responses include `Content-Security-Policy: default-src 'none';
frame-ancestors 'none'; base-uri 'none'` so browser-like clients cannot execute
response content, frame the API, or resolve relative base URLs from API
payloads.
Responses also include `X-Frame-Options: DENY` for legacy frame-protection
checks that do not evaluate CSP `frame-ancestors`.
Set `KAGENT_SERVICE_ALLOW_FULL_TRACE_RESPONSE=true` only for tightly
controlled operator-only service instances that need complete trace bodies in
HTTP responses. Keep it `false` for normal production traffic.
`kagent-doctor --production` rejects enabled full trace HTTP
responses with `full_trace_response_must_be_disabled`.
Set `KAGENT_SERVICE_TRACE_DIR` to persist full per-run traces and
return `trace_path` in `/run` responses. The trace directory is tightened to
`0700`, and trace files are written through a same-directory owner-only
temporary file and atomically replaced as final `0600` JSON files, so failed
writes do not corrupt an existing trace for the same run ID and persisted trace
contents stay owner-only even outside systemd `UMask` deployments. When trace
persistence is enabled, `/ready` creates or tightens the trace directory to
`0700` and performs a small owner-only temporary-file write/delete probe; failures return
`503 not_ready` with `error_code=readiness_failed` and a stable failure label
before traffic is sent to `/run`, without exposing local filesystem paths or
raw dependency exceptions. Access logs, JSON `/metrics`, and Prometheus
`kagent_error_responses_total` record the same error code.
When SQLite idempotency persistence is configured, `/ready` checks
`idempotency_cache_persistence` and returns
`failed: idempotency_cache_unavailable` if the cache file cannot be initialized.
Operators should use `failed_checks` to route incidents to the failing
dependency, such as `trace_persistence`.
Run `kagent-trace-prune` from a cron job or Kubernetes CronJob
to enforce trace retention. The command defaults to dry-run mode and requires
`--delete` for destructive cleanup, so operators can wire alerting and review
before enabling deletion. Production jobs should include `--fail-on-errors`
so corrupt trace files, unreadable JSON, or failed deletes surface as failed
job runs instead of quiet JSON-only warnings.
Set `KAGENT_SERVICE_RUN_TIMEOUT_SECONDS` to cap execution-route
wall-clock time for `/run`, `/runtime/run`, and `/runtime/resume`; timed-out
runs return a structured HTTP `504` response. Keep this value lower than the
upstream proxy timeout so clients receive service-owned JSON errors instead of
proxy-generated responses.
Set `KAGENT_SERVICE_REQUEST_TIMEOUT_SECONDS` to cap how long a client
can take to send a complete HTTP request, limiting slow-client thread
occupancy. If headers arrive but the body stalls, the service returns
structured HTTP `408 request_body_timeout`.
During container or process shutdown, `kagent-serve` handles
`SIGTERM`, closes the HTTP server, waits for accepted bounded request threads
through `block_on_close`, and exits with status `143` so supervisors can
distinguish an orchestrator stop from an application failure.
