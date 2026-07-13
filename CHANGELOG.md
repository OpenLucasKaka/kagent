# Changelog

## 0.1.10 - 2026-07-13

### Fixed

- Hid the main prompt placeholder while IME-safe cursor rendering is active so
  macOS Chinese preedit text no longer overlaps `Ask kagent`.
- Suppressed the empty prompt while a run is thinking and guarded against
  duplicate Enter events submitting the same prompt twice before React rerenders.
- Kept the latest user prompt visible with its assistant answer even when the
  answer is taller than the live transcript viewport.
- Removed the Ink-rendered fake prompt cursor when terminal cursor sync is
  active, and deferred cursor positioning until after Ink flushes the frame.

## 0.1.9 - 2026-07-13

### Fixed

- Kept the real terminal cursor aligned with the Ink prompt input cell so IME
  preedit text appears on the `kagent` prompt line instead of the terminal's
  lower-left corner.
- Brought already-running macOS apps to the foreground for `open_app` by using
  AppleScript activation before falling back to `open -a`.
- Normalized the common `飞书` app name to the macOS `Feishu` process name for
  `open_app`.

## 0.1.7 - 2026-07-13

### Added

- npm registry self-update checks for interactive launches, explicit
  `kagent update --check` diagnostics, and `kagent upgrade` installs with
  stable/latest and beta/next channel selection.
- Immutable, dependency- and Python ABI-keyed runtime directories with atomic
  publication and reuse across package-only version updates on macOS and Linux.
- npm release automation gated on successful main-branch CI for the exact
  tested commit, with strict npm/Python version matching and idempotent
  already-published handling.

### Changed

- CI now covers the supported Node.js 18 and 22 endpoints alongside Python 3.9
  and 3.12 without multiplying the matrix beyond two jobs.

## 0.1.0

Initial production-oriented LangGraph agent package.

### Added

- Bounded LangGraph control loop with planner, executor, verifier, reflector,
  per-step retry budget, and structured failure status.
- Deterministic tool registry for arithmetic and text operations, with
  discoverable command metadata.
- Structured traces with run metadata, events, execution attempts,
  verification results, reflections, errors, and compact summaries.
- Planner preview mode, graph topology introspection, version introspection,
  fault injection, JSON artifact output, and automation-friendly CLI exit
  semantics.
- Batch JSONL job runner for processing multiple agent goals with per-line
  result summaries and structured bad-input records.
- Local HTTP service with `GET /health`, `POST /run`, structured JSON errors,
  and a `kagent-serve` console script.
- Production service hardening with request size limits, optional bearer auth,
  request ID propagation, structured access logs, `/metrics`, and OpenAPI
  discovery.
- Docker runtime, `.dockerignore`, deployment documentation, and environment
  example for containerized service operation.
- Real service smoke script wired into `scripts/run_checks.sh` so the standard
  gate starts the HTTP service and exercises `/health`, `/run`, and `/metrics`.
- Optional service trace artifact persistence through
  `KAGENT_SERVICE_TRACE_DIR`.
- Trace retention pruning with `kagent-trace-prune`, runtime-only retention
  mode, pending approval protection, and `--fail-on-errors` for cron and
  Kubernetes alerting when corrupt traces or delete failures are encountered.
- GitHub Actions now runs the standard gate across Python 3.9 and 3.12.
- Dependabot configuration for Python dependencies and GitHub Actions.
- systemd unit example for VM or bare-metal deployments.
- Evaluator with workflow, tool, recovery, and failure cases; exact case and
  category filters; case discovery; trace invariant validation; and structured
  failed-case reporting.
- Continuous iteration script (`continuous iteration`) and metrics summary for
  long-running hardening, including health, consecutive passes, evaluator
  counts, recovery visibility, category counts, and triage recommendations.
- Standard project gate through `scripts/run_checks.sh`, GitHub Actions CI, and
  Makefile aliases.
- Deployment doctor production policy and systemd preflight checks for exposed
  service controls.
- Kubernetes deployment manifest with probes, runtime configuration resources,
  trace persistence storage, Prometheus scrape annotations, and pod security
  settings, plus `PodDisruptionBudget` and `NetworkPolicy` resources.
- Named OpenAPI success schemas for run, readiness, config, tools, version, and
  metrics payloads.
- `Cache-Control: no-store` response headers for runtime config, metrics,
  agent results, and structured error payloads.
- `/run` access log correlation fields for `run_id` and persisted `trace_path`.
- Structured access logs are flushed after each stderr write.
- Redacted runtime build info in `/metrics` and `kagent_build_info`
  in Prometheus output for rollout and configuration audits.
- Production HTTP server defaults for daemon request threads, address reuse,
  and explicit listen backlog.
- Graceful `SIGTERM` handling for service shutdown with exit status `143`.
- Configurable HTTP request read timeout for slow-client protection.
- OpenAPI response header documentation for request IDs, no-store caching, and
  content sniffing protection.
- `WWW-Authenticate: Bearer` headers on unauthorized service responses and
  OpenAPI 401 responses.
- `Retry-After` headers for rate-limit and `/run` concurrency rejections.
- HTTP `Server` header hardening so responses no longer expose the Python
  runtime version.
- Continuous iteration metrics now use monotonic timing for duration reporting.
- Prometheus alerting rules for service availability, HTTP errors, agent
  timeouts, failed runs, and rate limiting.
- Kubernetes termination grace period aligned with the default run timeout.
- `X-Run-ID` response headers for successful `/run` requests.
- OpenAPI response contracts for probe and integration endpoints, including
  `HEAD /health`, `OPTIONS /run`, `/metrics.prom`, and `/openapi.json`.
- systemd `TimeoutStopSec` aligned with the default run timeout for graceful
  VM and bare-metal shutdowns.
- Machine-readable access log schema documentation for required request fields
  and optional error/run trace correlation fields.
- Stable OpenAPI `operationId` values for generated clients, gateway checks,
  and live service smoke validation.
- Strict `/run` and batch record config validation so `max_steps` and
  `max_retries` reject non-integer JSON values before agent execution.
- Configurable `/run` goal length limit with stable `goal_too_large` errors,
  OpenAPI/schema documentation, deployment configuration, and smoke coverage.
- Release manifest generation with artifact names, sizes, and `sha256` hashes,
  plus manifest verification wired into the standard release gate and console
  scripts.
- Release hygiene cleanup for local build metadata after standard gates.
- Architecture and operations documentation for maintainers and operators.
- PEP 561 `py.typed` marker for downstream type checkers.
- Bounded Codex-style runtime cancel reasons to 500 characters in the service
  contract and server-side validation so cancellation audit fields stay compact.
- Scoped Codex-style runtime cancel idempotency to the concrete `run_id` so
  retry keys cannot replay cancellation responses across different runs.
- Made production approval bundle invocation explicit with `--strict` and
  structured `unknown_argument` failures for unsupported script arguments.
- Added structured `release_manifest_missing` preflight failures to the
  production approval bundle before readiness or release-evidence checks run.
- Added structured `evidence_max_age_invalid` failures when production approval
  evidence freshness configuration is not a positive integer.
- Made strict production approval bundles print redacted `status: "blocked"`
  stdout summaries for semantically invalid evidence while exiting with code 1.
- Made the CLI default to the Codex-style runtime for both `kagent` and
  `kagent "goal"`, with `--deterministic` reserved for legacy graph regression
  checks.
- Added Codex-style `*** Move to:` support to the audited runtime `apply_patch`
  tool so agents can move workspace files without shell access, with
  `previous_path` recorded for auditability.
