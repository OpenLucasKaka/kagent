# Architecture

This project is a bounded LangGraph agent service with two compatible runtime
surfaces. The original deterministic runtime remains stable for predictable
plans, structured traces, explicit failure states, and repeatable verification.
The newer Codex-style runtime adds the first non-coding agent layer: LLM-compatible
planning, strict JSON plan parsing, policy-gated tool execution, structured
observations, and fake-provider tests that do not require network credentials.

## LangGraph runtime

`core/agent.py` owns the LangGraph runtime topology:

```text
planner -> executor -> verifier -> END
                       verifier -> reflector -> executor
```

The planner normalizes a goal into supported steps. `core/planning.py` validates
those steps, classifies planner errors, and normalizes injected fault plans. The
executor runs exactly one current step. The verifier compares the result with
the deterministic expected answer. The reflector records why verification
failed and routes the same step back through the executor while retry budget
remains.

## Deterministic tools

`core/tools.py` is the tool registry. Each `ToolSpec` defines command metadata, a
full-match pattern, and a handler. The registry is the source of truth for:

- execution through `execute_step()`
- expected-answer verification through `expected_answer()`
- planner validation through `matching_tool_name()`
- CLI discovery through `registered_tool_metadata()`

This keeps planner, executor, verifier, and docs aligned around one contract.

## Codex-style runtime

`providers/llm.py` owns provider configuration and redacted runtime snapshots for
OpenAI-compatible chat-completions endpoints. `FakeLLMProvider` lets tests and
local development run full planning flows without an API key or network access.

`runtime/` owns the Codex-style runtime implementation. Its package entrypoint
exports the small public runtime surface, while implementation details stay in
`runtime/agent.py`, `runtime/types.py`, `runtime/tools.py`, and
`runtime/policy.py`.

`runtime/types.py` defines strict `AgentPlan`, `AgentAction`, and
`AgentObservation` records. LLM output is accepted only as JSON with an
`actions` list, and malformed or incomplete plans become structured failures
instead of uncaught exceptions. Action IDs must be unique inside a plan because
approval, resume, events, and observations use them as the correlation handle.
Action IDs and tool names must also be canonical strings without surrounding
whitespace, preventing visually similar identifiers from splitting audit or
approval records.

`runtime/tools.py` owns the generic runtime tool registry. Phase 1 includes
safe local tools such as `artifact`, `decision_matrix`, `note`,
`open_url`, `rubric_score`, `task_list`, and `transform_text`, plus the
policy-gated `http_request` tool for approved HTTP GET fetches; later domain
tools can register behind the same metadata, input, output, and error-code
contract.
Tool `input_schema` metadata includes
planner-visible shape and validation constraints such as `required`, `enum`,
`minItems`, `maxItems`, `minLength`, and `maxLength`, and the executor enforces
those constraints before calling a tool handler. Number schemas also support
`minimum` and `maximum` for bounded scoring and weighting tools, while boolean
schemas support pass/fail validation. Tool `output_schema` metadata documents
structured observations for planners, generated clients, and downstream
artifact consumers. Tool metadata also exposes
`approval_required_by_default`, derived from the default runtime policy, so
clients and planners can distinguish direct local tools from tools that normally
enter human approval. `artifact`
gives the non-coding runtime a structured output primitive for reports, plans,
decisions, data, and messages, including a stable `artifact_id`, normalized
tags, content format, and byte count.
`decision_matrix` ranks options with weighted criteria for
tradeoff-heavy planning. `rubric_score` gives the runtime a structured
self-review primitive for pass/fail criteria, score percentages, failed
criteria, and blocking failures. `task_list` gives the runtime a structured
planning artifact with normalized statuses, priorities, owners, due labels, and
status counts. `http_request` returns bounded response metadata and body text
only after the policy layer has produced explicit approval for the action.
It also applies SSRF defense in depth by rejecting private, loopback, and link-local
URL targets before opening a socket, including literal IPs,
`localhost`, and hostnames that resolve to blocked addresses. It does not follow redirects;
3xx responses are returned as observations so a public URL
cannot silently redirect execution to a blocked target.
`open_url` is intentionally separate from `http_request`: it opens `http://`
and `https://` URLs through Google Chrome automation first, with macOS `open`
fallbacks, and does not fetch page content into the runtime trace.

