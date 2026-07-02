# Operations Runbook

This runbook covers local and CI operation for the bounded LangGraph agent.

## Daily checks

Use the standard gate before shipping changes:

```sh
scripts/run_checks.sh
```

The same command runs in CI. It covers tests, Ruff linting, byte-compilation,
CLI smoke checks, a real service smoke check, evaluator smoke checks, metrics
smoke checks, no-build-isolation and isolated wheel builds, and clean wheel
install metadata smoke. It also writes
`/tmp/self-correcting-agent-release-manifest.json` with artifact `sha256`
hashes through `self-correcting-agent-release-manifest` so release automation
can compare the shipped wheel against the gate output. Use
`self-correcting-agent-release-manifest --verify /tmp/self-correcting-agent-release-manifest.json`
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
SELF_CORRECTING_LLM_BASE_URL="${PROVIDER_BASE_URL}" \
SELF_CORRECTING_LLM_API_KEY="${PROVIDER_API_KEY}" \
SELF_CORRECTING_LLM_MODEL="agent-runtime-model" \
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
SELF_CORRECTING_STAGING_BASE_URL="https://staging.example.internal" \
SELF_CORRECTING_STAGING_TOKEN="$TEAM_A_STAGING_TOKEN" \
scripts/staging_acceptance.sh \
  >/tmp/self-correcting-agent-staging-acceptance.json
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

Run observability acceptance after the deployment is reachable from the same
network path Prometheus will use:

```sh
SELF_CORRECTING_OBSERVABILITY_BASE_URL="https://staging.example.internal" \
SELF_CORRECTING_OBSERVABILITY_TOKEN="$TEAM_A_STAGING_TOKEN" \
scripts/observability_acceptance.sh \
  >/tmp/self-correcting-agent-observability-acceptance.json
```

The script verifies live `GET /metrics.prom`, required Prometheus metric names,
and packaged Grafana/Prometheus artifacts. When
`SELF_CORRECTING_PROMETHEUS_BASE_URL` is set, it also calls Prometheus
`/api/v1/query` with `SELF_CORRECTING_PROMETHEUS_QUERY` and requires at least
one result. It prints redacted JSON only, so the observability acceptance output
can be attached to the release evidence bundle. Strict gates require metrics
schema `1`, metrics status, required metric count, metrics scrape hash, Grafana
dashboard status and hash, Prometheus rules status and hash, and Prometheus
query status; missing required fields are reported as `invalid_evidence`.

Validate internal rollout sign-off before company-wide enablement:

```sh
scripts/internal_rollout_acceptance.py \
  --signoff /tmp/self-correcting-agent-internal-rollout-signoff.json \
  >/tmp/self-correcting-agent-internal-rollout.json
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

Use `SELF_CORRECTING_PROVIDER_SMOKE_EVIDENCE`,
`SELF_CORRECTING_STAGING_ACCEPTANCE_EVIDENCE`,
`SELF_CORRECTING_OBSERVABILITY_ACCEPTANCE_EVIDENCE`,
`SELF_CORRECTING_INTERNAL_ROLLOUT_EVIDENCE`, and output-path environment
variables when release automation stores artifacts outside `/tmp`.
The bundle reports all missing external evidence files as `evidence_missing`
with their labels and paths. It rejects stale evidence older than 24 hours by
default and reports `evidence_stale` with the affected evidence labels. Override
`SELF_CORRECTING_EVIDENCE_MAX_AGE_SECONDS` only when the release window is
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
SELF_CORRECTING_LLM_BASE_URL="${PROVIDER_BASE_URL}" \
SELF_CORRECTING_LLM_API_KEY="${PROVIDER_API_KEY}" \
SELF_CORRECTING_LLM_MODEL="agent-runtime-model" \
SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS=2 \
self-correcting-agent-doctor --production --require-runtime-provider \
  --trace-dir /tmp/self-correcting-agent-traces
```

`--require-runtime-provider` fails without provider configuration using
`llm_base_url_required`, `llm_model_required`, or `llm_api_key_required`. It
also fails with `runtime_iterations_too_low` when
`SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS` is lower than `2`, because a
single-iteration runtime cannot perform a corrective replan after an
observation.

