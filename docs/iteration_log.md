# Iteration Log

## 2026-06-15

- Created `self-correcting-langgraph-agent/` as an isolated LangGraph agent lab.
- Verified `langgraph==0.6.11` installs and imports on the local Python 3.9 runtime.
- Added failing tests before implementation for graph compilation, successful execution,
  self-correction, retry exhaustion, multi-step plans, CLI output, and a text tool.
- Implemented a bounded LangGraph loop: planner -> executor -> verifier -> reflector.
- Added deterministic arithmetic and word-count tools with verifier-backed retry behavior.
- Added a smoke-check script that runs tests, byte-compilation, and a CLI example.
- Added CLI fault injection with `--inject-wrong-answer` so the retry loop can
  be demonstrated from the command line.
- Added an evaluator module with success, self-correction, and retry-budget
  scenarios; `scripts/run_checks.sh` now runs it as a smoke gate.
- Added `scripts/continuous_iterate.sh`, a five-hour-capable loop that runs the
  check suite repeatedly and appends timestamped results to a log.
- Added the `uppercase_text` deterministic tool and expanded evaluator coverage
  from 3 to 4 scenarios.
- Extracted deterministic tool execution into `tools.py` and added direct tool
  characterization tests; full suite now covers 14 checks.
- Added planner-level validation for unsupported steps, preventing useless
  executor/reflector retries for impossible plans; evaluator now covers 5
  scenarios.
- Reworked deterministic tools into a `ToolSpec` registry, added
  `registered_tool_names()`, and exposed `--list-tools` through the CLI.
- Added structured `reflections` to self-correction runs, recording failed
  step, actual value, expected value, retry number, and reason.
- Added structured `verification_results` emitted by every verifier pass so
  successful and failed checks are both auditable.
- Added the `empty-answer` fault type to simulate transient empty tool output;
  evaluator now covers recovery from this failure mode.
- Added structured `execution_attempts` emitted by every executor pass, including
  injected faults and successful recovery attempts.
- Added structured `plan_validations` emitted by the planner, plus
  `matching_tool_name()` for registry-backed step validation.
- Added `summary.py`, CLI `--summary`, evaluator case summaries, and a summary
  smoke gate in `scripts/run_checks.sh`.
- Added `invariants.py` and wired invariant checks into evaluator cases so
  corrupted trace/state relationships fail evaluation.
- Upgraded `scripts/continuous_iterate.sh` to write per-iteration JSONL metrics
  with status, duration, exit code, and evaluator pass/fail counts.
- Added `metrics.py`, a metrics summary module/CLI for JSONL continuous
  iteration logs, plus a smoke gate in `scripts/run_checks.sh`.
- Added metrics health verdicts and recommendations so continuous runs report
  `healthy`, `degraded`, `failing`, or `unknown` instead of raw counts only.
- Refined reflection reasons so empty answers are classified separately from
  non-empty verifier mismatches.
- Added a `recovered` summary signal to distinguish plain success from
  successful self-correction after a failed verification.
- Split per-step retry budgeting from total run retry counting, so each planned
  step can recover independently while `retry_count` remains cumulative.
- Added an invariant that cumulative `retry_count` must match the number of
  recorded reflections, catching corrupted retry traces during evaluation.
- Improved CLI fault-injection validation so malformed `--inject-fault` values
  return an argparse error instead of a Python traceback.
- Added a deterministic `multiply_numbers` tool, graph coverage, CLI discovery,
  and an evaluator case for `multiply N * M` goals.
- Normalized `run_agent(..., fault_plan=...)` step keys so direct Python API
  callers get the same fault matching behavior as the CLI.
- Fixed the `count_words` tool to support empty quoted text, returning `0`
  instead of treating `count words in ''` as an unsupported step.
- Hardened metrics parsing so malformed JSONL lines are skipped, reported by
  line number, and reflected in health recommendations instead of crashing.
- Fixed `continuous_iterate.sh` to preserve the check command exit code even
  after logging, and to keep writing metrics when evaluator JSON is malformed.
- Added argparse-level validation for `--max-steps` and `--max-retries`, so
  invalid CLI config returns a clean usage error instead of a traceback.
- Added `agent_topology()` and CLI `--graph` so the planner/executor/verifier/
  reflector topology can be inspected without running a goal.
- Exposed `agent_topology` through the package-level public API.
- Added planner-level fast-fail for empty goals and an evaluator case covering
  the `empty plan` failure path.
- Preserved quoted text during goal normalization and moved that logic into a
  lightweight shared module so CLI fault matching stays warning-free.
- Added a deterministic `reverse_text` tool that preserves quoted payload case
  through planning, tool audit records, CLI discovery, and evaluator coverage.
- Ran a real one-iteration `continuous_iterate.sh` smoke; metrics summary was
  `healthy` with evaluator `10/0`.
- Added direct normalization characterization tests for quoted text preservation
  and splitting `then` only outside quotes.
- Fixed `continuous_iterate.sh` to run at least one iteration even when a very
  short duration expires before the first loop check.
- Added shared fault-name validation so unknown injected faults fail fast in the
  Python API and return clean argparse errors in the CLI.
- Hardened evaluator case execution so an exception in one case is reported as
  a structured failed case instead of aborting the whole evaluation report.
- Added per-case `duration_seconds` to evaluator output for lightweight
  performance visibility.
- Added top-level evaluator `duration_seconds` and `slowest_case` fields.
- Added CLI `--list-faults` so supported fault injection names are discoverable
  from the command line.
- Hardened metrics JSONL parsing further so non-object JSON lines are reported
  as malformed instead of crashing summary generation.
- Updated metrics duration parsing to accept fractional seconds while treating
  invalid duration values as `0.0`.
- Added `reflection_reasons` to compact run summaries and evaluator case
  summaries so recovery reasons are visible without reading the full trace.
- Added `reflection_reason_counts` to compact summaries for aggregated recovery
  reason visibility.
- Added `evaluator_slowest_case` to continuous iteration JSONL metrics and
  `latest_slowest_case` to metrics summaries.
- Updated `run_checks.sh` metrics smoke data to include `evaluator_slowest_case`
  and added a script test to keep the smoke sample aligned.
- Ran a current-script `continuous_iterate.sh` smoke and verified JSONL includes
  `evaluator_slowest_case` with metrics summary `latest_slowest_case`.
