# Self-Correcting LangGraph Agent

This project is an intentionally bounded agent loop built with LangGraph.

The first target is a deterministic, testable agent that can:

- plan a supported goal,
- execute the current step,
- verify the result,
- reflect after a failed verification,
- retry within a fixed budget,
- stop with a clear status.

The implementation favors a reliable control loop before adding external LLM
or tool integrations.

The project now also includes the first Codex-style runtime slice for
non-coding agent work. That runtime keeps the deterministic `/run` path stable
while adding an LLM-compatible planner interface, strict JSON plan parsing,
policy-gated tool execution, structured observations, and fake-provider tests
that run without network credentials.

## Code Organization

Detailed module and runtime notes live in
[`docs/architecture.md`](docs/architecture.md).
Operational guidance lives in [`docs/operations.md`](docs/operations.md).
Deployment guidance lives in [`docs/deployment.md`](docs/deployment.md).
Internal rollout guidance lives in
[`docs/internal-rollout.md`](docs/internal-rollout.md).
Internal client example lives in
[`examples/internal_runtime_client.py`](examples/internal_runtime_client.py).
Production readiness notes live in
[`docs/production-readiness.md`](docs/production-readiness.md).
Production readiness audit output can be generated with
[`scripts/production_readiness_audit.py`](scripts/production_readiness_audit.py).
Release notes live in [`CHANGELOG.md`](CHANGELOG.md).

- `core/`: deterministic LangGraph topology, typed state, planning,
  trace helpers, summaries, and deterministic tool registry.
- `runtime/`: Codex-style runtime implementation for LLM plans, bounded
  multi-iteration replanning, generic tool execution, policy decisions, and
  structured observations.
- `service/`: stdlib HTTP API, router, runtime status/resume/cancel handlers,
  transport helpers, trace persistence, and service safety controls.
- `cli/`: operator-facing CLI and interactive terminal shell, including
  compact output, JSON debug mode, approval prompts, and session memory.
- `providers/`: OpenAI-compatible provider configuration plus fake provider
  support for deterministic runtime tests.
- `eval/`: evaluation runner and case catalog.
- `ops/`: batch runner, doctor, metrics, release evidence, and release
  manifest commands.
- `utils/`: shared configuration validation and JSON artifact formatting.

Codex-style runtime tools currently include:

- `artifact`: record a structured report, plan, decision, data, or message with
  a stable `artifact_id`, normalized tags, content format, and byte count.
- `decision_matrix`: rank options with weighted criteria for structured
  tradeoff decisions.
- `http_request`: perform an approved HTTP GET with bounded response bytes,
  response metadata, text output, and SSRF protection that rejects private,
  loopback, and link-local targets. It does not follow redirects; 3xx responses
  are returned as observations.
- `note`: record a short artifact observation.
- `open_url`: open an `http://` or `https://` URL in a local browser window on
  macOS, using Google Chrome automation first with macOS `open` fallbacks. Use
  this for user requests like "open GitHub"; `http_request` only fetches
  content and will not open a browser window.
- `rubric_score`: score output against pass/fail criteria and surface blocking
  failures.
- `task_list`: normalize a structured task list with status counts.
- `transform_text`: uppercase, lowercase, reverse, or trim text.

Runtime tool `input_schema` metadata is both planner-visible and
execution-enforced, including constraints such as `required`, `enum`,
`minItems`, `maxItems`, `minLength`, `maxLength`, `minimum`, `maximum`, and
`boolean` fields. Runtime tool metadata also includes `output_schema` and
`timeout_seconds`, so planners and clients can reason about structured
observations and execution budgets before execution. Handler outputs are
validated against that contract and reported as `invalid_tool_output` when a
tool violates its declared shape; slow handlers are reported as
`tool_execution_timeout` so the runtime can replan within its iteration budget.

Supported deterministic tools:

- `calculate N + M`
- `count words in 'text'`
- `lowercase text in 'text'`
- `multiply N * M`
- `reverse text in 'text'`
- `subtract N - M`
- `trim text in 'text'`
- `uppercase text in 'text'`

List registered tools:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli --list-tools
```

List registered tools with command metadata:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli --list-tools --verbose
```

