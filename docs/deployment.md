# Deployment

This project ships as a Python package and as a small HTTP service container.
The service is intentionally dependency-light: the Docker image installs the
package, runs as a non-root user, exposes port `8000`, and uses the built-in
`HEALTHCHECK` against `/ready`.

## Docker

Build the image:

```sh
docker build -t kagent:local .
```

Run the service:

```sh
docker run --rm \
  --env-file deploy/env.example \
  -p 8000:8000 \
  kagent:local
```

Check readiness:

```sh
curl -s http://127.0.0.1:8000/health
curl -I http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/ready
curl -s http://127.0.0.1:8000/metrics
curl -s http://127.0.0.1:8000/metrics.prom
kagent-doctor --trace-dir /tmp/kagent-traces
```

For externally exposed deployments, enforce bearer auth in the self-check:

```sh
kagent-doctor --require-auth --trace-dir /tmp/kagent-traces
```

For production release gates, use the stronger policy check:

```sh
kagent-doctor --production --trace-dir /tmp/kagent-traces
```

`--production` fails unless bearer auth, diagnostic endpoint protection, trace
persistence, per-client rate limiting, and bounded run concurrency are
configured. It also rejects common placeholder bearer tokens with
`auth_token_placeholder`.
For deployments that depend on real Codex-style runtime planning, add the
provider gate:

```sh
# KAGENT_LLM_BASE_URL, KAGENT_LLM_API_KEY, and KAGENT_LLM_MODEL
# must already be set in your shell or secret manager.
KAGENT_SERVICE_RUNTIME_MAX_ITERATIONS=2 \
kagent-doctor --production --require-runtime-provider \
  --trace-dir /tmp/kagent-traces
```

This rejects missing provider settings with `llm_base_url_required`,
`llm_model_required`, or `llm_api_key_required`, and rejects one-iteration
runtime budgets with `runtime_iterations_too_low`.

## Runtime Configuration

The service reads these environment variables:

- `KAGENT_SERVICE_HOST`: bind host, default `127.0.0.1`.
- `KAGENT_SERVICE_PORT`: bind port, default `8000`.
- `KAGENT_SERVICE_MAX_REQUEST_BYTES`: maximum request body size,
  default `65536`.
- `KAGENT_SERVICE_MAX_GOAL_CHARS`: maximum accepted `/run` goal text
  length, default `4096`.
- `KAGENT_SERVICE_AUTH_TOKEN`: optional bearer token for `POST /run`.
  Use `kagent-doctor --require-auth` in release automation when
  this service is reachable outside localhost, or `--production` when the gate
  should also require diagnostic endpoint protection, trace persistence, rate
  limiting, and bounded concurrency. `--require-auth` rejects placeholder tokens
  with `auth_token_placeholder`. Production gates require this token to be at least 16 characters and reject placeholders such as
  `replace-with-a-long-random-token` with `auth_token_placeholder`.
- `KAGENT_SERVICE_AUTH_TOKENS`: optional JSON object for internal
  company deployments that need multiple bearer tokens, for example
  `{"team-a":"...","ops":"..."}`. The object keys become redacted
  `auth_subject` audit labels and per-subject rate-limit keys; raw tokens are
  never logged.
- `KAGENT_SERVICE_RATE_LIMIT_PER_MINUTE`: per-client `/run` request
  limit, default `0` for disabled.
- `KAGENT_SERVICE_MAX_CONCURRENT_RUNS`: maximum in-flight `/run`
  executions, default `4`; set `0` to disable this service-level cap.
- `KAGENT_SERVICE_IDEMPOTENCY_CACHE_SIZE`: number of successful
  `POST /run` responses retained for `Idempotency-Key` retry reuse, default
  `0` for disabled.
- `KAGENT_SERVICE_IDEMPOTENCY_CACHE_PATH`: optional SQLite file for
  persistent/shared idempotency reuse across service restarts and same-volume
  replicas. Leave it empty for the in-memory per-process cache. In Kubernetes,
  place it on a `ReadWriteMany` volume if more than one replica should share
  retry responses.