`runtime/policy.py` authorizes each planned tool call before execution. Unknown
or disallowed tools become `requires_approval` observations, which gives the
runtime a human-in-the-loop boundary without executing unsafe actions.
Operators can set `SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS` to configure
which runtime tools execute directly in a deployment. Unknown configured tool
names fail validation before service startup or doctor success, so rollout
mistakes do not silently weaken the policy.
`SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT` adds a subject-level
override keyed by authenticated `auth_subject`, so one shared internal service
can give different teams different direct-execution tool boundaries while
unmatched subjects fall back to the global or default policy.

`runtime/agent.py` orchestrates the first vertical slice: prompt the
provider, parse the plan, authorize actions, execute allowed tools, and return
events, plan, and observations. This layer is intentionally separate from the existing
deterministic `/run` path while the Codex-style runtime matures. Every runtime
trace carries `trace_type: "codex_runtime"` so persisted status, listing, and
resume flows can distinguish Codex-style runtime traces from deterministic
legacy `/run` traces stored in the same directory.
`runtime/metadata.py` owns bounded non-secret run labels shared by CLI and
service execution paths. It normalizes `metadata` string maps and `tags` arrays,
rejects secret-like metadata keys, and keeps run labels small enough for trace
filtering and low-cardinality dashboards.
The runtime also enforces a runtime identity boundary: the agent identity is
`self-correcting LangGraph agent runtime`, running in the user's current CLI or
service process, while the underlying model provider is only a replaceable
OpenAI-compatible planner. The system prompt tells providers not to answer
identity, deployment, ownership, or hosting questions as Qwen, ChatGPT, Claude,
or any other model brand. If a provider still returns a model-branded answer for
identity or deployment prompts, `runtime/agent.py` normalizes the final answer
back to the runtime identity and deployment boundary before clients see it.
Those corrections add `final_answer_guardrail` with a machine-readable reason
such as `runtime_identity_boundary` or `runtime_deployment_boundary`; the
provider's original misleading answer is omitted from that guardrail payload so
clients get an audit signal without replaying the bad identity claim.

## Application entrypoints

`cli/main.py` owns the local operator CLI flow: argument parsing, the
interactive shell loop, in-process session memory, JSON debug mode, and
approval prompt flow. `cli/ui.py` owns terminal presentation: the compact
status/answer/tool view, hidden internal `note` observations, session-memory
printing, last-run replay, one-shot trace printing, help text, color decisions,
and approval prompt copy. The `cli` package exposes only the CLI entrypoint and
`python -m self_correcting_langgraph_agent.cli` support, keeping UI code out of
the package root.

## State and traces

`core/state.py` defines the typed state shape and `AgentConfig`. Configuration can
come from explicit CLI flags, direct Python construction, or environment
defaults via `AgentConfig.from_env()`.

`core/trace.py` owns trace-safe state copying and structured trace append helpers.
Node functions should call these helpers instead of mutating nested trace
collections by hand. Full traces include run metadata, events, execution
attempts, tool calls, verification results, reflections, and errors.

`core/summary.py` converts a full trace into a compact automation-friendly summary.
`utils/json_output.py` provides shared JSON-ready conversion, formatting, and optional
artifact writing for CLI, batch, and service surfaces.

## Service boundary

`service/cli.py` exposes the same bounded agent behavior through a small stdlib
HTTP service. The handler delegates all business behavior to `handle_request()`
so the transport boundary can be tested without binding a socket, while
`create_server()` wraps it in `ThreadingHTTPServer` for actual operation.

The service intentionally keeps a narrow API:

- `GET /health` returns process liveness.
- `HEAD /health` returns liveness headers for load balancers.
- `GET /ready` returns dependency readiness, including trace persistence
  write/delete probing when a trace directory is configured.
- `HEAD /ready` returns readiness headers for load balancers and probes that do
  not need a response body.
- `GET /config` returns redacted runtime configuration.
- `GET /version` returns the package version.
- `GET /tools` returns registered deterministic tool metadata.
- `GET /runtime/tools` returns Codex-style runtime tool metadata, including
  machine-readable `input_schema` and `output_schema` contracts for planner and
  client validation.