## Continuous iteration

Use `scripts/continuous_iterate.sh` for long hardening loops:

```sh
scripts/continuous_iterate.sh 10800 60 /tmp/self-correcting-agent.log /tmp/self-correcting-agent.jsonl
```

Arguments are duration seconds, interval seconds, text log path, and JSONL
metrics path. Every iteration clears stale evaluator output before running the
check command, then appends a metrics record.

Custom check commands are supported:

```sh
SELF_CORRECTING_CHECK_COMMAND="scripts/run_checks.sh" \
SELF_CORRECTING_EVAL_FILE="/tmp/self-correcting-agent-eval.json" \
scripts/continuous_iterate.sh 3600 60 /tmp/agent.log /tmp/agent.jsonl
```

## Metrics summary

Summarize a JSONL metrics file with:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.ops.metrics /tmp/self-correcting-agent.jsonl --output /tmp/metrics-summary.json --require-recent-health healthy
```

The `self_correcting_langgraph_agent.ops.metrics` report includes:

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
.venv/bin/python -m self_correcting_langgraph_agent.eval.evaluator --list-cases
.venv/bin/python -m self_correcting_langgraph_agent.eval.evaluator --category recovery
.venv/bin/python -m self_correcting_langgraph_agent.eval.evaluator --case subtraction_tool_success --output /tmp/evaluator.json
.venv/bin/python -m self_correcting_langgraph_agent.eval.evaluator --fail-on-failure
```

## Artifact capture

The CLI writes JSON to stdout by default. Use `--output PATH` to also write the
same payload to an artifact file:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli "calculate 2 + 3" --summary --output /tmp/agent-summary.json
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
self-correcting-agent-batch /tmp/goals.jsonl /tmp/results.jsonl --fail-on-failure
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
self-correcting-agent-serve --host 127.0.0.1 --port 8000
```

## Codex-style runtime configuration

The Codex-style runtime can use a fake provider for deterministic tests or an
OpenAI-compatible chat-completions endpoint for real planning. Configure real
planning with:

- `SELF_CORRECTING_LLM_BASE_URL`: base URL such as `https://api.example.com/v1`.
- `SELF_CORRECTING_LLM_API_KEY`: bearer token for the provider.
- `SELF_CORRECTING_LLM_MODEL`: model name sent to the chat-completions API.
- `SELF_CORRECTING_LLM_TIMEOUT_SECONDS`: provider request timeout, default `30`.
- `SELF_CORRECTING_LLM_MAX_RETRIES`: retry count for transient 429 and 5xx
  provider errors, default `2`.
- `SELF_CORRECTING_LLM_RETRY_BACKOFF_SECONDS`: fixed sleep between provider
  retry attempts, default `0.25`. Numeric provider `Retry-After` response
  headers take precedence for retryable HTTP failures.