- Added evaluator-level recovery count/rate, carried those fields through
  continuous JSONL metrics and metrics summaries, and synchronized smoke data.
- Ran a current-script `continuous_iterate.sh` smoke and verified
  `evaluator_recovered_cases`, `evaluator_recovery_rate`,
  `latest_recovered_cases`, and `latest_recovery_rate`.
- Added a transient `tool-error` fault that self-corrects on retry, with graph,
  evaluator, CLI discovery, and smoke metrics coverage.
- Ran a current-script `continuous_iterate.sh` smoke and verified evaluator
  metrics now report `11/0`, `4` recovered cases, and `0.36` recovery rate.
- Added `latest_status` and `consecutive_passes` to metrics summaries so long
  runs can show current recovery after historical failed iterations.
- Added a deterministic `lowercase_text` tool with tool, graph, CLI discovery,
  evaluator, and smoke metrics coverage.
- Refactored evaluator case definitions into an `EvaluationCase` dataclass and
  `_evaluation_cases(...)` factory, keeping report behavior unchanged.
- Improved metrics recommendations to call out when the latest run is passing
  after previous failed iterations.
- Fixed `uppercase_text` to support empty quoted text, matching the behavior of
  the other text tools.
- Added `recent_statuses` to metrics summaries so the latest status window is
  visible alongside cumulative health.
- Added a deterministic `trim_text` tool with tool registry, CLI discovery,
  evaluator coverage, and README documentation.
- Added evaluator case categories and top-level `category_counts` so reports
  can distinguish workflow, tool, recovery, and failure coverage.
- Carried evaluator `category_counts` through continuous iteration JSONL metrics
  and exposed them as `latest_category_counts` in metrics summaries.
- Refactored numeric tool result construction in `tools.py` so arithmetic tools
  share one structured-output helper.
- Added a deterministic `subtract_numbers` tool with tool registry, CLI
  discovery, evaluator coverage, smoke metrics, and README documentation.
- Added a metrics recommendation for records that include evaluator totals but
  are missing evaluator category counts, making stale continuous-loop wiring
  visible.
- Exposed package `__version__` and added CLI `--version` for lightweight
  runtime/version introspection.
- Added `preview_plan()` and CLI `--plan` so planner output and tool validation
  can be inspected without executing the LangGraph loop.
- Refined `reflection_notes` so empty-answer and tool-error recoveries get
  cause-specific retry guidance instead of the generic arithmetic note.
- Refactored planner error classification into a shared helper used by both the
  graph planner and `preview_plan()`.
- Expanded `scripts/run_checks.sh` smoke coverage to exercise CLI `--version`
  and `--plan`.
- Added `tool_call_count` to compact run summaries so successful tool usage is
  visible without expanding the full trace.

## 2026-06-16

- Started a three-hour production-hardening pass with a continuous validation
  loop writing to `/tmp/self-correcting-agent-three-hour.jsonl`.
- Added run metadata (`run_id`, `started_at`, `completed_at`, and
  `duration_seconds`) to full agent traces and compact summaries for
  production observability.
- Added structured tool metadata and CLI `--list-tools --verbose` so automation
  can discover command syntax, descriptions, and examples.
- Added CLI `--fail-on-agent-failure` so shell automation can receive exit code
  `1` for failed agent runs while still capturing the JSON trace.
- Added evaluator `--category` filtering and `evaluate_agent(category=...)` so
  production triage can run targeted recovery/tool/failure subsets.
- Hardened metrics summaries for missing JSONL files so production automation
  gets JSON diagnostics instead of `FileNotFoundError` tracebacks.
- Added evaluator `--case` filtering and smoke coverage for exact case
  reproduction in CI or local triage.
- Split evaluator case definitions into `evaluation_cases.py`, reducing
  `evaluator.py` to the runner/filter/reporting responsibilities.
- Added Ruff as a dev dependency and wired `ruff check src tests` into
  `scripts/run_checks.sh` as a production lint gate.
- Added `AgentConfig.from_env()` plus CLI support for
  `SELF_CORRECTING_MAX_STEPS` and `SELF_CORRECTING_MAX_RETRIES`, with explicit
  CLI flags taking precedence.
- Added clean CLI diagnostics for invalid environment configuration values.
- Split `AgentConfig`, `AgentStatus`, and `AgentState` into `state.py`, keeping
  `agent.py` focused on LangGraph control flow while preserving public imports.
- Added clean evaluator diagnostics for unknown `--category` and `--case`
  filters so CI/local triage fails loudly instead of reporting an empty run.
- Promoted evaluator, summary, and tool-discovery helpers to stable
  package-level imports for application code and automation.
- Extracted trace copying and execution/event recording into `trace.py`, with
  focused tests for nested state isolation and serializable trace records.
- Fixed `continuous_iterate.sh` to clear stale evaluator JSON before every
  iteration, preventing failed checks from inheriting previous evaluator totals.
- Added CLI `--output PATH` so JSON traces/summaries can be written as
  automation artifacts, including before `--fail-on-agent-failure` exits `1`.
- Added `--output` coverage to `scripts/run_checks.sh` so artifact writing is
  exercised by the standard project gate.
- Unified CLI JSON emission so `--output PATH` also works for introspection
  commands such as `--version`, `--graph`, and `--list-tools`.
- Extracted plan validation, planner error classification, and fault plan
  normalization into `planning.py`, reducing `agent.py` to LangGraph runtime
  orchestration.
- Added `docs/architecture.md` and README linkage describing the LangGraph
  runtime, deterministic tool registry, trace/state boundaries, evaluation,
  metrics, public API, and operational gates.
- Improved metrics recommendations for latest failed checks without a fresh
  evaluator report, pointing operators to the check log instead.
- Added a PEP 561 `py.typed` marker and setuptools package-data wiring so
  downstream type checkers can consume the package's inline annotations.
- Added a GitHub Actions CI workflow that installs dev dependencies and runs
  `scripts/run_checks.sh`, keeping local and remote gates aligned.
- Added a thin `Makefile` with `install`, `test`, `lint`, `eval`, and `check`
  targets for predictable local developer workflows.
- Added `docs/operations.md` with continuous-iteration commands, metrics
  interpretation, failure triage, targeted evaluator usage, and CLI artifact
  capture guidance.