- `GET /runtime/runs` lists recent persisted runtime status summaries, bounded
  by a `limit` query parameter so operators can build dashboards without
  scraping full trace files. The endpoint filters on `trace_type:
  "codex_runtime"` before applying the limit, so non-runtime trace files do not
  hide real runtime runs. Operators can also filter compact summaries with
  `auth_subject=team-a`, `status=failed`, `tool=artifact`, `error_code=invalid_tool_input`,
  `latest_failed_error_code=invalid_tool_input`,
  `latest_failed_action_id=fetch-site`, `latest_failed_tool=planner`,
  `iteration_budget_remaining=0`,
  `artifact_kind=report`, `artifact_format=markdown`,
  `artifact_tag=release`, `tag=internal-smoke`,
  `metadata_key=workflow`, `metadata_value=internal`,
  `has_artifacts=true`, `has_errors=true`,
  `has_failures=true`,
  `has_approvals=true`, `has_pending_approval=true`,
  `has_final_answer_guardrail=true`,
  `final_answer_guardrail_reason=runtime_identity_boundary`,
  `approved_action_id=step-1`, and
  `resumed_from_run_id=pending-run`, `resumed_by_auth_subject=default`,
  `pending_approval_tool=http_request`, and `pending_approval_action_id=step-1`;
  `limit` is applied after those filters
  so dashboards can ask for the most recent matching runs. List responses
  include `has_more` and an opaque `next_cursor`; callers pass that value back
  as `cursor` to continue scanning the same filtered run set. Runtime run lists omit full `pending_approval` payloads and expose only compact
  `pending_approval_action_id` and `pending_approval_tool` fields for approval
  queue routing.
  It also skips unreadable trace files so one malformed artifact does not break
  the list endpoint.
- `GET /runtime/runs/summary` returns a runtime fleet summary for the same
  persisted `trace_type: "codex_runtime"` records. It applies the same
  subject visibility rules as runtime list/detail routes, accepts the compact
  list filters, and returns aggregate `run_count`, `status_counts`,
  `auth_subject_counts`, `tool_counts`, `error_code_counts`,
  `failed_observation_count`, `approval_required_count`,
  `pending_approval_count`, `final_answer_guardrail_applied_count`,
  `final_answer_guardrail_reason_counts`, `artifact_count`, `artifact_total_bytes`,
  `tag_counts`, and `metadata_key_counts`
  without exposing trace bodies, tool inputs, or artifact content.
- `GET /runtime/approvals` returns a compact approval queue for persisted
  runtime traces with pending policy-gated actions. It applies the same subject
  visibility rules as runtime list/detail routes and returns `run_id`,
  `auth_subject`, `goal`, `trace_path`, `pending_approval_action_id`, and
  `pending_approval_tool`, and `pending_age_seconds` without returning
  `pending_approval.input`. Operators can add `min_pending_age_seconds=3600`
  to find approval work that is old enough to cancel or escalate.
- `GET /runtime/approvals/summary` returns a compact aggregate over the same
  pending approval queue. It applies subject visibility plus `auth_subject` and
  `tool` filters, then returns `pending_approval_count`,
  `stale_pending_count`, `max_pending_age_seconds`, `auth_subject_counts`, and
  `tool_counts` without returning trace bodies or pending tool inputs.
- `GET /runtime/policy` returns the machine-readable runtime tool execution
  policy for internal audit and rollout checks. Subject tokens receive only
  their own effective policy and matching subject override; the primary token
  receives the global/default policy and all subject overrides. The response
  includes tool names and subject identifiers, never bearer tokens. It also
  returns `effective_tool_policy`, which expands the active policy into one
  entry per registered runtime tool with string `allowed` and
  `approval_required` flags for the current subject, plus
  `effective_tool_policy_sha256` as a stable fingerprint for rollout evidence.
