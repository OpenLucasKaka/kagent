# Changelog

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
  and a `self-correcting-agent-serve` console script.
- Production service hardening with request size limits, optional bearer auth,
  request ID propagation, structured access logs, `/metrics`, and OpenAPI
  discovery.
- Docker runtime, `.dockerignore`, deployment documentation, and environment
  example for containerized service operation.
- Real service smoke script wired into `scripts/run_checks.sh` so the standard
  gate starts the HTTP service and exercises `/health`, `/run`, and `/metrics`.
- Optional service trace artifact persistence through
  `SELF_CORRECTING_SERVICE_TRACE_DIR`.
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
- Redacted runtime build info in `/metrics` and `self_correcting_agent_build_info`
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