- Added evaluator case discovery through `registered_evaluation_cases()` and
  CLI `--list-cases`, with standard smoke coverage in `scripts/run_checks.sh`.
- Added pytest warning configuration and `PYTHONWARNINGS=ignore` Makefile
  entries for known local SSL/dependency warning noise.
- Added `CHANGELOG.md` and README linkage documenting the current 0.1.0
  production-oriented LangGraph agent capabilities.
- Added `make clean` as an explicit developer cleanup target for caches,
  bytecode, and egg-info build artifacts.
- Added evaluator CLI `--output PATH` so evaluation reports and case discovery
  payloads can be written directly as automation artifacts.
- Extracted shared JSON formatting and artifact writing into `json_output.py`,
  removing duplicate output helpers from the agent and evaluator CLIs.
- Added metrics CLI `--output PATH` and standard smoke coverage so metrics
  summaries can be collected as automation artifacts.
- Added `recent_health` to metrics summaries so long-running hardening can show
  whether the recent window is healthy, recovering, failing, or unknown.
- Added console-script smoke coverage for `.venv/bin/self-correcting-agent` in
  `scripts/run_checks.sh`, validating installed entry points in the standard
  gate.
- Expanded console-script smoke coverage to
  `.venv/bin/self-correcting-agent-eval` and
  `.venv/bin/self-correcting-agent-metrics`.
- Documented installed console scripts in README so users can run the package
  through distribution entry points, not only `python -m`.
- Added evaluator `--fail-on-failure` so automation can exit nonzero when an
  evaluator report contains failed cases, and wired it into `scripts/run_checks.sh`.
- Added a batch JSONL runner (`self_correcting_langgraph_agent.ops.batch` and
  `self-correcting-agent-batch`) for processing multiple agent goals into
  JSONL result summaries with structured per-line failures.
- Added batch `--fail-on-failure` so schedulers can receive exit code `1` when
  any batch record failed, while preserving all per-line output records.
- Added batch `--full-trace` so batch jobs can emit complete agent traces when
  operators need audit/debug detail instead of compact summaries.
- Added per-record batch config support for `max_steps` and `max_retries`, so
  JSONL jobs can tune agent budgets per goal.
- Added metrics `--require-recent-health` so monitoring and CI jobs can fail
  when the latest rolling health window is not in the required state.
- Extracted service trace persistence into `service_trace_store.py` with
  path-safe trace names and same-directory atomic replacement.
- Extracted `POST /run` execution into `service_run.py`, keeping the HTTP
  service focused on transport concerns while preserving existing behavior.
- Centralized JSON-ready conversion in `json_output.py` and reused it across
  CLI, batch, service responses, and trace persistence.
- Added service-level agent run outcome and duration metrics for `/run`, with
  JSON and Prometheus exposure plus smoke-gate assertions.
- Added machine-readable `error_code` fields to structured service failure
  responses and documented the shared OpenAPI error schema.
- Added error-code counters to JSON/Prometheus service metrics and included
  `error_code` in structured access logs for failed responses.
- Promoted service error codes into a shared catalog, wired the catalog into
  OpenAPI as an enum, and documented the operational meaning of each code.
- Extracted HTTP response encoding and structured error-code extraction into
  `service/transport.py`, thinning the service handler transport logic.
- Added `self-correcting-agent-doctor`, a deployment self-check CLI that
  reports readiness, redacted config, version, and registered tool count.
- Added doctor policy checks for public bind without auth and a `--require-auth`
  gate for externally exposed release automation.
- Added doctor `--production`, a stricter release gate that requires bearer
  auth, trace persistence, per-client rate limiting, and bounded concurrency.
- Extracted stdlib HTTP server bootstrap into `service/server.py`, including
  runtime config, metrics, rate limiter, and concurrency limiter attachment.
- Extracted pure HTTP route selection into `service/router.py`, reducing
  `service/cli.py` to CLI/server lifecycle, transport headers, and access logging.
- Expanded release hygiene by cleaning root and `src` egg-info metadata through
  `make clean` and by making `scripts/run_checks.sh` remove local build
  metadata on exit.
- Added a systemd `ExecStartPre` production doctor check so VM/bare-metal
  deployments fail before service startup when required controls are missing.
- Added a Kubernetes production manifest with Secret/ConfigMap/PVC resources,
  readiness/liveness probes, Prometheus scrape annotations, resource limits,
  non-root security contexts, and a production doctor initContainer.
- Added Kubernetes disruption and network controls through a
  `PodDisruptionBudget` and restrictive `NetworkPolicy`.
- Expanded the OpenAPI contract with named success schemas for run requests,
  run responses, readiness, config, tools, version, and metrics payloads.
- Added `Cache-Control: no-store` to HTTP responses and wired service smoke
  coverage so runtime config, metrics, run results, and errors are not cached.
- Added `run_id` and persisted `trace_path` fields to `/run` access logs for
  direct correlation between HTTP requests, responses, and trace artifacts.
- Added `X-Run-ID` to successful `/run` HTTP responses and documented it in
  OpenAPI for client-side request/log/trace correlation.
- Flushed structured access logs after each stderr write to reduce log loss
  during container or process shutdown.
- Added redacted runtime build info to `/metrics` and
  `self_correcting_agent_build_info` Prometheus output for version and rollout
  audits without exposing bearer tokens.
- Added a production HTTP server subclass with bounded request threads,
  `block_on_close`, explicit address reuse, and a larger listen backlog for
  graceful shutdown, safer restarts, and short traffic bursts.
- Added graceful `SIGTERM` handling for `self-correcting-agent-serve`, closing
  the HTTP server and returning exit status `143` for orchestrator stops.
- Added `SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS` and per-connection
  socket timeouts so slow or incomplete HTTP requests cannot hold service
  handler threads indefinitely.
- Added common response headers to the OpenAPI contract for `X-Request-ID`,
  no-store cache control, and content sniffing protection, with smoke coverage
  against the live `/openapi.json` endpoint.
- Added Kubernetes request-timeout configuration parity and baseline Prometheus
  alerting rules for scrape availability, HTTP 5xx rate, run timeouts, failed
  runs, and rate-limit pressure.
- Added Kubernetes `terminationGracePeriodSeconds: 45`, documenting that the
  grace window exceeds the default 30-second run timeout so SIGTERM shutdowns
  can finish bounded runs cleanly before forced termination.