Provider config snapshots expose only whether an API key is configured; the key
value is never returned in snapshots, traces, logs, metrics, or docs examples.
Keep the runtime identity boundary clear during operator testing: the product
identity is `self-correcting LangGraph agent runtime`, running in the current
CLI or service process. The underlying model provider is only a replaceable
OpenAI-compatible planner. Identity and deployment questions should describe
the runtime and its local/service process boundary, not the provider's model
brand or hosting location. If the runtime corrects a provider-branded identity
or deployment answer, responses include `final_answer_guardrail` with a
machine-readable reason and `original_answer_omitted=true`, so operators can
audit the correction without replaying the misleading provider answer.
Use `self-correcting-agent-doctor --production --require-runtime-provider` to
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
`answer` for clients that only need the final result.
Tool input or execution failures are kept as observations and can drive another
planner iteration while `max_iterations` budget remains. For deterministic
replay of these correction loops over HTTP, send `plan_sequence` as an ordered
array of strict plans; it is mutually exclusive with `plan`.
Planner parse failures and invalid plan shapes are also kept as `invalid_plan`
observations and can drive another planner iteration while budget remains.
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
`SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS` caps accepted
`max_iterations` for `/runtime/run` and `/runtime/resume`; requests above that
cap return `400 invalid_request_body` before the provider is called.
When a runtime action is blocked by policy, the response status is
`requires_approval` and includes `pending_approval`. Resubmit the same request
with `approved_action_ids` containing only the reviewed action IDs to continue
without changing the default tool policy. Approved IDs must be unique, non-empty action IDs without surrounding whitespace.
Runtime responses and compact persisted summaries include `approved_action_count`
and `approved_action_ids` as approval audit metadata.
If trace persistence is enabled, `POST /runtime/resume` can resume from a
persisted pending run by `run_id` and `approved_action_ids`; resume accepts
only the pending approval action from that trace. Resumed responses include
`resumed_from_run_id` and a new `trace_path`. Operator/admin resumes keep the
original run owner in `auth_subject` and record the approver in
`resumed_by_auth_subject`.
`/runtime/run trace persistence` uses `SELF_CORRECTING_SERVICE_TRACE_DIR` too:
persisted runtime responses include `trace_path`, HTTP responses include
`X-Trace-Path`, and write failures return `trace_persistence_failed`. Runtime
trace files include `trace_type: "codex_runtime"`. `GET /runtime/runs`,
`GET /runtime/runs/{run_id}`, and `POST /runtime/resume` require that marker
and treat other JSON trace files as not found, which keeps older deterministic
`/run` artifacts from appearing in runtime dashboards or approval workflows.
`GET /runtime/runs` skips unreadable trace files so one corrupted artifact does
not break dashboards; direct status or resume requests for an unreadable trace
return `trace_read_failed`.

Run the deployment self-check before or after service startup:

```sh
self-correcting-agent-doctor --trace-dir /tmp/self-correcting-agent-traces
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
.venv/bin/python -m self_correcting_langgraph_agent.cli "capture hello" \
  --runtime \
  --runtime-plan '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"},"reason":"capture"}],"final_answer":"captured"}'
.venv/bin/python -m self_correcting_langgraph_agent.cli --runtime --interactive
.venv/bin/python -m self_correcting_langgraph_agent.cli --runtime --interactive --interactive-json
.venv/bin/python -m self_correcting_langgraph_agent.cli "create README" \
  --runtime \
  --runtime-plan '{"actions":[{"id":"step-1","tool":"apply_patch","input":{"patch":"*** Begin Patch\n*** Add File: README.agent.md\n+# Agent file\n+\n+Created through apply_patch.\n*** End Patch\n"},"reason":"create workspace file"}],"final_answer":"created"}'
curl -s 'http://127.0.0.1:8000/runtime/runs?tag=internal-smoke&limit=20'
curl -s 'http://127.0.0.1:8000/runtime/runs/summary?metadata_key=workflow&metadata_value=internal'
curl -s -X POST http://127.0.0.1:8000/runtime/resume \
  -H 'Content-Type: application/json' \
  -d '{"run_id":"<pending-run-id>","approved_action_ids":["step-1"]}'
```

TTY interactive sessions start with `self-correcting agent ready  /help`, print
live progress while the planner and tools run, and then use a compact operator
transcript by default: status first, answer second, and only real external tool
observations under `tools`. Internal `note` observations stay hidden in the
default view so the shell reads like an agent session instead of a debug trace.
Use `/json` inside the shell for full trace output, `/compact` to return to the
operator view, `/last` to replay the most recent compact result,
`/trace` to print the most recent full JSON trace once, `/memory` to inspect
the current session memory, `/clear` to clear it, and `/help` to list shell
commands. Session memory is in-process by default; add `--session-memory PATH`
to persist compact memory across shell restarts. The memory file is written
owner-only, and `/clear` also clears the persisted file.