- `GET /runtime/runs/{run_id}` returns a persisted runtime status summary with
  `trace_path`, `auth_subject`, `metadata`, `metadata_keys`, `tags`,
  `pending_approval`, and resume linkage without returning the
  full internal trace body. Persisted traces without the Codex-style runtime
  marker are returned as `404 not_found`; unreadable runtime trace files return
  `500 trace_read_failed`. Compact summaries also include `plan_count`,
  `observation_count`, `event_count`, `failed_observation_count`,
  `planner_failure_count`, `tool_failure_count`, `approval_required_count`,
  `latest_failed_action_id`, `latest_failed_tool`,
  `latest_failed_error_code`, `error_code_counts`, `final_answer_guardrail`,
  `latest_plan_action_count`, `latest_plan_action_ids`,
  `dependency_edge_count`, `tool_names`, `artifact_count`, `artifact_ids`,
  `artifact_kinds`, `artifact_formats`, `artifact_tags`,
  `artifact_total_bytes`, and `artifact_bytes_by_kind`
  so dashboards can show who initiated the run, run shape, planner failure pressure, tool failure
  pressure, approval pressure, the latest failed action, error-code clusters,
  latest plan shape,
  dependency complexity, involved tools, produced non-coding deliverables, and
  artifact categories, formats, tags, and byte volume without reading full
  traces.
- `POST /runtime/runs/{run_id}/cancel` marks one non-terminal persisted
  Codex-style runtime trace as `cancelled`, removes its pending approval payload,
  appends a compact control event, and exposes `cancelled_by_auth_subject`,
  `cancelled_at`, and optional `cancel_reason` in compact status summaries.
  Owner subject tokens can cancel their own runs; the primary token can cancel
  any subject run for operator/admin cleanup.
- `GET /runtime/runs/{run_id}/timeline` returns a compact timeline of runtime
  planner, policy, executor, and observation status fields without full tool
  inputs or outputs. It gives operators the execution order and failure points
  they need before opening a trace artifact.
- `GET /runtime/runs/{run_id}/artifacts` returns an artifact metadata manifest
  for one persisted Codex-style runtime run without returning artifact content.
  This gives downstream systems titles, kinds, formats, tags, byte counts, and
  action IDs before they fetch a specific artifact body.
- `GET /runtime/runs/{run_id}/artifacts/{artifact_id}` reads one persisted
  artifact by ID from a Codex-style runtime trace. It keeps the same runtime
  trace marker isolation and unreadable-trace error handling while avoiding a
  full trace response for downstream report, plan, data, or message consumers;
  the response includes `trace_path` for audit correlation.
- `GET /metrics` returns in-process request counters, error-code counters,
  latency fields, agent run outcome/duration fields, and concurrency gauges as
  JSON.
- `GET /metrics.prom` returns the same service metrics as Prometheus text.
- `GET /openapi.json` returns the lightweight API contract.
- `OPTIONS /run` reports supported HTTP methods through the `Allow` header.
- `POST /run` accepts a JSON object with `goal`, optional `max_steps`, and
  optional `max_retries`, then returns the compact run summary. A full trace
  response is available only when `full_trace` is set and the service is
  explicitly configured to allow HTTP full trace responses.
- `POST /runtime/run` accepts a Codex-style runtime goal. It may include a
  strict `plan` object for deterministic tests, or use configured
  OpenAI-compatible provider settings when the plan is omitted. Tests and
  replay tools may also send `plan_sequence`, an ordered list of strict plans
  that is mutually exclusive with `plan`. The optional `max_iterations` field
  enables repeated plan-act-observe cycles; responses keep the latest `plan`
  for compatibility, include `plans` for the full sequence of planner
  outputs, and expose `iteration_count`, `max_iterations`, and
  `iteration_budget_remaining` for budget observability. Tool failures become
  observations for the next planner iteration
  while budget remains. Planner parse failures and invalid plan shapes also
  become `invalid_plan` observations, allowing the next planner call to correct
  its own output while budget remains. A converged planner may return
  `final_answer`, which the runtime exposes as the top-level response `answer`.
  When a terminal tool failure or planner failure exhausts the iteration
  budget, the final failed observation's `error_code` and `error` are promoted
  to the run top level so clients and status summaries do not need to inspect
  the full trace for the failure cause.
  Strict runtime plans are capped by `MAX_PLAN_ACTIONS` to protect approval,
  executor, and trace systems from unbounded action lists.
  Actions may include `depends_on` references to prior action IDs; the parser
  rejects unknown, later, duplicate, or malformed dependencies as
  `invalid_plan` to keep execution, approval, and trace correlation
  unambiguous. Policy and executor events for dependent actions include
  `depends_on` and compact `dependency_statuses` metadata so operators can
  reconstruct dependency-aware execution without loading tool outputs. The
  parser also rejects unknown top-level plan fields and unknown action fields
  as `invalid_plan`, making planner schema drift visible to clients and replay
  tests.
  Planner `reason` strings and `final_answer` are bounded by
  `MAX_ACTION_REASON_CHARS` and `MAX_PLAN_FINAL_ANSWER_CHARS` so long-form
  deliverables stay in typed artifacts instead of plan metadata.