- Added `WWW-Authenticate: Bearer` to unauthorized HTTP responses, documented
  it in OpenAPI, and upgraded service smoke to run with bearer auth enabled.
- Added `Retry-After` headers to rate-limit and `/run` concurrency rejections,
  with OpenAPI and smoke coverage so clients and gateways can back off
  predictably.
- Hardened the HTTP `Server` header so real service responses expose only the
  product token and not the Python runtime version, with smoke and security
  documentation coverage.
- Switched continuous iteration duration metrics to monotonic timing so system
  clock jumps do not inflate or deflate operational trend data.
- Expanded the OpenAPI contract and live service smoke coverage for non-JSON
  and empty responses: `HEAD /health`, `OPTIONS /run`, `/metrics.prom`, and
  `/openapi.json` now have explicit response contracts.
- Added `TimeoutStopSec=45` to the systemd unit and deployment documentation
  so VM/bare-metal shutdowns get the same bounded-run grace window as
  Kubernetes.
- Added a machine-readable access log schema helper and documented required
  request log fields plus optional `error_code`, `run_id`, and `trace_path`
  correlation fields for log pipeline ingestion.
- Added stable OpenAPI `operationId` values for every HTTP operation and wired
  live service smoke coverage so generated clients and gateway contracts have
  stable operation names.
- Hardened `/run` request config parsing so `max_steps` and `max_retries`
  reject strings, floats, and booleans as `invalid_agent_config` before agent
  execution, with real HTTP smoke coverage.
- Reused the same JSON integer validation for batch record config, so batch
  jobs reject bad `max_steps` and `max_retries` values as failed records while
  continuing later jobs.
- Added `self-correcting-agent-release-manifest`, a release manifest generator
  that records artifact file names, sizes, and `sha256` hashes, then wired it
  into `scripts/run_checks.sh` after the release wheel build.
- Added release manifest `--verify` support and wired it into the standard
  gate so artifact drift after manifest generation fails release checks.
- Added `SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS` and `goal_too_large` handling
  so oversized `/run` goals are rejected before agent execution, with config,
  metrics, Prometheus, OpenAPI, deployment, and smoke coverage.
- Added `SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE=false` as the
  default HTTP response policy for `full_trace=true`, returning
  `full_trace_disabled` unless explicitly enabled while keeping persisted trace
  artifacts available for operator debugging.
- Hardened `/run` request parsing so `full_trace` must be a JSON boolean,
  rejecting strings such as `"true"` as `invalid_request_body` before agent
  execution.
- Added `SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS` so `/config`, `/tools`,
  `/metrics`, `/metrics.prom`, and `/openapi.json` can require bearer auth,
  then upgraded `doctor --production`, Kubernetes defaults, and service smoke
  coverage to require the protection for production gates.
- Tightened `doctor --production` so bearer tokens shorter than 16 characters
  fail with `auth_token_too_short`, keeping local auth checks lightweight while
  making exposed release gates less accepting of weak shared secrets.
- Added optional `POST /run` `Idempotency-Key` support backed by a bounded
  in-memory cache, with `409 idempotency_key_conflict` for same-key/different-body
  retries plus OpenAPI, deployment, metrics, and smoke coverage.
- Hardened `Idempotency-Key` parsing so keys must be 1-128 printable ASCII
  characters, returning `invalid_idempotency_key` before agent execution.
- Added idempotency cache activity counters for hits, misses, conflicts, and
  stores in `/metrics`, Prometheus output, and live service smoke coverage.
- Added a Prometheus alert for `idempotency_key_conflict` so client retry-key
  misuse is visible through the standard production alert rules.
- Hardened `self-correcting-agent-doctor --production` to reject common bearer
  auth placeholders such as `replace-with-a-long-random-token` with
  `auth_token_placeholder`, including CLI/env tests, standard gate coverage,
  and security/deployment documentation.
- Tightened rate-limit observability so `active_rate_limit_windows` prunes
  expired windows during metrics snapshots, keeping low-traffic service metrics
  from reporting stale client cardinality.
- Hardened service and doctor CLI startup so invalid service environment
  variables fail through concise argparse errors instead of Python tracebacks,
  with release-gate smoke coverage for both service and doctor entrypoints.
- Added dynamic `retry_after_seconds` to rate-limit `429` JSON responses and
  aligned the HTTP `Retry-After` header/OpenAPI contract with the fixed-window
  reset time.
- Added `retry_after_seconds` to concurrency-saturation `503` JSON responses
  so both rate-limit and run-slot rejections expose the same machine-readable
  client backoff field.
- Added HTTP method cardinality to JSON and Prometheus service metrics via
  `requests_by_method` and `self_correcting_agent_requests_by_method_total`.
- Bounded HTTP path metrics cardinality by aggregating unknown routes under
  `__unknown__` while keeping raw paths in structured access logs.
- Added a Prometheus unknown route alert using the bounded `__unknown__` path
  metric and `not_found` error counter so scanner or routing drift is visible.
- Added `idempotency_cache_evictions` to the bounded idempotency cache metrics,
  Prometheus exposition, smoke coverage, and operations docs so undersized
  retry caches are visible before they become client-visible duplicate work.
- Added raw-key-free `idempotency_key_present` access log enrichment for
  `POST /run`, with schema, HTTP, smoke, and operations documentation coverage.
- Added explicit `incomplete_request_body` handling when clients close before
  sending declared `Content-Length` bytes, with HTTP, OpenAPI, smoke, metrics,
  and operations documentation coverage.
- Added `self-correcting-agent-trace-prune` for dry-run-first persisted trace
  retention, with delete mode, wheel entrypoint coverage, and deployment
  operations guidance.
- Promoted trace pruning from entrypoint discovery to an executed
  `scripts/run_checks.sh` smoke that verifies dry-run output, explicit
  `--delete` cleanup, and non-JSON trace sidecar preservation.
- Added structured `408 request_body_timeout` handling for stalled HTTP request
  bodies, with socket-level tests, OpenAPI, live smoke, metrics, operations,
  and security documentation coverage.
- Added a Kubernetes `CronJob` to run `self-correcting-agent-trace-prune`
  against the shared trace PVC with 7-day retention, hardened pod security, and
  deployment/readiness documentation coverage.