`/openapi.json` includes named schemas for production integration, including
`RunRequest`, `RunResponse`, readiness, config, tools, version, metrics, and
structured error responses. It also declares common response headers such as
`X-Request-ID`, `Cache-Control`, `X-Content-Type-Options`,
`Referrer-Policy`, `Content-Security-Policy`, and `X-Frame-Options`, so
generated clients and gateway checks can validate the same contract the
service emits. `ReadinessResponse` includes a structured `failed_checks` array
so probes and release automation can identify failing dependencies without
parsing human-readable check strings.
`/config`, `/metrics`, and Prometheus `self_correcting_agent_build_info` also
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
`llm_base_url`, `llm_model`, `llm_api_key_configured`, and
`llm_timeout_seconds`, plus retry audit fields `llm_max_retries` and
`llm_retry_backoff_seconds`. The raw API key is never exposed; operators
should use `llm_api_key_configured` only to confirm whether a key is present.
Probe and integration endpoints such as `HEAD /health`, `HEAD /ready`,
`OPTIONS /run`, and `GET /metrics.prom` also declare response headers and
content types in the OpenAPI document.
Every OpenAPI operation also has a stable `operationId`, such as `postRun`,
for generated clients and gateway contract checks.
Use those schema names for generated clients, contract review, and downstream
smoke tests.
Use `GET /runtime/tools` to inspect Codex-style runtime tool names,
descriptions, `input_schema`, `output_schema`, and `timeout_seconds` values
before generating or validating plans.
Set `SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS` to a comma-separated
allowlist when a deployment should execute only selected runtime tools without
human approval. Leave it empty for the default policy. Unknown tool names fail
service and doctor configuration before startup, and `/config`, `/metrics`,
and Prometheus `self_correcting_agent_build_info` expose the active
`runtime_allowed_tools` value as non-secret audit metadata.
Set `SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT` to a JSON object
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
The built-in safe local tools are `artifact`, `decision_matrix`, `note`,
`open_url`, `rubric_score`, `task_list`, and `transform_text`; the policy-gated
`http_request` tool performs approved HTTP GET fetches with bounded response
bytes and returns response metadata plus text. `open_url` is the separate local
browser-opening tool for `http://` and `https://` URLs. It uses Google Chrome
automation first, falls back to macOS `open`, and does not fetch page content
into the runtime trace. Approval does not bypass SSRF
protection: `http_request` rejects private, loopback, and link-local URL
targets before opening a socket, including `localhost`, literal private IPs,
link-local metadata addresses, and hostnames that resolve to blocked
addresses. It does not follow redirects; 3xx responses are returned as
observations so a public URL cannot silently redirect execution to a blocked
target. `artifact` records
structured reports, plans, decisions, data, or messages with a stable
`artifact_id`, normalized tags, content format, and byte count.
`decision_matrix` ranks options with weighted criteria for structured tradeoff
decisions, `rubric_score` returns score percentages, failed criteria, and
blocking failures for structured self-review, while `task_list` returns
normalized task items plus status counts for planning and handoff workflows.
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
run starts. Compact summaries expose `metadata_keys` and `tags` but never
accept arbitrary nested metadata objects. CLI runtime runs use the same
validation via repeated `--tag TAG` and `--metadata KEY=VALUE` flags, and
interactive sessions attach those labels to each submitted goal.
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
`pending_approval_tool=http_request` or `pending_approval_action_id=step-1` to
partition active approval queues without opening full traces; lists omit full `pending_approval` payloads, and `GET /runtime/runs/{run_id}` remains the
approval detail endpoint. Invalid filter values, including a blank
`auth_subject`, return
`400 invalid_request_body`. The
endpoint also skips unreadable trace files instead of failing the whole list.
When diagnostic endpoints are protected, the primary token is treated as an
operator/admin diagnostic token and can list all persisted runtime traces.
Tokens from
`SELF_CORRECTING_SERVICE_AUTH_TOKENS` are subject-scoped: `team-a` can list only
runtime traces whose persisted `auth_subject` is `team-a`, and cross-subject run IDs are hidden as `404 not_found`.
Use `GET /runtime/runs/summary` to build a lightweight operations dashboard or
approval queue badge without loading individual runs. It applies subject
visibility and compact list filters, then returns `run_count`, `status_counts`,
`auth_subject_counts`, `tool_counts`, `error_code_counts`,
`failed_observation_count`, `approval_required_count`,
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
Use `GET /runtime/runs/{run_id}` to inspect a persisted runtime run status
summary without returning full trace internals; `auth_subject` is included when
the run was started by a named internal bearer token, while raw tokens are never
persisted. Dynamic run IDs are normalized
to `/runtime/runs/{run_id}` in request path metrics, cancel requests are
normalized to `/runtime/runs/{run_id}/cancel`, while artifact lookups are
normalized to `/runtime/runs/{run_id}/artifacts/{artifact_id}`. Runtime status
summaries include `iteration_count`, `max_iterations`,
`iteration_budget_remaining`, `plan_count`, `observation_count`, and
`event_count` for low-cardinality dashboard triage without exposing full event
or observation bodies. They also include
`failed_observation_count`, `approval_required_count`,
`planner_failure_count`, `tool_failure_count`, `latest_failed_action_id`,
`latest_failed_tool`, `latest_failed_error_code`, `error_code_counts`,
`latest_plan_action_count`, `latest_plan_action_ids`, `dependency_edge_count`,
`tool_names`, `final_answer_guardrail`, `artifact_kinds`, `artifact_formats`, `artifact_tags`,
`artifact_total_bytes`, and `artifact_bytes_by_kind` so
operators can separate planner failures, tool failures, approval queues,
error-code clusters, latest plan shape, dependency-heavy plans, tool-specific
clusters, final-answer guardrail corrections, artifact categories, artifact
formats, artifact tags, and artifact byte volume before opening full traces.
Use `GET /runtime/runs/summary` to aggregate
`final_answer_guardrail_applied_count` and
`final_answer_guardrail_reason_counts` across visible traces without exposing
the original provider answer that triggered the correction. Add
`has_final_answer_guardrail=true` or
`final_answer_guardrail_reason=runtime_identity_boundary` to the same endpoint
when an operations dashboard needs to aggregate only corrected runs.
Artifact-producing runs also
expose `artifact_count` and `artifact_ids`, which downstream workflows can use
to discover non-coding deliverables without loading full observation bodies. Use
`GET /runtime/runs/{run_id}/timeline` for a compact timeline of planner,
policy, executor, and observation status fields without full inputs or outputs.
Timeline responses also include redacted `progress_events` and
`progress_event_count`, which are safe for operations dashboards because they
exclude tool inputs, patch bodies, and observation outputs.
Use
`GET /runtime/runs/{run_id}/artifacts` to list artifact metadata without
content before selecting a specific deliverable. Use
`GET /runtime/runs/{run_id}/artifacts/{artifact_id}` to fetch one persisted
artifact body by ID without returning the full trace; the response includes
`trace_path` for audit correlation. If the target trace cannot be decoded or
read, the endpoint returns
`500 trace_read_failed` without exposing local file paths or parser details.