- `KAGENT_SERVICE_RUNTIME_ALLOWED_TOOLS`: optional comma-separated
  allowlist for runtime tools that may execute without approval, for example
  `note,artifact,task_list`. Leave it empty for the default policy. Unknown runtime tool names fail service configuration before startup. `/config`,
  `/metrics`, and Prometheus `kagent_build_info` expose the active
  `runtime_allowed_tools` value as non-secret rollout metadata.
- `KAGENT_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT`: optional JSON
  object mapping `auth_subject` values to comma-separated tool lists or arrays
  of tool names, for example `{"team-a":"note,artifact","ops":["note"]}`.
  Subject-specific entries override the global runtime allowlist for matching
  internal bearer tokens. Unknown runtime tool names fail service configuration
  before startup, and rollout metadata exposes only
  `runtime_allowed_tools_by_subject_count`.
- `KAGENT_SERVICE_RUNTIME_MAX_ITERATIONS`: maximum accepted
  Codex-style runtime planner iterations for `/runtime/run` and
  `/runtime/resume`, default `10`.
- `KAGENT_SERVICE_RUNTIME_PENDING_APPROVAL_STALE_SECONDS`: age
  threshold used by `/metrics` and `/metrics.prom` stale pending approval
  gauges, default `3600`.
- `KAGENT_SERVICE_ALLOW_FULL_TRACE_RESPONSE`: whether
  `full_trace=true` may return complete internal trace bodies over HTTP,
  default `false`. Keep this disabled for normal production traffic and use
  persisted trace files for operator debugging.
- `KAGENT_SERVICE_PROTECT_DIAGNOSTICS`: whether diagnostic GET
  endpoints require the configured bearer token, default `false`. Production
  doctor gates require this to be `true`; health, readiness, and version
  probes remain public.
- `KAGENT_SERVICE_TRUST_FORWARDED_FOR`: whether rate limiting trusts
  `X-Forwarded-For`, default `false`; enable only behind a trusted reverse proxy.
- `KAGENT_SERVICE_TRACE_DIR`: optional directory for persisted full
  run traces. When set, `/ready` validates that the directory can be created
  and written, `/run` responses include `trace_path`, and trace files are
  atomically replaced after a successful temporary-file write.
- `KAGENT_SERVICE_RUNTIME_WORKSPACE_DIR`: optional root for the runtime
  virtual workspace. When set, `/ready` creates and validates owner-only
  `workspace`, `reports`, `logs`, `policies`, and `memories` directories.
  Use this for production deployments that need agent-generated reports,
  policy snapshots, logs, or memory assets to survive process restarts.
- `KAGENT_REDIS_URL`: optional `redis://` endpoint for short-term memory.
  When set, `/ready` sends a real Redis `PING`, `/config` reports
  `redis_short_term_memory=enabled` without exposing the URL, and the runtime
  can use `memory_put` / `memory_get`.
- `KAGENT_MILVUS_URL`: optional Milvus HTTP base URL for long-term semantic
  memory, for example `http://milvus:19530`. When set, `/ready` requires a 2xx
  response from the configured URL, `/config` reports
  `milvus_long_term_memory=enabled`, and the runtime can use
  `memory_upsert` / `memory_search` with explicit embedding vectors.
- `KAGENT_EMBEDDING_BASE_URL`: optional OpenAI-compatible embedding endpoint
  base URL. When omitted, kagent falls back to `KAGENT_LLM_BASE_URL` for
  embedding requests.
- `KAGENT_EMBEDDING_API_KEY`: optional embedding bearer token. When omitted,
  kagent falls back to `KAGENT_LLM_API_KEY`. `/config` only reports whether a
  key is configured.
- `KAGENT_EMBEDDING_MODEL`: embedding model name used by `memory_remember` and
  `memory_recall`, for example `text-embedding-nomic-embed-text-v1.5`.