- Hardened `self-correcting-agent-doctor --production` to reject enabled full
  trace HTTP responses with `full_trace_response_must_be_disabled`, including
  CLI/env tests, standard gate coverage, and security/operations docs.
- Added Prometheus alerting for `request_body_timeout` so slow client or gateway
  request-body stalls become visible through the baseline production alert rules.
- Added security response header policy labels to
  `self_correcting_agent_build_info`, including `security_response_headers` and
  `content_security_policy_header`, so Prometheus rollout audits can compare
  live service behavior with gateway and OpenAPI expectations.
- Added trace permission policy fields to `/config`, JSON `/metrics`, and
  Prometheus `self_correcting_agent_build_info` for rollout audits of trace
  directory, trace file, and readiness probe file permissions.
- Added `X-Frame-Options: DENY` to all HTTP responses, the OpenAPI common
  response headers, runtime config/metrics audit fields, Prometheus
  `self_correcting_agent_build_info`, smoke coverage, and security/operations
  documentation for legacy frame-protection checks.
- Hardened persisted trace writes to use `0700` trace directories, owner-only
  same-directory temporary files, and final `0600` trace JSON permissions
  before atomic replacement, with regression coverage for failure cleanup and
  existing-trace preservation.
- Aligned trace persistence readiness checks with the same `0700`
  trace-directory preparation so `/ready` cannot create or leave a wider trace
  directory before traffic reaches `/run`.
- Hardened `/ready` trace persistence probes to use owner-only temporary files
  before deletion, matching persisted trace write permissions.
- Added OpenAPI `ConfigResponse` and `MetricsResponse` schema coverage for
  trace permission audit fields, keeping generated clients and gateway checks
  aligned with `/config`, `/metrics`, and Prometheus rollout surfaces.
- Added explicit container-level `seccompProfile: RuntimeDefault` to the
  Kubernetes production doctor, service, and trace-prune containers so scanner
  and admission checks do not need to infer pod-level inheritance.
- Redacted public readiness dependency failures to stable labels such as
  `trace_persistence_unavailable`, preventing `/ready` from exposing local
  filesystem paths when trace storage is misconfigured.
- Added top-level readiness `failed_checks` to expose machine-readable failing
  dependency names for probes, doctor output, release automation, and OpenAPI
  generated clients.
- Added `readiness_failed` as a stable readiness error code so `/ready` 503
  responses are counted in access logs, JSON metrics, and Prometheus error-code
  counters without exposing dependency exception details.

## 2026-06-22

- Started the Codex-style non-coding agent runtime track while preserving the
  existing deterministic LangGraph `/run` path.
- Added `llm_provider.py` with redacted OpenAI-compatible provider config,
  timeout validation, a stdlib chat-completions client, and `FakeLLMProvider`
  for no-network tests.
- Added strict runtime plan types and parser coverage for LLM JSON actions,
  including stable validation errors for malformed or incomplete plans.
- Added a generic runtime tool registry with safe local `note` and
  `transform_text` tools, structured observations, and input error codes.
- Added a runtime policy gate that blocks disallowed tools before execution and
  returns `requires_approval` observations for human-in-the-loop workflows.
- Added `run_runtime_agent()` as the first Codex-style orchestration slice:
  provider planning, plan parsing, policy authorization, tool execution,
  events, plans, and observations.
- Added `POST /runtime/run` as a separate HTTP surface for the Codex-style
  runtime, preserving the deterministic `/run` API while reusing the same HTTP
  trust boundary and OpenAPI contract machinery.
- Added redacted LLM provider audit fields to `/config`, JSON `/metrics`,
  Prometheus `self_correcting_agent_build_info`, and the OpenAPI
  `ConfigResponse`/`MetricsResponse` schemas so deployments can verify provider
  wiring without exposing API keys.
- Added bounded multi-iteration planning to the Codex-style runtime. Python and
  HTTP callers can set `max_iterations`, planner prompts receive prior
  observations, and responses include both the latest `plan` and full `plans`
  sequence for auditability.
- Added optional planner `final_answer` parsing and top-level runtime `answer`
  responses so successful Codex-style runs can return a client-ready result,
  not only tool observations.
- Added runtime tool `input_schema` metadata and included it in planner prompts
  so LLM plans receive machine-readable tool argument contracts.
- Added `/runtime/run` trace persistence through the existing owner-only trace
  store, including `trace_path`, `X-Trace-Path`, OpenAPI coverage, and stable
  `trace_persistence_failed` error handling.
- Aligned `/runtime/run` with the service `max_goal_chars` boundary so the
  Codex-style runtime cannot bypass the same oversized-goal protection as
  `/run`.
- Added `GET /runtime/tools` as a protected diagnostic discovery endpoint for
  Codex-style runtime tool descriptions and `input_schema` contracts.
- Added action-level approval resume for the Codex-style runtime:
  policy-denied actions now return `pending_approval`, and callers can resubmit
  reviewed action IDs through `approved_action_ids`.
- Added `POST /runtime/resume` to load persisted pending runtime traces by
  `run_id`, apply reviewed `approved_action_ids`, and persist resumed results
  with `resumed_from_run_id`.
- Added `GET /runtime/runs/{run_id}` for compact persisted runtime status
  summaries, with metrics path normalization to avoid high-cardinality run IDs.
- Added `GET /runtime/runs` to list recent persisted runtime status summaries
  with a bounded `limit` query parameter for dashboards and operator triage.
- Added explicit `trace_type: "codex_runtime"` markers to Codex-style runtime
  traces. Runtime status, list, and resume endpoints now ignore non-runtime
  trace JSON files, and list limits are applied after trace-type filtering.
- Scoped idempotency cache entries by execution route and documented
  `Idempotency-Key` for `/runtime/run` and `/runtime/resume`, preventing a
  retry key/body pair from reusing a response across incompatible run surfaces.
- Added a built-in `task_list` runtime tool with strict input schema,
  normalized statuses/priorities, owner and due fields, status counts, service
  execution coverage, and default policy approval for non-coding planning
  workflows.
- Added execution-time validation for runtime tool `input_schema` contracts,
  including required fields, enum values, arrays, nested objects, and rejection
  of undeclared properties before tool handlers run.