- Policy-denied runtime actions return `requires_approval` with a
  `pending_approval` action payload. A caller may resubmit the same plan with
  `approved_action_ids` to approve specific action IDs without broadening the
  default tool policy. Approved IDs must be unique, non-empty action IDs without
  surrounding whitespace. Runtime responses and compact summaries include
  `approved_action_count` and `approved_action_ids` as approval audit metadata.
- `POST /runtime/resume` loads a persisted `requires_approval` runtime trace by
  `run_id`, applies reviewed `approved_action_ids`, and writes a new resumed
  trace linked by `resumed_from_run_id`; resume accepts only the pending approval action
  from that trace. Resumed traces keep the original owner `auth_subject` and
  record the approver in `resumed_by_auth_subject`.
- `/runtime/run trace persistence` uses the same configured trace directory as
  `/run`; successful persisted runtime responses include `trace_path`, and HTTP
  responses expose it through `X-Trace-Path`.
- Invalid JSON, missing goals, invalid config, and unknown routes become
  structured JSON failures with 4xx status codes. Failure responses include
  `status`, machine-readable `error_code`, and human-readable `error` fields.

The HTTP boundary enforces a configurable request body limit before running the
agent, supports optional bearer-token protection for `POST /run`, applies
optional per-client rate limiting, and bounds agent execution with a
configurable timeout that returns a structured `504` across `/run`,
`/runtime/run`, and `/runtime/resume`. Responses include
`X-Request-ID`, unsupported methods return structured `405` responses with
`Allow`, and access logs are emitted as structured JSON records on stderr.
Execution-route idempotency is scoped internally by route before consulting the
shared cache, and by authenticated internal subject before storing or reusing a
response. Identical `Idempotency-Key` and body values cannot cross-reuse
responses between `/run`, `/runtime/run`, `/runtime/resume`, or different
internal subjects; unauthenticated traffic uses an anonymous scope. The default
backend is an in-memory per-process LRU cache, while
`SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_PATH` enables a stdlib SQLite cache
for restart-safe and same-volume replica retry reuse.
Runtime trace reads follow the same internal boundary: the primary bearer token
acts as an operator/admin diagnostic token, while subject-mapped bearer tokens
can list or inspect only persisted runtime traces with the same `auth_subject`;
cross-subject run IDs are returned as `404 not_found`.
`POST /runtime/resume` uses the same subject-scoped runtime resume boundary:
subject tokens can resume only their own pending runtime traces, while the
primary bearer token can perform operator/admin recovery across subjects.
Admin recovery preserves the original trace owner in `auth_subject` and records
the recovering subject in `resumed_by_auth_subject`.
`POST /runtime/runs/{run_id}/cancel` follows the same subject boundary for
operator cleanup: subject tokens can cancel only their own non-terminal runtime
traces, while the primary bearer token can cancel any subject run and the trace
records `cancelled_by_auth_subject`.

`service/safety.py` owns pure trust-boundary helpers used by the service:
constant-time bearer token checks, `Content-Type` validation, safe request IDs,
trusted-proxy rate-limit keys, safe trace file names, case-insensitive header
lookup, and JSON-ready conversion. Keeping these helpers outside the handler
keeps HTTP transport code separate from security and serialization rules.