- `KAGENT_EMBEDDING_TIMEOUT_SECONDS`: embedding request timeout, default `30`.
- `KAGENT_KAFKA_AUDIT_URL`: optional HTTP health endpoint for the Kafka audit
  path or Kafka REST proxy. When set, `/ready` requires a 2xx response and
  `/config` reports `kafka_audit_sink=enabled`. `/runtime/run` and
  `/runtime/resume` also send redacted planner, policy, tool, approval, and
  run-completion progress events to this endpoint.
- `KAGENT_KAFKA_AUDIT_TOPIC`: optional audit topic name. `/config` reports only
  whether it is configured.
- `KAGENT_EXTERNAL_BACKEND_TIMEOUT_SECONDS`: readiness timeout for Redis,
  Milvus, and Kafka probes, default `2`.
- `KAGENT_SERVICE_RUN_TIMEOUT_SECONDS`: maximum wall-clock time for
  one execution route (`/run`, `/runtime/run`, or `/runtime/resume`) before
  returning `504`, default `30`.
- `KAGENT_SERVICE_REQUEST_TIMEOUT_SECONDS`: maximum time to read a
  complete HTTP request before returning a structured slow-client timeout,
  default `10`.
- `KAGENT_LLM_PROVIDER`: provider hint for non-interactive deployments.
  Supported values are `openai_compatible`, `deepseek`, `qwen`, and `ollama`.
  Interactive setup asks the operator to choose this provider from a menu before
  collecting Base URL, model, and API key. When omitted in environment-only
  setups, kagent infers the provider from the Base URL and model when possible.
- `KAGENT_LLM_BASE_URL`: provider base URL. For current production adapters,
  use an OpenAI-compatible `/v1` endpoint.
- `KAGENT_LLM_API_KEY`: provider bearer token.
- `KAGENT_LLM_MODEL`: chat-completions model name.
- `KAGENT_LLM_TIMEOUT_SECONDS`: provider request timeout, default
  `30`.
- `KAGENT_LLM_MAX_RETRIES`: transient 429 and 5xx provider retry
  count, default `2`.
- `KAGENT_LLM_RETRY_BACKOFF_SECONDS`: fixed sleep between provider
  retry attempts, default `0.25`. Numeric provider `Retry-After` response
  headers take precedence for retryable HTTP failures.
- `KAGENT_MAX_STEPS`: default max planned steps per run.
- `KAGENT_MAX_RETRIES`: default per-step retry budget.

When `KAGENT_SERVICE_AUTH_TOKEN` is set, callers must send:

```sh
Authorization: Bearer <token>
```

## systemd

For VM or bare-metal deployments, use
`deploy/systemd/kagent.service` as a starting point. Install the
package into `/opt/kagent/.venv`, copy
`deploy/env.example` to `/etc/kagent.env`, adjust values, then
enable the unit with systemd. The unit runs with `Restart=on-failure` and basic
process hardening flags. It also runs
`kagent-doctor --production` as `ExecStartPre`, so the service
will not start until `/etc/kagent.env` provides bearer auth,
trace persistence, per-client rate limiting, and bounded run concurrency.
The unit declares `StateDirectory=kagent` and
`ReadWritePaths=/var/lib/kagent`, then uses `ProtectSystem=strict`
so persisted traces and runtime workspace assets have an explicit writable
state boundary. The unit passes `--trace-dir /var/lib/kagent/traces` and
`--runtime-workspace-dir /var/lib/kagent/runtime-workspace` to both the
production doctor and the service process so trace persistence and the virtual
workspace are validated before startup and used at runtime.
It also sets `UMask=0077` so newly written trace and state files default to
owner-only permissions.
The unit also defines process sandbox boundaries with an empty
`CapabilityBoundingSet`, `PrivateDevices=true`, `LockPersonality=true`, and
`RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`.
It also protects kernel and control-group surfaces, restricts SUID/SGID and
realtime scheduling, and pins syscall architecture to the native platform.
The unit declares cgroup resource boundaries with `MemoryMax=1G`,
`CPUQuota=100%`, and `TasksMax=64`; tune these values for larger production
hosts after observing `/metrics` and supervisor memory pressure.
The unit sets `TimeoutStopSec=45`, which is longer than the default
`KAGENT_SERVICE_RUN_TIMEOUT_SECONDS=30`, so systemd gives the service
time to handle `SIGTERM`, close the HTTP server, and let bounded runs finish
before sending a final kill signal.