- Added `plan_count`, `observation_count`, and `event_count` to compact runtime
  status/list summaries and OpenAPI schemas for dashboard triage without
  exposing full trace internals.
- Added bounded self-correction for runtime tool failures: failed tool
  observations are fed into the next planner iteration while budget remains,
  and exhausted failures still return `failed`.
- Added HTTP `plan_sequence` support for deterministic `/runtime/run` replay of
  multi-iteration correction loops, with request validation and OpenAPI schema
  coverage.
- Hardened runtime plan parsing to reject duplicate action IDs inside a plan,
  preserving unambiguous approval, resume, event, and observation correlation.
- Hardened runtime plan parsing to reject action IDs and tool names with
  surrounding whitespace, preventing visually ambiguous approval and trace
  correlation handles.
- Added `SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS` as a service-level cap
  for `/runtime/run` and `/runtime/resume`, with env/CLI/config/metrics/OpenAPI
  and deployment documentation coverage.
- Applied `SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS` to `/runtime/run` and
  `/runtime/resume` as whole-execution timeouts, returning structured
  `504 agent_run_timeout` responses and documenting the OpenAPI contract.
- Hardened persisted runtime trace reads: `GET /runtime/runs` now skips
  unreadable trace files, while `GET /runtime/runs/{run_id}` and
  `POST /runtime/resume` return structured `500 trace_read_failed` responses
  without leaking local paths or raw parser details.
- Added an `artifact` Codex-style runtime tool for structured non-coding
  outputs such as reports, plans, decisions, data, and messages. It exposes a
  strict `input_schema`, stable `artifact_id`, normalized tags, byte counts,
  service execution coverage, and default policy authorization.
- Added a `decision_matrix` Codex-style runtime tool for weighted tradeoff
  decisions, including `number` support in runtime tool schema validation,
  deterministic ranking output, service execution coverage, and documentation.
- Added action-level timing metadata to Codex-style runtime tool observations
  and executor events (`started_at`, `completed_at`, and `duration_seconds`),
  then documented the fields in OpenAPI, architecture, and operations docs.
- Extended action-level timing to planner and policy runtime events and to
  policy-denied `requires_approval` observations, giving traces complete
  provider, policy, and tool timing coverage.
- Added run-level `duration_seconds` to Codex-style runtime responses and
  compact persisted status/list summaries, with OpenAPI and runbook coverage.
- Added compact runtime status diagnostics: `failed_observation_count`,
  `approval_required_count`, and `tool_names`, allowing dashboards to triage
  failures, approval queues, and tool clusters without reading full traces.
- Promoted terminal tool failure details to top-level runtime `error_code` and
  `error` when iteration budget is exhausted, while preserving corrected
  failures only in observations.
- Added `artifact_count` and `artifact_ids` to compact runtime status/list
  summaries so non-coding deliverables produced by the `artifact` tool are
  discoverable without opening full trace observations.
- Added `/runtime/runs` filters for `status=failed`, `tool=artifact`, and
  `has_artifacts=true`, applying `limit` only after trace type and dashboard
  filters so operators can list the most recent matching runtime runs.
- Added `GET /runtime/runs/{run_id}/artifacts/{artifact_id}` so downstream
  systems can retrieve one persisted non-coding artifact by ID without loading
  full runtime traces.
- Split request path metrics for runtime artifact lookups into
  `/runtime/runs/{run_id}/artifacts/{artifact_id}` instead of folding them into
  runtime status metrics.
- Added `trace_path` to runtime artifact lookup responses so fetched
  deliverables remain auditable without requiring full trace payloads.
- Added `GET /runtime/runs/{run_id}/artifacts` for content-free artifact
  metadata manifests, giving downstream systems a light discovery step before
  fetching individual deliverables.
- Added `GET /runtime/runs/{run_id}/timeline` for compact persisted runtime
  timelines that expose planner, policy, executor, and observation statuses
  without full tool inputs or outputs.
- Added runtime tool `minLength` schema metadata and executor validation for
  non-empty string arguments, keeping planner-visible contracts aligned with
  runtime enforcement.
- Added runtime tool `maxLength` schema metadata and executor validation for
  bounded text arguments, reducing risk from oversized tool inputs in traces
  and responses.
- Added runtime tool `maxItems` schema metadata and executor validation for
  bounded array arguments such as artifact tags, decision criteria/options, and
  task lists.
- Added runtime tool numeric `minimum`/`maximum` schema validation and exposed
  non-negative decision weights in the default `decision_matrix` contract.
- Added `MAX_PLAN_ACTIONS` enforcement for strict Codex-style runtime plans so
  oversized planner responses fail as `invalid_plan` before approval, tracing,
  or tool execution.
- Added `MAX_ACTION_REASON_CHARS` and `MAX_PLAN_FINAL_ANSWER_CHARS` enforcement
  so planner metadata remains bounded and long-form outputs flow through typed
  artifacts.
- Added runtime tool `boolean` schema validation and a built-in `rubric_score`
  tool for structured pass/fail self-review with score percentages, failed
  criteria, and blocking failure summaries.
- Added explicit plan size and metadata limits to the Codex-style planner
  system prompt so model providers see the same constraints enforced by the
  parser.
- Added CLI `--runtime`, `--runtime-plan`, `--max-iterations`, and runtime
  tool discovery support so the Codex-style runtime can be executed directly
  from local and CI automation without starting the HTTP service.
- Added planner invalid-output self-correction: parse failures and invalid plan
  shapes now become `invalid_plan` observations and can trigger another planner
  iteration while `max_iterations` budget remains.
- Added `planner_failure_count` and `tool_failure_count` to compact runtime
  status/list summaries and OpenAPI so dashboards can distinguish planner
  repair loops from tool execution failures.
- Compacted previous observations before replanning prompts: artifact outputs
  now retain metadata with `content_omitted=true` instead of replaying full
  artifact bodies to the provider.
- Added generic long-string compaction for replanning prompts using
  `text_prefix`, `original_chars`, and `truncated_chars`, while preserving full
  observation values in traces and responses.
- Exposed `prompt_observation_compaction` in runtime responses and OpenAPI so
  clients can see the active prompt observation compaction policy.
- Added optional action-level `depends_on` references for strict runtime plans,
  validated against prior action IDs so dependency mistakes fail as
  `invalid_plan`.