Use `agent_runs_by_status`, `average_agent_run_duration_seconds`, and
`max_agent_run_duration_seconds` to distinguish healthy agent completions from
agent exceptions or timeouts. Prometheus scrapes expose the same signals through
`self_correcting_agent_runs_total`, `self_correcting_agent_run_status_total`,
and the agent run duration gauges. Use
`self_correcting_agent_agent_run_duration_seconds_bucket`,
`self_correcting_agent_agent_run_duration_seconds_count`, and
`self_correcting_agent_agent_run_duration_seconds_sum` for histogram queries
over internal agent execution latency. Compare this histogram with the HTTP
request duration histogram to separate agent work from HTTP transport,
auth, rate-limit, and trace persistence overhead.
Use `requests_by_method` and
`self_correcting_agent_requests_by_method_total` to separate probe, diagnostic,
preflight, and `/run` traffic by HTTP method during rollout or gateway debugging.
Known HTTP methods are normalized to uppercase, and unknown HTTP methods are
aggregated under `__unknown__` to keep method metrics bounded while access logs
still keep the original method for request-level triage.
Use `requests_by_auth_subject` and
`self_correcting_agent_requests_by_auth_subject_total` for internal usage dashboards
that show which configured teams or service accounts are using the agent. This
dimension is populated only after a named internal bearer token is authenticated
through `SELF_CORRECTING_SERVICE_AUTH_TOKENS`; raw tokens are never recorded,
and unauthenticated probe traffic is omitted from the subject counter to keep
labels bounded.
Use `self_correcting_agent_request_duration_seconds_bucket`,
`self_correcting_agent_request_duration_seconds_count`, and
`self_correcting_agent_request_duration_seconds_sum` for Prometheus histogram
queries over HTTP request latency. These bucketed metrics support percentile
and SLO burn-rate views that average and max gauges cannot provide on their own.
Use `self_correcting_agent_runtime_runs_total` and
`self_correcting_agent_runtime_run_status_total` to trend Codex-style runtime
traffic separately from the deterministic `/run` path. Use
`runtime_runs_by_auth_subject`, `runtime_runs_by_auth_subject_status`,
`runtime_resumes_by_auth_subject`,
`self_correcting_agent_runtime_runs_by_auth_subject_total`, and
`self_correcting_agent_runtime_run_status_by_auth_subject_total` to build
per-team runtime outcome dashboards for success, failure, and approval rates
without exposing bearer tokens. Use
`self_correcting_agent_runtime_resumes_by_auth_subject_total` to trend
subject/admin resume activity separately from run ownership. Use
`self_correcting_agent_runtime_failed_observations_total` for tool or planner
failure pressure, `self_correcting_agent_runtime_approval_required_total` for
human approval queue pressure, and
`self_correcting_agent_runtime_failed_budget_exhaustions_total` to alert on
failed runtime runs that spent their whole iteration budget.
Use `self_correcting_agent_runtime_final_answer_guardrails_total` and
`self_correcting_agent_runtime_final_answer_guardrails_by_reason_total` to
alert on model identity/deployment drift caught by runtime guardrails without
replaying the provider's original misleading answer.
Use `self_correcting_agent_runtime_pending_approvals_current`,
`self_correcting_agent_runtime_stale_pending_approvals_current`,
`self_correcting_agent_runtime_max_pending_approval_age_seconds`, and
`self_correcting_agent_runtime_pending_approval_stale_seconds` as gauges for
the current persisted approval queue. These metrics are derived from compact
runtime traces, so they show whether approval work is still pending now, while
`self_correcting_agent_runtime_approval_required_total` remains a historical
counter of policy gates encountered by runs.
Use `self_correcting_agent_runtime_observation_errors_total{error_code="..."}`
to separate runtime observation failures by stable error code, including
`tool_execution_timeout`, `invalid_tool_input`, `invalid_tool_output`, and
`tool_not_allowed`.
Use `self_correcting_agent_runtime_run_duration_seconds_bucket`,
`self_correcting_agent_runtime_run_duration_seconds_count`, and
`self_correcting_agent_runtime_run_duration_seconds_sum` for percentile and SLO
views over Codex-style runtime latency, separate from HTTP transport latency and
the deterministic `/run` histogram.
Unknown HTTP paths are aggregated under `__unknown__` in request path metrics
to avoid high-cardinality labels from scanners or malformed client URLs; access
logs still keep the original path for request-level triage.
Use `active_rate_limit_windows` to estimate current per-client rate-limit
cardinality after expired rate-limit windows have been pruned from the metrics
snapshot.
Use `error_responses_by_code` and
`self_correcting_agent_error_responses_total` to trend client errors,
authentication failures, rate limiting, and service-side agent failures by
stable `error_code`. Use `service_version`, `bind_host`, `bind_port`,
`auth_required`, `trace_persistence`, `trace_directory_permissions`,
`trace_file_permissions`, `trace_probe_file_permissions`, `max_request_bytes`,
`trust_forwarded_for`, `llm_provider`, `llm_base_url`, `llm_model`,
`llm_api_key_configured`, `llm_timeout_seconds`, `llm_max_retries`, and
`llm_retry_backoff_seconds` in `/metrics`, plus
`self_correcting_agent_build_info` in Prometheus scrapes, to audit rollout
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
`SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE=true` is configured. Prefer
persisted traces through `SELF_CORRECTING_SERVICE_TRACE_DIR` for production
debugging because it returns `trace_path` without exposing internal event bodies
to API clients.
Use `self-correcting-agent-trace-prune TRACE_DIR --max-age-days 7` to dry-run
trace retention before deleting anything. Add `--delete` only after reviewing
the JSON summary; the command scans top-level `*.json` trace files and leaves
other files untouched.
For Codex-style runtime retention, prefer
`self-correcting-agent-trace-prune TRACE_DIR --max-age-days 7 --runtime-only`.
Runtime-only mode scans only `trace_type: "codex_runtime"` files and, by
default, matches old `done`, `failed`, and `cancelled` traces while protecting
`requires_approval` traces. Its JSON summary includes `protected_pending`,
`matched_by_status`, `runtime_scanned`, `skipped_non_runtime`, and
`skipped_status` so operators can review exactly what a retention job would
delete before adding `--delete`.
Use `self-correcting-agent-trace-replay TRACE.json` when debugging a persisted
Codex-style runtime trace. The replay command emits a redacted summary with run
status, tool counts, failed observations, changed files, artifacts, and timeline
metadata, but it does not replay `read_file` contents, action inputs, or patch
bodies into stdout.
`max_steps` and `max_retries` must be JSON integers, not strings, floats, or
booleans; invalid values return `400 invalid_agent_config` before the agent
runner starts. `full_trace` must be a JSON boolean; strings such as `"true"`
return `400 invalid_request_body` before the agent runner starts. `goal` is
capped by `SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS` and oversized goals return
`413 goal_too_large` before the agent runner starts.
The `SelfCorrectingAgentHighRequestLatency` alert fires when the 95th
percentile HTTP request latency from
`self_correcting_agent_request_duration_seconds_bucket` stays above 2 seconds.
Check downstream run duration, trace storage latency, concurrency saturation,
and gateway retries before raising timeout or concurrency limits.
The `SelfCorrectingAgentSlowAgentRuns` alert fires when the 95th percentile
internal agent execution latency from
`self_correcting_agent_agent_run_duration_seconds_bucket` stays above 2
seconds. If this fires without `SelfCorrectingAgentHighRequestLatency`, focus on
planner, tool, verifier, and retry behavior rather than HTTP transport.
The `SelfCorrectingAgentSlowRuntimeRuns` alert fires when the 95th percentile
Codex-style runtime run latency from
`self_correcting_agent_runtime_run_duration_seconds_bucket` stays above 5
seconds. If this fires without `SelfCorrectingAgentSlowAgentRuns`, focus on
runtime planning depth, approval gates, external tool latency, and iteration
budget pressure rather than the deterministic `/run` path.
The `SelfCorrectingAgentMalformedRunRequests` alert fires when malformed
`/run` requests persist, including invalid `Content-Length`, incomplete bodies,
or missing/duplicated/non-JSON `Content-Type`. Check gateway normalization,
client HTTP libraries, and whether probes or scanners are reaching `/run`.
The `SelfCorrectingAgentOversizedRunRequests` alert fires when
`request_too_large` or `goal_too_large` responses persist. Check whether a
client is sending unbounded prompts, whether a gateway body limit is higher
than the service limit, or whether `SELF_CORRECTING_SERVICE_MAX_REQUEST_BYTES`
and `SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS` need an intentional rollout
change.
Set `SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_SIZE` above `0` to enable
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
`SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_PATH` to a SQLite file when retry
responses must survive restarts or be shared by same-volume service replicas;
leave it empty for the in-memory per-process cache. When this path is set,
`/ready` and `self-correcting-agent-doctor` validate
`idempotency_cache_persistence` by initializing the SQLite file before the
service accepts traffic.