## Kubernetes

Use `deploy/kubernetes/kagent.yaml` as a production-oriented
cluster starting point:

```sh
kubectl apply -f deploy/kubernetes/kagent.yaml
```

Before applying it to a real cluster, replace
`KAGENT_SERVICE_AUTH_TOKEN` in the Secret with a long random token and
update the image reference to an immutable registry tag. The checked-in
`replace-with-a-long-random-token` value is intentionally a deployment
placeholder; the initContainer production doctor rejects it with
`auth_token_placeholder` so the pod will not start with the example secret. The
manifest includes a ConfigMap for runtime controls, a Secret for bearer auth, a
PVC for persisted trace artifacts, a Deployment with two replicas, rolling
updates, `minReadySeconds`, `progressDeadlineSeconds`,
`topologySpreadConstraints` that prefer spreading service pods across nodes by
`kubernetes.io/hostname`, and a ClusterIP Service.

The Deployment runs `kagent-doctor --production` as an
initContainer before the service starts. The service container uses a
`startupProbe` against `/ready` so cold starts, trace PVC setup, and readiness
dependency checks can finish before liveness restarts are considered. When
`KAGENT_SERVICE_IDEMPOTENCY_CACHE_PATH` is set, both the production
doctor initContainer and `/ready` validate SQLite idempotency persistence before
traffic is accepted. Readiness and liveness probes target `/ready` and `/health`, and Prometheus scrape
annotations point at `/metrics.prom`. The trace PVC uses `ReadWriteMany`
because the manifest runs two replicas; choose a storage class that supports
multi-pod mounts or reduce replicas before applying it.
The production doctor initContainer has CPU, memory, and ephemeral-storage
requests and limits so release-gate checks remain bounded during rollout.
The Deployment uses `minReadySeconds: 5` so a pod must remain ready briefly
before rollout progress counts it as available, and
`progressDeadlineSeconds: 120` so stalled rollouts surface as failed Deployment
progress rather than hanging indefinitely.
The service and trace-prune runtime containers have ephemeral-storage requests
and limits as well, so package caches, temp files, and cleanup output stay
inside declared scheduler and eviction boundaries.
The service, initContainer, and trace-prune job mount `/tmp` from an `emptyDir`
with a `64Mi` `sizeLimit`, so temporary files cannot grow without bound on the
node filesystem.
The pod templates set `seccompProfile: RuntimeDefault` at the pod level and
repeat it on each container security context so admission policies and image
scanners can verify the runtime syscall profile without depending on inherited
defaults.
The manifest also includes a `CronJob` that runs
`kagent-trace-prune` against the same trace volume every day and
deletes old terminal Codex-style runtime trace JSON files older than 7 days
with `--runtime-only --fail-on-errors`. Runtime-only mode protects pending
`requires_approval` traces by default and reports `protected_pending` plus
`matched_by_status`. `--fail-on-errors` makes corrupt trace files or failed
deletes fail the CronJob after writing the JSON summary. Run the command without
`--delete` first when changing the retention window so operators can review the
JSON dry-run summary before applying a destructive cleanup.
The pod sets `terminationGracePeriodSeconds: 45`, which is longer than the
default `KAGENT_SERVICE_RUN_TIMEOUT_SECONDS=30`, so Kubernetes gives
the service time to handle `SIGTERM`, close the HTTP server, and let bounded
runs return controlled responses before the container is killed.