`service/contract.py` owns the OpenAPI contract and allowed-method list used by
`/openapi.json`, `OPTIONS /run`, structured error response schemas, and
structured `405` responses. Error response schemas expose the shared service
error-code catalog as an enum. Success schemas such as `RunRequest`,
`RunResponse`, readiness, config, tools, version, and metrics responses are
also named in the contract, and common response headers are declared for
request correlation, no-store caching, content sniffing protection, referrer
leakage reduction, and browser execution/framing hardening. This includes probe
and integration responses such as `HEAD /health`, `HEAD /ready`,
`OPTIONS /run`, and `/metrics.prom`, keeping API review, generated clients, and
service runtime changes easier to reason about independently. Each operation
declares a stable `operationId` so generated clients, gateway policy checks,
and smoke tests can refer to API operations without depending on summary text.
Config and metrics schemas explicitly document trace permission audit fields so
contract review covers the same trace storage policy exposed at runtime.
The readiness schema also includes `failed_checks` so clients can consume
machine-readable dependency names instead of scraping check messages.

`service_status.py` owns readiness checks and redacted runtime configuration
snapshots. It keeps dependency probing, trace persistence readiness, and
configuration reporting out of the HTTP handler. Trace persistence readiness
uses the same `0700` trace-directory preparation as persisted trace writes
before running its owner-only temporary-file write/delete probe.
SQLite idempotency readiness initializes the configured cache file before
reporting ready. Failed readiness checks return stable failure labels rather than raw
exception text so public probes do not leak local paths, and the top-level
`failed_checks` list captures the failing dependency names for automation.

`service_transport.py` owns pure HTTP transport helpers: response encoding,
JSON versus Prometheus text content types, the `nosniff` header value, and
structured failure `error_code` extraction for access logs and metrics. This
keeps byte-level response formatting out of the request handler.

`service_server.py` owns server bootstrap for the stdlib HTTP service. It
creates `ProductionThreadingHTTPServer` instances with bounded request threads,
`block_on_close`, address reuse, and an explicit listen backlog, then attaches
runtime dependencies: service configuration, metrics, rate limiting, and
concurrency limiting. This keeps process bootstrap separate from request
handling.

`service_router.py` owns pure request routing for the service. It maps method
and path to readiness, config, metrics, OpenAPI, tool metadata, and `/run`
execution responses without depending on `BaseHTTPRequestHandler`. This keeps
route behavior directly unit-testable while `service/cli.py` stays focused on CLI,
server lifecycle, HTTP headers, and access logging.

`service_run.py` owns `POST /run` request execution after the HTTP trust
boundary has accepted the request. It parses the run request body, builds the
agent configuration, enforces the run timeout, converts agent exceptions into
structured service failures, and returns either compact summaries or full
traces.

`service_runtime_run.py` owns `POST /runtime/run` execution after the same HTTP
trust boundary has accepted the request. It converts an optional strict plan
object into a fake provider for deterministic service tests, otherwise builds
an OpenAI-compatible provider from environment-backed LLM settings. It validates
`max_iterations` against `runtime_max_iterations` before calling the runtime
loop so HTTP callers cannot create unbounded replanning cycles. When trace
persistence is configured, it persists the runtime result through
`service_trace_store.py` and returns
`trace_persistence_failed` if the trace cannot be written.

`service_runtime_resume.py` owns `POST /runtime/resume`. It requires configured
trace persistence, loads the previous run by safe `run_id`, verifies the run is
typed as a Codex-style runtime trace and waiting for approval, replays the
persisted plan with action-level approvals, and persists the resumed result.
`service_runtime_cancel.py` owns `POST /runtime/runs/{run_id}/cancel`. It
requires trace persistence, enforces subject-scoped ownership, rejects terminal
runs, clears pending approval state, appends a cancellation control event, and
persists the updated trace atomically. The optional cancellation reason is
bounded to 500 characters so compact status summaries stay audit-friendly and
operator input cannot inflate persisted traces.