### Error Code Catalog

- `agent_run_failed`: the agent runner raised an unexpected exception.
- `agent_run_timeout`: an execution route exceeded
  `SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS`.
- `full_trace_disabled`: a client requested `full_trace=true` while HTTP full trace
  responses are disabled.
- `goal_too_large`: `/run` goal text exceeded `SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS`.
- `expectation_failed`: HTTP `Expect` is present; the service does not support
  continue-style request body negotiation.
- `idempotency_key_conflict`: `Idempotency-Key` was reused with a different
  request body on the same execution route.
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
  body before `SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS`.
- `request_too_large`: request body exceeded `SELF_CORRECTING_SERVICE_MAX_REQUEST_BYTES`.
- `too_many_concurrent_runs`: service-level run concurrency cap is full.
- `trace_persistence_failed`: configured trace directory could not persist the run trace.
- `trace_read_failed`: a persisted runtime trace could not be decoded or read.
- `unauthorized`: bearer token is missing or invalid.
- `unsupported_media_type`: `Content-Type` is missing, duplicated, or not a
  single-valued `application/json` header.

Set `SELF_CORRECTING_SERVICE_AUTH_TOKEN` to require `Authorization: Bearer ...`
for `POST /run`; unauthorized responses include `WWW-Authenticate: Bearer` for
standard client and gateway handling. `self-correcting-agent-doctor
--production` requires this token to be at least 16 characters and rejects
placeholder values with `auth_token_placeholder`. Malformed or non-ASCII `Authorization`
header values are treated as unauthorized, not internal service errors. Raw HTTP
requests must use a single-valued `Authorization` header. Tokens
that cannot be represented as safe HTTP header values fail production doctor
with `auth_token_unsafe`. For internal company use, set
`SELF_CORRECTING_SERVICE_AUTH_TOKENS` to a JSON object mapping stable subjects
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
`SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS=true` to require the same bearer
token for diagnostic GET endpoints: `/config`, `/tools`, `/metrics`,
`/metrics.prom`, and `/openapi.json`. `/health`, `/ready`, and `/version`
remain public for probes and rollout checks. `self-correcting-agent-doctor
--production` requires diagnostic protection to be enabled.
Set
`SELF_CORRECTING_SERVICE_MAX_REQUEST_BYTES` to cap request body size before the
agent runs. Set `SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS` to cap accepted goal
length independently of the raw HTTP body size. Set
`SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_SIZE` to bound how many successful
execution-route responses can be reused by `Idempotency-Key`; the cache is
in-memory by default or SQLite-backed when
`SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_PATH` is set, with keys scoped by
execution route and authenticated internal subject for `/run`, `/runtime/run`,
and `/runtime/resume`. Anonymous traffic uses a separate anonymous scope.
`/config`, `/metrics`, and `/metrics.prom` expose whether the idempotency cache
backend is `memory` or `sqlite` without exposing the SQLite path. Cache entries,
hits, misses, conflicts, stores, and evictions help operators
distinguish healthy retry reuse from key misuse and undersized cache capacity.
Rising evictions during the expected client retry window usually means the
cache size is too small or retry traffic is being spread across too many
service processes. Set `SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS` to
control which runtime tools execute without approval in this deployment. Set
`SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT` when different
`auth_subject` teams need stricter or broader runtime tool policies. Set
`SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS` to cap
the accepted planner iteration budget for Codex-style runtime requests. Set
`SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE` to cap per-client `/run`
traffic. By default the limiter uses the socket remote address and ignores
caller-supplied `X-Forwarded-For`; set
`SELF_CORRECTING_SERVICE_TRUST_FORWARDED_FOR=true` only behind a trusted reverse
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
Set `SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE=true` only for tightly
controlled operator-only service instances that need complete trace bodies in
HTTP responses. Keep it `false` for normal production traffic.
`self-correcting-agent-doctor --production` rejects enabled full trace HTTP
responses with `full_trace_response_must_be_disabled`.
Set `SELF_CORRECTING_SERVICE_TRACE_DIR` to persist full per-run traces and
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
`self_correcting_agent_error_responses_total` record the same error code.
When SQLite idempotency persistence is configured, `/ready` checks
`idempotency_cache_persistence` and returns
`failed: idempotency_cache_unavailable` if the cache file cannot be initialized.
Operators should use `failed_checks` to route incidents to the failing
dependency, such as `trace_persistence`.
Run `self-correcting-agent-trace-prune` from a cron job or Kubernetes CronJob
to enforce trace retention. The command defaults to dry-run mode and requires
`--delete` for destructive cleanup, so operators can wire alerting and review
before enabling deletion.
Set `SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS` to cap execution-route
wall-clock time for `/run`, `/runtime/run`, and `/runtime/resume`; timed-out
runs return a structured HTTP `504` response. Keep this value lower than the
upstream proxy timeout so clients receive service-owned JSON errors instead of
proxy-generated responses.
Set `SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS` to cap how long a client
can take to send a complete HTTP request, limiting slow-client thread
occupancy. If headers arrive but the body stalls, the service returns
structured HTTP `408 request_body_timeout`.
During container or process shutdown, `self-correcting-agent-serve` handles
`SIGTERM`, closes the HTTP server, waits for accepted bounded request threads
through `block_on_close`, and exits with status `143` so supervisors can
distinguish an orchestrator stop from an application failure.