- Added `dependency_edge_count` to compact runtime status/list summaries and
  OpenAPI so dashboards can track plan dependency complexity without loading
  full traces.
- Added `latest_plan_action_count` and `latest_plan_action_ids` to compact
  runtime status/list summaries and OpenAPI so dashboards can show current plan
  shape without loading full trace bodies.
- Tightened strict runtime plan parsing so unknown top-level plan fields,
  unknown action fields, and self-dependencies fail as `invalid_plan` instead
  of being silently ignored.
- Added runtime tool `output_schema` metadata to default tool specs, planner
  prompts, `/runtime/tools`, CLI tool discovery, and OpenAPI so planners and
  clients can reason about structured observations before execution.
- Added execution-time validation for runtime tool `output_schema` contracts;
  malformed handler outputs now return `invalid_tool_output` observations and
  can trigger bounded replanning.
- Added `error_code_counts` to compact runtime status/list summaries and
  OpenAPI so dashboards can group planner, tool, approval, and trace failure
  causes without loading full trace bodies.
- Added `/runtime/runs?error_code=...` filtering and OpenAPI coverage so
  operators can list recent runs for one compact error-code family after trace
  type filtering and before applying `limit`.
- Added compact `artifact_kinds` summaries plus `/runtime/runs?artifact_kind=...`
  filtering and OpenAPI coverage so operators can find report, plan, decision,
  data, or message deliverable runs without opening full traces.
- Added compact `artifact_formats` summaries plus
  `/runtime/runs?artifact_format=...` filtering and OpenAPI coverage so
  operators can find markdown, plain text, or JSON deliverable runs without
  opening full traces.
- Added compact `artifact_tags` summaries plus `/runtime/runs?artifact_tag=...`
  filtering and OpenAPI coverage so operators can find tagged deliverable runs
  without opening full traces.
- Added `/runtime/runs?has_errors=true|false` filtering and OpenAPI coverage so
  operators can separate runs with observation-level `error_code_counts` or
  run-level `error_code` values from clean runs before opening full traces.
- Added compact `artifact_total_bytes` and `artifact_bytes_by_kind` summaries
  to status/list responses and OpenAPI so dashboards can triage artifact volume
  by deliverable category without loading full artifact content.
- Added dependency-aware policy/executor event metadata for dependent runtime
  actions: events now include `depends_on` and compact `dependency_statuses` so
  operators can reconstruct execution prerequisites without loading tool
  outputs.
- Tightened runtime approval validation so `approved_action_ids` must be unique,
  non-empty action IDs without surrounding whitespace, and `/runtime/resume`
  accepts only the current pending approval action from the persisted trace.
- Added approval audit metadata to runtime responses and compact status/list
  summaries via `approved_action_count` and `approved_action_ids`, preserving
  reviewed action evidence without opening full traces.
- Added `/runtime/runs?has_approvals=true|false` filtering and OpenAPI coverage
  so operators can list runs with or without human-approved actions from
  compact approval audit summaries.
- Added `/runtime/runs?approved_action_id=...` filtering and OpenAPI coverage
  so operators can trace one reviewed action ID across compact persisted runs.
- Added `/runtime/runs?resumed_from_run_id=...` filtering and OpenAPI coverage
  so operators can find resumed attempts linked to an original pending runtime
  run.
- Added compact `pending_approval_action_id` and `pending_approval_tool`
  summaries plus `/runtime/runs` filters for each field, allowing approval
  queues to be partitioned without opening full traces.
- Added `/runtime/runs?latest_failed_action_id=...` filtering and OpenAPI
  coverage so failure triage can jump from a compact run list to the exact
  failed action without opening each trace.
- Added `/runtime/runs?has_failures=true|false` filtering and OpenAPI coverage
  so operators can separate failed observations from run-level-only errors.
- Added runtime-specific metrics counters for run statuses, failed
  observations, approval-required observations, and failed budget exhaustions
  across `/metrics` and `/metrics.prom`.
- Hardened runtime plan parsing for real LLMs by extracting the final
  plan-shaped JSON object from model prefaces, examples, or think-style text
  while keeping strict schema validation.
- Added a policy-gated `http_request` runtime tool for approved HTTP GET
  fetches with bounded response bytes, response metadata, and text output.
- Added a direct `open_url` runtime tool for local CLI sessions so browser-open
  requests use Google Chrome automation instead of `http_request`.
- Added `self-correcting-agent-doctor --require-runtime-provider` so
  provider-backed production gates reject missing LLM base URL, model, API key,
  or one-iteration runtime budgets before a Codex-style runtime deployment is
  promoted.
- Added deterministic `run_checks.sh` coverage for the runtime provider doctor
  gate, plus production, operations, deployment, and README documentation for
  pairing the static gate with `scripts/smoke_real_llm_runtime.sh`.
- Added configurable OpenAI-compatible provider retries for transient 429 and
  5xx responses, including redacted config/metrics/OpenAPI audit fields,
  deployment env examples, and regression coverage that non-transient 400
  errors are not retried.
- Hardened the policy-gated `http_request` runtime tool with SSRF defense in
  depth: approved fetches now reject localhost, private, loopback, link-local,
  multicast, reserved, and unresolved targets before opening a socket.
- Disabled automatic redirect following in `http_request` so approved public
  URLs cannot silently hop to blocked private or metadata targets; 3xx responses
  are now returned as bounded observations.
- Added Codex-style runtime run duration histograms to JSON metrics and
  Prometheus exposition so operators can graph runtime latency separately from
  HTTP transport latency and the deterministic `/run` path.
- Added `SelfCorrectingAgentSlowRuntimeRuns` Prometheus alerting plus operations,
  deployment, production-readiness, and regression-test coverage so runtime
  latency is part of the production paging surface.
- Verified a real OpenAI-compatible provider end to end with the live runtime
  smoke: CLI runtime planning, HTTP `/runtime/run`, persisted trace status,
  approval/resume, and runtime metrics all passed without storing provider
  credentials in the repository.
- Added per-tool runtime timeout enforcement with planner-visible
  `timeout_seconds`, structured `tool_execution_timeout` observations, OpenAPI
  contract coverage, and operator documentation so slow tool handlers can feed
  bounded replanning instead of blocking a Codex-style runtime run.