Runtime tool specs include `input_schema`, `output_schema`,
`approval_required_by_default`, and `timeout_seconds` metadata. The
planner prompt lists each available tool as structured JSON with name,
description, default approval requirement, input contract, output contract, and
execution budget so LLM-generated plans can target the expected arguments,
estimate approval cost, and reason about observations instead of relying on
natural-language descriptions alone. `/runtime/tools` exposes default
approval metadata, while `/runtime/policy` exposes the current subject's
effective per-tool `allowed` and `approval_required` values after
default/global/subject policy precedence is applied. The
Codex-style `apply_patch` runtime tool applies patch-form file creation inside
the current workspace only, rejects absolute paths, parent traversal, and
overwrites, and returns changed-file `path`, `bytes`, and `sha256` metadata so
file effects remain auditable. The executor also validates runtime tool
inputs against the supported schema subset before invoking handlers, including
required fields, enums, arrays, nested objects, and rejected additional
properties. Handler outputs are validated against `output_schema`; violations
become `invalid_tool_output` observations that can be fed into the next planner
iteration. Handlers that exceed their declared timeout become
`tool_execution_timeout` observations and can also be fed into bounded
replanning. Previous observations are projected into a planner-safe view before
replanning; artifact observations keep metadata such as `artifact_id`, title,
kind, format, tags, and byte count with `content_omitted=true`, avoiding large
artifact bodies in provider prompts while persisted traces retain the full
deliverable. Other long observation strings are represented as `text_prefix`,
`original_chars`, and `truncated_chars` so replanning keeps useful context
without replaying unbounded outputs. Tool observations and planner, policy, and executor
events carry action-level timing metadata (`started_at`, `completed_at`, and
`duration_seconds`) so operators can identify slow provider calls, policy
checks, and tool calls inside a multi-step runtime trace without replaying the
run. Runtime responses also expose `prompt_observation_compaction`,
documenting the active artifact-content omission and long-string truncation
policy used for provider prompts. Runtime guardrail corrections are observable
without exposing the original misleading provider answer: persisted status and
list responses carry `final_answer_guardrail`, fleet summaries include
`final_answer_guardrail_applied_count` and
`final_answer_guardrail_reason_counts`, and Prometheus exposes
`self_correcting_agent_runtime_final_answer_guardrails_total` plus
`self_correcting_agent_runtime_final_answer_guardrails_by_reason_total`.
Runtime run responses and compact persisted status summaries also carry
run-level duration as `duration_seconds`, giving dashboards a low-cardinality
sort key before operators open full traces.

`service_trace_store.py` owns trace persistence for completed runs. It creates
the configured trace directory with `0700` permissions, serializes JSON-ready
traces, applies safe trace file names so run IDs cannot escape the trace
directory, and writes through a same-directory owner-only temporary file before
atomically replacing the final `0600` trace. Readiness probes reuse the same
owner-only temporary-file write path before deleting the probe file.

## Evaluation and metrics

`evaluation_cases.py` contains the evaluator case catalog. `evaluator.py` runs
the selected cases, validates trace invariants, reports failed case exceptions
as structured failures, and supports exact case/category filters.

`metrics.py` summarizes continuous-iteration JSONL records. It reports latest
status, consecutive passes, malformed lines, evaluator totals, recovery
visibility, category counts, and recommendations for follow-up.

## Operational gates

`scripts/run_checks.sh` is the standard project gate. It runs:

- pytest
- Ruff linting
- byte-compilation
- CLI smoke checks
- deployment doctor self-checks
- real HTTP service smoke checks
- evaluator smoke checks
- metrics smoke checks
- wheel build and clean virtual-environment wheel install smoke
- release manifest generation with artifact `sha256` hashes and `--verify`
  checks against the built wheel

`doctor.py` provides the deployment self-check CLI. It reuses service readiness,
redacted config snapshots, version reporting, and tool registration checks so
operators can validate the runtime environment without opening a listening
socket.

`scripts/continuous_iterate.sh` repeats that gate for long-running hardening.
Each iteration clears stale evaluator output before running checks, then writes
a JSONL metrics record with the check exit code and any fresh evaluator report.

## Public surfaces

Stable package-level imports are exposed from `self_correcting_langgraph_agent`
for application code:

- `run_agent`
- `preview_plan`
- `evaluate_agent`
- `registered_evaluation_cases`
- `summarize_run`
- `registered_tool_metadata`
- `registered_tool_names`

The CLI is optimized for automation: JSON output by default, clean argparse
errors, optional `--summary`, `--plan`, `--fail-on-agent-failure`, and
`--output PATH` artifact writing. Runtime CLI runs can also persist
service-compatible full traces with `--trace-dir PATH`, reusing the shared trace
store permissions and filename sanitization; interactive sessions write one
trace per submitted goal.