The manifest also includes a `PodDisruptionBudget` with `minAvailable: 1` for
voluntary disruption protection and a `NetworkPolicy` that permits service
ingress on port `8000` only from pods whose namespace and pod labels both set
`kagent-access: "true"`, while restricting egress to DNS and
HTTPS. Label the ingress gateway, monitoring scraper, or internal caller
namespace and pods before relying on the policy in a real cluster.

Prometheus alerting rules live in
`deploy/prometheus/kagent-rules.yaml`. Prometheus Operator
clusters can apply
`deploy/prometheus/kagent-servicemonitor.yaml` to scrape the
ClusterIP Service through a `ServiceMonitor`; clusters without the
`monitoring.coreos.com` CRDs can continue using the pod scrape annotations in
the base Kubernetes manifest. Load the rules into your Prometheus or Prometheus
Operator rule pipeline after adjusting the `job` selector to match your scrape
configuration. The baseline rules include service availability, HTTP 5xx rate,
`kagentHighRequestLatency`, `kagentSlowAgentRuns`,
`kagentSlowRuntimeRuns`,
run timeout, failed-run, Codex-style runtime failed-run, runtime approval
pressure, runtime budget exhaustion, rate-limit, idempotency conflict,
per-subject runtime resume alerting, runtime planner failure alerting,
runtime tool failure/approval pressure, runtime tool execution timeout,
idempotency cache eviction, request body timeout,
`kagentMalformedRunRequests`,
`kagentOversizedRunRequests`, and unknown route or method alerts.
Grafana dashboard JSON for the same runtime signals lives in
`deploy/grafana/kagent-dashboard.json`; import it after the
Prometheus datasource is available to get baseline service health, HTTP error,
runtime latency, per-subject usage/outcome, resume, approval, and tool-error
panels.

## Operational Checks

Before publishing an image, run the local gate:

```sh
scripts/run_checks.sh
```

For a focused service check, run:

```sh
scripts/smoke_service.sh
```

After deployment, validate the live service:

```sh
curl -s http://127.0.0.1:8000/version
curl -s http://127.0.0.1:8000/openapi.json
curl -s http://127.0.0.1:8000/metrics.prom
curl -i -X OPTIONS http://127.0.0.1:8000/run
curl -s -X POST http://127.0.0.1:8000/run \
  -H 'Content-Type: application/json' \
  -d '{"goal":"calculate 2 + 3"}'
```

The service writes structured JSON access logs to stderr. Each record includes
`event`, `method`, `path`, `status_code`, `duration_seconds`, `request_id`, and
`remote_addr`. Clients can pass `X-Request-ID`; otherwise the service generates
one and echoes it in the response. The access log schema also reserves optional
`error_code`, `run_id`, `trace_path`, and `idempotency_key_present` fields for
failure triage, trace correlation, and retry correlation without logging raw
idempotency keys. Successful `/run` responses include `X-Run-ID`, and include
`X-Trace-Path` when trace persistence writes a trace artifact.

Set `KAGENT_SERVICE_RUN_TIMEOUT_SECONDS` below the upstream reverse
proxy timeout so slow execution routes return a controlled JSON `504` response.
Set `KAGENT_SERVICE_REQUEST_TIMEOUT_SECONDS` low enough to close
slow or incomplete HTTP requests before they hold handler threads for too long.
Set `KAGENT_SERVICE_MAX_CONCURRENT_RUNS` according to CPU and memory
capacity so slow runs cannot starve health, readiness, or metrics probes.
The service handles `SIGTERM` by closing the HTTP server and exiting with
status `143`, which lets Docker, systemd, and Kubernetes treat planned stops
separately from application crashes. Accepted requests run on bounded request threads,
and server shutdown uses `block_on_close` so the process waits for those in-flight
handlers to finish within the configured run timeout and supervisor grace window.

## Rollback

Keep image tags immutable. If a deployment fails health checks or `/metrics`
shows unexpected 4xx/5xx growth, roll back to the previous image tag and keep
the failed image available for log inspection.