List supported injected faults:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli --list-faults
```

Print the graph topology:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli --graph
```

Print the installed package version:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli --version
```

Preview planner output without executing the graph:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli "calculate 2 + 3 then subtract 10 - 4" --plan
```

## Run

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
scripts/run_checks.sh
```

`scripts/run_checks.sh` runs the pytest suite, Ruff linting, byte-compilation,
CLI smoke checks, evaluator smoke checks, and metrics smoke checks.
The GitHub Actions workflow in `.github/workflows/ci.yml` installs the package
with dev dependencies and runs the same script, so local and CI gates stay
aligned. CI runs with read-only repository permissions and uploads the built
wheel plus the verified release manifest as workflow artifacts for release
inspection.
The standard gate also writes a release manifest with artifact `sha256` hashes
to `/tmp/self-correcting-agent-release-manifest.json` after the wheel build and
verifies it with `self-correcting-agent-release-manifest --verify`.
It also writes a release evidence bundle to
`/tmp/self-correcting-agent-release-evidence.json`, tying the gate result,
production readiness audit, release manifest verification, and optional
provider smoke and staging acceptance evidence into one redacted JSON file for
internal approval.
Use `scripts/staging_acceptance.sh` against a deployed staging URL before
internal rollout; it verifies authenticated diagnostics, runtime policy,
deterministic `/runtime/run`, trace status/list/summary, and metrics without
printing the staging token. Its redacted evidence also proves the current
subject's effective tool policy, including direct `note` execution and
approval-gated `http_request`. Local CLI sessions can also execute direct
`open_url` actions for browser-opening tasks.
Use `scripts/observability_acceptance.sh` against the deployed service before
production promotion; it verifies live `/metrics.prom`, required Prometheus
metric names, optional Prometheus `/api/v1/query` scrape evidence, and packaged
Grafana/Prometheus artifacts without printing the diagnostic token.
Use `scripts/internal_rollout_acceptance.py` to validate internal rollout
sign-off before company-wide enablement; it requires TL, SRE, security, and
business owner approval plus rollback rehearsal, binds approval to
`runtime_effective_tool_policy_sha256`, and emits redacted JSON evidence. It
also blocks stale sign-offs by matching `release_version` to the installed
package version and `environment` to `internal-production` unless explicit
expected values are provided.
Use `scripts/production_approval_bundle.sh --strict` after the external evidence files
exist to generate strict production readiness and release evidence artifacts in
one command. It rejects evidence files older than 24 hours by default; set
`SELF_CORRECTING_EVIDENCE_MAX_AGE_SECONDS` for an explicit release-window
override. The bundle stdout includes redacted evidence metadata with `sha256`,
age, and freshness status for each external evidence file.
For production approval bundles, `--strict` applies provider smoke, staging
acceptance, observability acceptance, and internal rollout evidence requirements
consistently. Unknown script arguments are rejected as structured
`unknown_argument` errors before evidence files are inspected. Add
`--require-observability-acceptance` to manual release-evidence commands when promoting to shared internal
production so SRE evidence is mandatory too. Add `--require-internal-rollout`
when the rollout ticket must include structured sign-off evidence.
The `Makefile` provides thin aliases for common local workflows:
`make install`, `make test`, `make lint`, `make eval`, `make smoke-service`,
`make readiness-audit`, `make release-evidence`,
`make production-approval-bundle`, `make wheel`,
`make docker-build`, `make check`, and `make clean`.

Installed console scripts mirror the module entry points:

```sh
self-correcting-agent --version
self-correcting-agent-batch /tmp/goals.jsonl /tmp/results.jsonl
self-correcting-agent-doctor --trace-dir /tmp/self-correcting-agent-traces
self-correcting-agent-doctor --production --trace-dir /tmp/self-correcting-agent-traces
self-correcting-agent-doctor --production --require-runtime-provider --trace-dir /tmp/self-correcting-agent-traces
self-correcting-agent-eval --list-cases
self-correcting-agent-metrics /tmp/self-correcting-agent-continuous.jsonl
self-correcting-agent-release-evidence --run-checks-exit-code 0 --readiness-audit /tmp/self-correcting-agent-production-readiness-audit.json --staging-acceptance-evidence /tmp/self-correcting-agent-staging-acceptance.json
self-correcting-agent-release-manifest /tmp/self-correcting-agent-wheelhouse/*.whl
self-correcting-agent-release-manifest --verify /tmp/self-correcting-agent-release-manifest.json
self-correcting-agent-serve --host 127.0.0.1 --port 8000
self-correcting-agent-trace-prune /tmp/self-correcting-agent-traces --max-age-days 7
self-correcting-agent-trace-prune /tmp/self-correcting-agent-traces --max-age-days 7 --runtime-only
self-correcting-agent-trace-replay /tmp/self-correcting-agent-traces/RUN_ID.json
```

## Python API

Stable package-level imports are available for application code and automation:

```python
from self_correcting_langgraph_agent import (
    FakeLLMProvider,
    evaluate_agent,
    preview_plan,
    registered_evaluation_cases,
    registered_tool_metadata,
    run_agent,
    run_runtime_agent,
    summarize_run,
)
```

Run the Codex-style runtime with a fake provider:

```python
from self_correcting_langgraph_agent import FakeLLMProvider, run_runtime_agent

provider = FakeLLMProvider(
    '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"}}]}'
)
result = run_runtime_agent("capture hello", provider=provider)
```

The package includes a `py.typed` marker, so downstream type checkers can use
the inline type annotations shipped with the library.

Run a normal goal:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli "calculate 2 + 3 then count words in 'ship small reliable agents'"
```

Run a batch of goals from JSONL:

```sh
printf '{"id":"sum","goal":"calculate 2 + 3"}\n' >/tmp/goals.jsonl
.venv/bin/python -m self_correcting_langgraph_agent.ops.batch /tmp/goals.jsonl /tmp/results.jsonl --fail-on-failure
```

Each output JSONL record contains the input `id`, line number, final status,
and compact run summary. Invalid input lines are written as failed records
without stopping the rest of the batch. Use `--fail-on-failure` when automation
should exit nonzero if any record failed. Use `--full-trace` when each output
record should include the full agent trace instead of the compact summary.
Each input object may also set `max_steps` and `max_retries` to override the
agent config for that record. These fields must be JSON integers; strings,
floats, and booleans are rejected as failed records.

Serve the agent as a local JSON API:

```sh
self-correcting-agent-serve --host 127.0.0.1 --port 8000
```

The service exposes `GET /health`, `HEAD /health`, `GET /ready`,
`GET /config`, `GET /version`, `GET /tools`, `GET /metrics`,
`GET /metrics.prom`, `GET /openapi.json`, `OPTIONS /run`, `POST /run`, and
`POST /runtime/run`. It also exposes `GET /runtime/tools` for Codex-style
runtime tool descriptions plus `input_schema`, `output_schema`, and
`approval_required_by_default` contracts so internal clients can preview which
actions will enter the approval path.
`/metrics` and `/metrics.prom` include HTTP request counters plus agent run
outcomes (`done`, `failed`, `timeout`), error-code counters, and agent run
duration gauges. Codex-style runtime runs also expose status counters, failure
counters, approval counters, and runtime run duration histogram metrics. They
also expose redacted runtime info such as service
version, auth enabled/disabled state, trace persistence state, and run control
limits for rollout and configuration audits.
Structured failure responses include a stable `error_code` alongside the
human-readable `error` message.
`POST /runtime/run` accepts optional `max_iterations` for bounded
plan-act-observe replanning; responses include the latest `plan` and a `plans`
array with every planner output. A planner `final_answer` is returned as the
top-level `answer`. Tool input or execution failures are recorded as
observations and can drive another planner iteration while budget remains.
Planner parse failures and invalid plan shapes are also recorded as
`invalid_plan` observations and can drive a corrective planner iteration when
`max_iterations` budget remains.
When artifact observations are fed back into replanning prompts, the runtime
keeps artifact metadata and marks `content_omitted=true` instead of replaying
the artifact body, while persisted traces and artifact endpoints still retain
the full deliverable. Other long observation strings are compacted into
`text_prefix`, `original_chars`, and `truncated_chars` fields before they are
sent back to the planner. Runtime responses include
`prompt_observation_compaction` so clients and operators can see the active
prompt compaction policy.
Each strict runtime plan is also capped by `MAX_PLAN_ACTIONS` so one planner
response cannot flood approval queues, traces, or tool execution with an
unbounded action list; oversized plans fail as `invalid_plan`. Actions may
include `depends_on` to name prior action IDs they depend on; unknown, later,
or malformed dependencies fail as `invalid_plan`. Dependent policy and executor
events include `depends_on` and compact `dependency_statuses` metadata for trace
and timeline triage without exposing dependency outputs. Unknown top-level plan
fields and unknown action fields also fail as `invalid_plan`, keeping model
output schema drift visible instead of silently ignored. Planner
`reason` fields and `final_answer` are bounded by `MAX_ACTION_REASON_CHARS` and
`MAX_PLAN_FINAL_ANSWER_CHARS`; larger deliverables should be emitted through
the `artifact` tool instead of bloating plan metadata.
Runtime tool observations and planner, policy, and executor events include
action-level timing fields: `started_at`, `completed_at`, and
`duration_seconds`. Runtime run responses and compact persisted run summaries
also include run-level duration as `duration_seconds` for dashboard sorting and
timeout triage. When a terminal tool failure exhausts the iteration budget, the
last failed observation's `error_code` and `error` are promoted to the runtime
response top level; failures that are later corrected by replanning remain only
in observations.
For deterministic service replay tests, callers may send `plan_sequence` as an
ordered array of strict plans instead of one `plan`. When trace persistence is
configured, runtime responses also include `trace_path` and HTTP responses
include `X-Trace-Path`.
Callers may attach bounded non-secret `metadata` string maps and `tags` arrays
to `/runtime/run` requests for internal workflow routing, dashboard filtering,
and audit correlation. Secret-like metadata keys such as tokens, passwords, or
API keys are rejected before the runtime starts.
The CLI runtime path supports the same labels with repeated `--tag TAG` and
`--metadata KEY=VALUE` flags, including interactive sessions where the labels
are attached to each submitted goal.
Policy-denied runtime actions return `pending_approval`; callers can approve
specific reviewed actions with `approved_action_ids`, which must contain
unique, non-empty action IDs. Responses and compact summaries include
`approved_action_count` and `approved_action_ids` as approval audit metadata.
With trace persistence enabled,
`POST /runtime/resume` resumes a pending run by `run_id`, accepts only the
pending approval action, and writes a new trace linked by
`resumed_from_run_id`. `GET /runtime/runs/{run_id}` returns
a compact persisted status summary without exposing full trace internals, while
`POST /runtime/runs/{run_id}/cancel` marks a non-terminal persisted runtime run
as `cancelled`, removes its pending approval payload, and records
`cancelled_by_auth_subject` for owner/admin audit trails.
`GET /runtime/runs` lists recent persisted runtime summaries and can be filtered
with query parameters such as `status=cancelled`, `status=failed`,
`tool=artifact`, and
`error_code=invalid_tool_input`, `artifact_kind=report`,
`artifact_format=markdown`, `artifact_tag=release`, `has_artifacts=true`,
`tag=internal-smoke`, `metadata_key=workflow`, `metadata_value=internal`,
`has_errors=true`, `has_approvals=true`,
`has_final_answer_guardrail=true`,
`final_answer_guardrail_reason=runtime_identity_boundary`,
`approved_action_id=step-1`, and
`resumed_from_run_id=pending-run`, `pending_approval_tool=http_request`, and
`pending_approval_action_id=step-1`;
`limit` is applied after trace type and query filters.
`GET /runtime/runs/summary` returns a runtime fleet summary over the same
subject-scoped and filtered trace set, including run, status, subject, tool,
error, approval, pending approval, artifact, and artifact byte counts without
returning trace bodies or artifact content. It also includes `tag_counts` and
`metadata_key_counts` for low-cardinality internal workflow dashboards.
`GET /runtime/approvals` returns a compact approval queue with run IDs,
subjects, goals, trace paths, action IDs, and tool names while omitting
`pending_approval.input`.
`GET /runtime/approvals/summary` returns the matching pending approval
aggregate with subject and tool counts for internal dashboards and bots.
`GET /runtime/policy` returns the runtime tool policy for rollout audits:
subject tokens see only their own effective policy, while the primary token can
inspect global/default policy and subject overrides without exposing bearer
tokens. The response also includes `effective_tool_policy`, a stable per-tool
view of `allowed` and `approval_required` for the current subject, plus
`effective_tool_policy_sha256` as a rollout evidence fingerprint. Internal
approval UIs can render the active execution boundary without reimplementing
policy precedence.
Codex-style
runtime traces are explicitly marked with `trace_type: "codex_runtime"`;
runtime status, list, and resume endpoints ignore other JSON trace files in the
same trace directory so legacy `/run` artifacts cannot be mistaken for
resumable runtime runs. Compact runtime summaries include `plan_count`,
`observation_count`, and `event_count` for dashboards that need run shape
without full trace bodies. They also include `failed_observation_count`,
`planner_failure_count`, `tool_failure_count`, `approval_required_count`, and
`error_code_counts`, `latest_plan_action_count`, `latest_plan_action_ids`,
`dependency_edge_count`, `tool_names`, `artifact_kinds`, `artifact_formats`,
`artifact_tags`, `artifact_total_bytes`, and `artifact_bytes_by_kind`
so dashboards can triage planner failures, tool failures, approval pressure,
error-code clusters, current plan shape, plan dependency complexity, involved
tools, produced artifact categories, artifact formats, artifact tags, and
artifact byte volume without loading full trace internals. Call
`GET /runtime/runs/{run_id}/timeline` for a compact timeline of planner,
policy, executor, and observation statuses without full inputs or outputs.
The same timeline response includes redacted `progress_events` plus
`progress_event_count`, so dashboards can separate planner time, tool time, and
terminal run status without opening full trace bodies.
Artifact runs add `artifact_count` and `artifact_ids`, letting downstream
workflows find produced non-coding deliverables from compact status responses.
Call
`GET /runtime/runs/{run_id}/artifacts` to list artifact metadata without
content, then call
`GET /runtime/runs/{run_id}/artifacts/{artifact_id}` to read one persisted
artifact without loading the full trace body; the response includes `trace_path`
for audit correlation. Runtime listing also skips unreadable trace files so one
malformed artifact does not break dashboards; direct status, artifact, or resume
requests for an unreadable runtime trace return `500 trace_read_failed`.
The run endpoint accepts the same bounded config fields as batch records, plus
`full_trace=true` when operators explicitly enable HTTP full trace responses.
That response mode is disabled by default; callers receive
`403 full_trace_disabled` unless
`SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE=true` is configured.
Use `SELF_CORRECTING_SERVICE_TRACE_DIR` for the default production debugging
path, which returns a `trace_path` without exposing internal event bodies in
the HTTP response and echoes that artifact path as `X-Trace-Path` when it is
safe for response headers. `max_steps` and `max_retries` must be JSON integers
here too, and `full_trace` must be a JSON boolean. Invalid types return
`400 invalid_agent_config` or `400 invalid_request_body` before the agent
starts:
The service also enforces `SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS` so very long
goals fail with `413 goal_too_large` before planning begins.
`SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS` caps accepted Codex-style
runtime `max_iterations` for `/runtime/run` and `/runtime/resume`, preventing a
single request from consuming unbounded planner/tool cycles.
Set `SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_SIZE` above `0` to let retried
execution requests with the same `Idempotency-Key` and body reuse the first
response. The cache is scoped per execution route (`POST /run`,
`POST /runtime/run`, and `POST /runtime/resume`) so a retry key reused on a
different route cannot return the wrong response shape. Reusing the same key
with a different body on the same route returns `409 idempotency_key_conflict`.
`/metrics` and `/metrics.prom` expose cache hits, misses, conflicts, stores,
evictions, entries, and configured size. Evictions increasing during normal
retry windows usually means the cache is too small for client retry volume or
the service needs sticky routing.

```sh
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/ready
curl -s http://127.0.0.1:8000/config
curl -s http://127.0.0.1:8000/tools
curl -s http://127.0.0.1:8000/metrics
curl -s http://127.0.0.1:8000/metrics.prom
curl -s http://127.0.0.1:8000/openapi.json
curl -s -X POST http://127.0.0.1:8000/run \
  -H 'Content-Type: application/json' \
  -d '{"goal":"calculate 2 + 3","max_steps":6,"max_retries":2}'
```

Service runtime controls are configured through environment variables:
`SELF_CORRECTING_SERVICE_AUTH_TOKEN` enables bearer auth for `POST /run`,
`SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE` caps per-client run traffic,
`SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS` caps in-flight runs,
`SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_SIZE` bounds the in-memory
single-process execution-route idempotency cache,
`SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS` restricts which Codex-style
runtime tools may execute without approval,
`SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT` maps authenticated
internal subjects to stricter or broader runtime tool allowlists,
`SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS` caps Codex-style runtime
planner iterations accepted over HTTP,
`SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS` bounds one execution request
before a structured `504`, `SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS` bounds
slow HTTP clients before a complete request is received,
`SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE` controls whether
`full_trace=true` may return internal trace bodies over HTTP,
`SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS` requires bearer auth for
diagnostic endpoints such as `/config`, `/tools`, `/metrics`, `/metrics.prom`,
and `/openapi.json` while keeping `/health`, `/ready`, and `/version` public,
`SELF_CORRECTING_SERVICE_AUTH_TOKENS` can map internal subjects to bearer
tokens for per-subject audit logging and rate-limit isolation,
`SELF_CORRECTING_SERVICE_TRUST_FORWARDED_FOR` controls whether `/run` rate
limiting trusts `X-Forwarded-For` from a reverse proxy, and
`SELF_CORRECTING_SERVICE_TRACE_DIR` persists full traces for audit/debug
workflows. When trace persistence is enabled, `/ready` checks that the
configured trace directory can be created and written before reporting ready.
Use `self-correcting-agent-doctor --production` in exposed release automation
to require auth, diagnostic endpoint protection, trace persistence, per-client
rate limiting, and bounded concurrency before deployment. Doctor output also
includes a redacted `runtime_policy` summary with
`effective_tool_policy_sha256` so preflight artifacts can be compared with
staging acceptance evidence.
For provider-backed runtime deployments, add `--require-runtime-provider` and
set `SELF_CORRECTING_LLM_BASE_URL`, `SELF_CORRECTING_LLM_API_KEY`,
`SELF_CORRECTING_LLM_MODEL`, and `SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS`
to at least `2` so the release gate proves real planner wiring before traffic
arrives.
See `deploy/env.example` and `docs/deployment.md` for deployment defaults.

CLI defaults can be configured with environment variables:

```sh
SELF_CORRECTING_MAX_STEPS=3 SELF_CORRECTING_MAX_RETRIES=1 \
  .venv/bin/python -m self_correcting_langgraph_agent.cli "calculate 2 + 3"
```

Explicit `--max-steps` and `--max-retries` flags override environment defaults.
Invalid environment values return a clean argparse error that names the bad
variable.

Run the Codex-style runtime from the CLI with an inline deterministic plan:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli "review launch readiness" \
  --runtime \
  --runtime-plan '{"actions":[{"id":"step-1","tool":"rubric_score","input":{"criteria":[{"name":"Runnable","passed":true}]},"reason":"score"}],"final_answer":"ready"}'
```

Omit `--runtime-plan` to use the OpenAI-compatible provider configured through
`SELF_CORRECTING_LLM_BASE_URL`, `SELF_CORRECTING_LLM_API_KEY`, and
`SELF_CORRECTING_LLM_MODEL`. Use `--max-iterations` to bound runtime replanning,
and `--runtime --list-tools --verbose` to inspect runtime tool schemas.
Start an interactive terminal session with `--runtime --interactive`; each line
you type is treated as a new goal, planned by the configured LLM provider, and
executed against the current working directory until you type `exit` or `quit`.
Use repeated `--tag TAG` and `--metadata KEY=VALUE` flags with `--runtime` to
attach non-secret audit labels to CLI runtime runs.
Use `--trace-dir PATH` with `--runtime` to persist full local trace files named
by `run_id`; interactive sessions write one trace per submitted goal and the
latest `/trace` output includes `trace_path`.
TTY interactive sessions print live progress while the planner and tools run,
then a compact operator transcript: status, answer, and real external tool
observations under `tools`. Internal `note` observations are hidden in this
view so the shell stays readable. Add `--interactive-json` when you need the
full JSON trace for deep debugging.
Inside an interactive session, use `/json` to switch to full traces, `/compact`
to return to the operator view, `/last` to replay the last compact result,
`/trace` to print the last full JSON trace once, `/memory` to inspect current
session memory, `/clear` to clear it, and `/help` to print the available shell
commands.
Session memory is in-process by default. Add `--session-memory PATH` to persist
compact session memory across interactive shell restarts; the memory file is
written owner-only and `/clear` also clears the persisted file.
The runtime includes a Codex-style `apply_patch` tool for workspace file
creation. It accepts `*** Begin Patch` / `*** Add File:` patches, writes only
inside the current workspace, rejects absolute paths, parent traversal, and
overwrites, and returns changed file `path`, byte count, and `sha256` metadata
for audit.
It also includes `open_url` for local browser-opening tasks. `open_url` accepts
only `http://` and `https://` URLs, uses Google Chrome automation first, and
falls back to macOS `open`; use `http_request` only when the agent should fetch
page content as an observation.
Provider calls can retry transient 429 and 5xx failures with
`SELF_CORRECTING_LLM_MAX_RETRIES` and
`SELF_CORRECTING_LLM_RETRY_BACKOFF_SECONDS`; defaults are two retries with a
0.25 second fixed backoff. Numeric provider `Retry-After` response headers take
precedence for retryable HTTP failures.
Run `scripts/smoke_real_llm_runtime.sh` with those provider environment
variables before promoting a model-backed deployment. The redacted output
includes `runtime_effective_tool_policy_sha256`, so provider smoke evidence can
be matched to the reviewed runtime policy boundary.
Run `scripts/staging_acceptance.sh` with `SELF_CORRECTING_STAGING_BASE_URL` and
`SELF_CORRECTING_STAGING_TOKEN` before promoting a deployed service to internal
users.
For internal operator checks, use
`examples/internal_runtime_client.py policy --tool http_request --approval-required true`
to inspect the current subject's approval boundary from `/runtime/policy`.

For shell automation, make failed agent status return exit code `1` while still
printing the JSON trace:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli "calculate 1 + 1 then search the web" --fail-on-agent-failure
```

Write the same JSON payload to an artifact file:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli "calculate 2 + 3" --summary --output /tmp/agent-summary.json
```

The output file is written before `--fail-on-agent-failure` changes the process
exit code, so automation can still collect the trace for failed agent runs.
The same artifact behavior applies to JSON introspection commands such as
`--version`, `--graph`, and `--list-tools`.

Print a compact run summary:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli "uppercase text in 'agent loop'" --inject-fault "uppercase text in 'agent loop'=empty-answer" --summary
```

Compact summaries include `recovered=true` when a run finishes successfully
after at least one failed verification, plus `reflection_reasons` copied from
the structured reflection records and `reflection_reason_counts` for compact
aggregation. They also include `tool_call_count`, the number of successful
tool calls recorded in the run. Full traces and summaries include run metadata:
`run_id`, `started_at`, `completed_at`, and `duration_seconds`.

Run a text transformation goal:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli "uppercase text in 'agent loop'"
```

Trim surrounding whitespace from quoted text:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli "trim text in '  agent loop  '"
```

Demonstrate self-correction by forcing one bad execution:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli "calculate 2 + 3" --inject-wrong-answer "calculate 2 + 3"
```

The same fault injection mechanism can simulate an empty first answer:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli "uppercase text in 'agent loop'" --inject-fault "uppercase text in 'agent loop'=empty-answer"
```

Fault plan step keys are normalized by the Python API and CLI, so extra
whitespace and case differences do not prevent a planned fault from matching.
Goal normalization preserves text inside quotes for accurate tool-call audit
records.
Supported fault names are `wrong-answer`, `empty-answer`, and `tool-error`;
unknown faults are rejected before the run starts.

Self-correction runs include both human-readable `reflection_notes` and
structured `reflections` with the failed step, actual answer, expected answer,
retry number, and reason.
Empty outputs are classified as `answer was empty`; wrong non-empty answers are
classified as verifier mismatches.

Every verifier pass also appends a structured `verification_results` entry with
the step, actual answer, expected answer, pass/fail result, and retry number.

Every executor pass appends an `execution_attempts` entry with the step, tool,
output, injected fault if any, and retry number.

The evaluator also runs trace invariants, checking that planner, executor,
verifier, and reflector records stay aligned with graph events and final state.
Evaluator case exceptions are reported as failed cases instead of aborting the
whole report. The report includes total `duration_seconds`, `slowest_case`, and
per-case `duration_seconds`. Each case also has a `category`, and the top-level
report includes `category_counts` for grouped visibility across workflow, tool,
recovery, and failure scenarios.

Run the built-in evaluator:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.eval.evaluator
```

List evaluator cases without running them:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.eval.evaluator --list-cases
```

Run a targeted evaluator category:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.eval.evaluator --category recovery
```

Run one evaluator case by exact name:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.eval.evaluator --case subtraction_tool_success
```

Write an evaluator report artifact:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.eval.evaluator --case subtraction_tool_success --output /tmp/evaluator.json
```

Make evaluator failures fail automation:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.eval.evaluator --fail-on-failure
```

Unknown evaluator categories or case names return a clean usage error instead
of silently producing an empty report.

Run continuous iteration for five hours:

```sh
scripts/continuous_iterate.sh 18000 60 /tmp/self-correcting-agent-continuous.log /tmp/self-correcting-agent-continuous.jsonl
```

The text log keeps full command output. The JSONL metrics file records each
iteration's status, duration, exit code, evaluator pass/fail counts, and latest
evaluator slowest case plus recovery count/rate and category counts.
Each iteration clears the evaluator output file before running checks, so a
failed check cannot accidentally reuse stale evaluator metrics from a previous
iteration.

Summarize continuous iteration metrics:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.ops.metrics /tmp/self-correcting-agent-continuous.jsonl
```

Write the same metrics summary to an artifact file:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.ops.metrics /tmp/self-correcting-agent-continuous.jsonl --output /tmp/metrics-summary.json
```

Fail automation unless the recent window is healthy:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.ops.metrics /tmp/self-correcting-agent-continuous.jsonl --require-recent-health healthy
```

The metrics summary includes a health verdict (`healthy`, `degraded`, `failing`,
or `unknown`), malformed JSONL line numbers, and recommendations for failed
iterations, evaluator failures, malformed metrics records, and latest slowest
case/recovery visibility. It also reports `latest_status` and
`consecutive_passes` so a long run can show when it recovered after earlier
failures. It also reports `recent_health` so operators can distinguish a
recently stable window from older historical failures. When historical failures
exist but the latest run passes, recommendations call out that recovery
explicitly.
The summary also includes `recent_statuses`, the latest five iteration statuses
in chronological order.
It carries the latest evaluator category distribution as `latest_category_counts`.
If evaluator totals are present but category counts are missing, recommendations
call out the continuous metrics wiring gap.
If the latest iteration fails before producing a fresh evaluator report,
recommendations point to the check log instead of implying an evaluator failure.
If the metrics file does not exist yet, the metrics CLI still prints a JSON
summary with `metrics_file_found=false` instead of raising a traceback.

## Current Graph

```text
planner -> executor -> verifier -> END
                       verifier -> reflector -> executor
```

The verifier decides whether the graph is done, should retry through the
reflector, should continue to the next planned step, or should fail because a
budget has been exhausted.
Retry budget is applied per planned step, while `retry_count` remains the total
number of reflections across the full run.

Planner validation rejects unsupported steps before execution, so impossible
plans fail with a single planner event instead of burning retry budget.
Empty goals also fail in the planner with `empty plan`.
Each planned step is also recorded in `plan_validations` with the matched tool
name and support status.