- Added runtime observation error-code metrics across JSON `/metrics`,
  Prometheus exposition, runtime route aggregation, and baseline alerting for
  `tool_execution_timeout`, giving operators stable live counters for runtime
  tool, planner, and approval failure classes.
- Added internal company bearer-token subjects via
  `SELF_CORRECTING_SERVICE_AUTH_TOKENS`, with redacted `auth_subject` access-log
  audit fields, per-subject rate-limit isolation, production doctor acceptance,
  and `/config`/Prometheus `auth_subject_count` audit visibility without
  logging or returning raw tokens.
- Added `POST /runtime/runs/{run_id}/cancel` for subject-scoped cleanup of
  non-terminal Codex-style runtime traces, including pending approval removal,
  `cancelled_by_auth_subject` audit metadata, OpenAPI coverage, low-cardinality
  metrics path normalization, operations docs, and internal runtime smoke
  coverage.
- Added bounded non-secret runtime `metadata` and `tags` on `/runtime/run`,
  with secret-like key rejection, persisted compact status fields,
  `/runtime/runs` and summary filtering, `tag_counts` and
  `metadata_key_counts` aggregates, OpenAPI coverage, operations docs, and
  internal runtime smoke validation.
- Added status-aware runtime trace retention to
  `self-correcting-agent-trace-prune --runtime-only`, defaulting to old
  `done`, `failed`, and `cancelled` traces while protecting
  `requires_approval`; run checks, Kubernetes CronJob, deployment docs, and
  operations docs now verify the dry-run-first audit fields.
- Added stale pending-approval operations support with
  `min_pending_age_seconds`, `pending_age_seconds`, `stale_pending_count`, and
  `max_pending_age_seconds` across runtime approval APIs, OpenAPI, internal
  smoke, architecture, and operations docs so operators can find old approval
  work before cancelling or escalating it.
- Upgraded provider smoke evidence to schema version `1`, carrying redacted
  `provider_snapshot` and `capability_checks` through readiness audit and
  release evidence without writing raw provider keys or full base URLs.
- Added current pending-approval gauges for `/metrics` and `/metrics.prom`,
  including queue size, stale queue size, max pending age, and stale threshold;
  deployment defaults, Prometheus alerting, Grafana, observability acceptance,
  operations docs, and internal smoke now cover stale approval monitoring.
- Added release-evidence secret scanning for external production evidence
  files; secret-like keys or values now block approval with
  `evidence_secret_detected` while reporting only redacted evidence label,
  JSON path, and reason findings.
- Moved the same external-evidence secret scan into
  `scripts/production_readiness_audit.py`, so provider, staging,
  observability, and rollout evidence are rejected before final release
  evidence generation if they contain secret-like keys or values.
- Hardened provider smoke evidence semantics: strict gates now require schema
  version `1`, approval/CLI/HTTP/resume run IDs, redacted provider snapshot
  fields, and `capability_checks` for `cli_runtime`, `http_runtime`,
  `trace_status`, `timeline`, `approval_resume`, and `metrics`; incomplete
  passing evidence is downgraded to `invalid_evidence`.
- Extended strict external evidence semantics to staging acceptance,
  observability acceptance, and internal rollout sign-off, so empty or
  underspecified `passed` JSON can no longer satisfy readiness audit or release
  evidence gates.
- Improved the strict production approval bundle preflight to report all missing
  external evidence files at once as structured `evidence_missing` JSON.
- Versioned staging acceptance, observability acceptance, and internal rollout
  evidence as schema `1`, and made strict readiness/release gates reject
  passing evidence without `evidence_schema_version`.
- Added `approval_required_by_default` to Codex-style runtime tool metadata,
  OpenAPI, CLI verbose discovery, HTTP `/runtime/tools`, and planner prompts so
  internal clients and planners can predict human approval paths.
- Added `/runtime/policy` `effective_tool_policy`, expanding the active
  default/global/subject runtime policy into per-tool `allowed` and
  `approval_required` flags for internal approval UIs and rollout audits.
- Tightened staging acceptance and strict release evidence so staging promotion
  must prove the deployed `/runtime/policy` effective tool policy, including
  direct `note` execution and approval-gated `http_request`.
- Added internal runtime client policy filtering with `--tool` and
  `--approval-required`, plus readiness-audit markers so packaged examples keep
  supporting single-tool approval-boundary checks for internal operators.
- Added `effective_tool_policy_sha256` to `/runtime/policy` and strict staging
  evidence, giving rollout approvals a stable fingerprint for the current
  subject's effective runtime tool boundary.
- Added a redacted `runtime_policy` summary to `self-correcting-agent-doctor`
  and `run_checks.sh` coverage for its `effective_tool_policy_sha256`, tying
  deployment preflight artifacts to staging policy evidence.
- Required internal rollout sign-off and strict internal rollout evidence to
  carry `runtime_effective_tool_policy_sha256`, binding human approval to the
  reviewed runtime tool boundary.
- Added `runtime_effective_tool_policy_sha256` to provider-backed runtime smoke
  evidence and strict provider smoke validation, binding live model evidence to
  the same reviewed runtime tool boundary.
- Bounded `POST /runtime/runs/{run_id}/cancel` reasons to 500 characters across
  server validation, OpenAPI, architecture, operations docs, and tests so
  operator-visible cancellation audit fields cannot inflate persisted runtime
  traces.
- Scoped `POST /runtime/runs/{run_id}/cancel` idempotency to the concrete
  `run_id`, preventing one operator retry key from replaying the wrong
  cancellation response across different pending runtime runs.
- Made `scripts/production_approval_bundle.sh --strict` the documented release
  automation entrypoint and added structured `unknown_argument` failures for
  unsupported script arguments before evidence files are inspected.
- Added structured `release_manifest_missing` preflight failures to
  `scripts/production_approval_bundle.sh --strict`, so approval automation does
  not fall through to downstream readiness or release-evidence errors when the
  standard gate manifest is absent.
- Added structured `evidence_max_age_invalid` failures to the strict production
  approval bundle when `SELF_CORRECTING_EVIDENCE_MAX_AGE_SECONDS` is not a
  positive integer, keeping release-window configuration errors machine-readable.
- Made strict production approval continue through failed readiness and release
  evidence checks when evidence files are present but semantically invalid,
  printing a redacted `status: "blocked"` stdout summary with `failed_checks`
  before exiting with code 1.
