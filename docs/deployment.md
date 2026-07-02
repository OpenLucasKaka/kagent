# Deployment

This project ships as a Python package and as a small HTTP service container.
The service is intentionally dependency-light: the Docker image installs the
package, runs as a non-root user, exposes port `8000`, and uses the built-in
`HEALTHCHECK` against `/ready`.

## Docker

Build the image:

```sh
docker build -t self-correcting-langgraph-agent:local .
```

Run the service:

```sh
docker run --rm \
  --env-file deploy/env.example \
  -p 8000:8000 \
  self-correcting-langgraph-agent:local
```

Check readiness:

```sh
curl -s http://127.0.0.1:8000/health
curl -I http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/ready
curl -s http://127.0.0.1:8000/metrics
curl -s http://127.0.0.1:8000/metrics.prom
self-correcting-agent-doctor --trace-dir /tmp/self-correcting-agent-traces
```

For externally exposed deployments, enforce bearer auth in the self-check:

```sh
self-correcting-agent-doctor --require-auth --trace-dir /tmp/self-correcting-agent-traces
```

For production release gates, use the stronger policy check:

```sh
self-correcting-agent-doctor --production --trace-dir /tmp/self-correcting-agent-traces
```

`--production` fails unless bearer auth, diagnostic endpoint protection, trace
persistence, per-client rate limiting, and bounded run concurrency are
configured. It also rejects common placeholder bearer tokens with
`auth_token_placeholder`.
For deployments that depend on real Codex-style runtime planning, add the
provider gate:

```sh
SELF_CORRECTING_LLM_BASE_URL="${PROVIDER_BASE_URL}" \
SELF_CORRECTING_LLM_API_KEY="${PROVIDER_API_KEY}" \
SELF_CORRECTING_LLM_MODEL="agent-runtime-model" \
SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS=2 \
self-correcting-agent-doctor --production --require-runtime-provider \
  --trace-dir /tmp/self-correcting-agent-traces
```

This rejects missing provider settings with `llm_base_url_required`,
`llm_model_required`, or `llm_api_key_required`, and rejects one-iteration
runtime budgets with `runtime_iterations_too_low`.

## Runtime Configuration

The service reads these environment variables:

- `SELF_CORRECTING_SERVICE_HOST`: bind host, default `127.0.0.1`.
- `SELF_CORRECTING_SERVICE_PORT`: bind port, default `8000`.
- `SELF_CORRECTING_SERVICE_MAX_REQUEST_BYTES`: maximum request body size,
  default `65536`.
- `SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS`: maximum accepted `/run` goal text
  length, default `4096`.
- `SELF_CORRECTING_SERVICE_AUTH_TOKEN`: optional bearer token for `POST /run`.
  Use `self-correcting-agent-doctor --require-auth` in release automation when
  this service is reachable outside localhost, or `--production` when the gate
  should also require diagnostic endpoint protection, trace persistence, rate
  limiting, and bounded concurrency. `--require-auth` rejects placeholder tokens
  with `auth_token_placeholder`. Production gates require this token to be at least 16 characters and reject placeholders such as
  `replace-with-a-long-random-token` with `auth_token_placeholder`.
- `SELF_CORRECTING_SERVICE_AUTH_TOKENS`: optional JSON object for internal
  company deployments that need multiple bearer tokens, for example
  `{"team-a":"...","ops":"..."}`. The object keys become redacted
  `auth_subject` audit labels and per-subject rate-limit keys; raw tokens are
  never logged.
- `SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE`: per-client `/run` request
  limit, default `0` for disabled.
- `SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS`: maximum in-flight `/run`
  executions, default `4`; set `0` to disable this service-level cap.
- `SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_SIZE`: number of successful
  `POST /run` responses retained for `Idempotency-Key` retry reuse, default
  `0` for disabled.
- `SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_PATH`: optional SQLite file for
  persistent/shared idempotency reuse across service restarts and same-volume
  replicas. Leave it empty for the in-memory per-process cache. In Kubernetes,
  place it on a `ReadWriteMany` volume if more than one replica should share
  retry responses.
- `SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS`: optional comma-separated
  allowlist for runtime tools that may execute without approval, for example
  `note,artifact,task_list`. Leave it empty for the default policy. Unknown runtime tool names fail service configuration before startup. `/config`,
  `/metrics`, and Prometheus `self_correcting_agent_build_info` expose the active
  `runtime_allowed_tools` value as non-secret rollout metadata.
- `SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT`: optional JSON
  object mapping `auth_subject` values to comma-separated tool lists or arrays
  of tool names, for example `{"team-a":"note,artifact","ops":["note"]}`.
  Subject-specific entries override the global runtime allowlist for matching
  internal bearer tokens. Unknown runtime tool names fail service configuration
  before startup, and rollout metadata exposes only
  `runtime_allowed_tools_by_subject_count`.
- `SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS`: maximum accepted
  Codex-style runtime planner iterations for `/runtime/run` and
  `/runtime/resume`, default `10`.
- `SELF_CORRECTING_SERVICE_RUNTIME_PENDING_APPROVAL_STALE_SECONDS`: age
  threshold used by `/metrics` and `/metrics.prom` stale pending approval
  gauges, default `3600`.
- `SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE`: whether
  `full_trace=true` may return complete internal trace bodies over HTTP,
  default `false`. Keep this disabled for normal production traffic and use
  persisted trace files for operator debugging.
- `SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS`: whether diagnostic GET
  endpoints require the configured bearer token, default `false`. Production
  doctor gates require this to be `true`; health, readiness, and version
  probes remain public.
- `SELF_CORRECTING_SERVICE_TRUST_FORWARDED_FOR`: whether rate limiting trusts
  `X-Forwarded-For`, default `false`; enable only behind a trusted reverse proxy.
- `SELF_CORRECTING_SERVICE_TRACE_DIR`: optional directory for persisted full
  run traces. When set, `/ready` validates that the directory can be created
  and written, `/run` responses include `trace_path`, and trace files are
  atomically replaced after a successful temporary-file write.
- `SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS`: maximum wall-clock time for
  one execution route (`/run`, `/runtime/run`, or `/runtime/resume`) before
  returning `504`, default `30`.
- `SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS`: maximum time to read a
  complete HTTP request before returning a structured slow-client timeout,
  default `10`.
- `SELF_CORRECTING_LLM_BASE_URL`: OpenAI-compatible provider base URL.
- `SELF_CORRECTING_LLM_API_KEY`: provider bearer token.
- `SELF_CORRECTING_LLM_MODEL`: chat-completions model name.
- `SELF_CORRECTING_LLM_TIMEOUT_SECONDS`: provider request timeout, default
  `30`.
- `SELF_CORRECTING_LLM_MAX_RETRIES`: transient 429 and 5xx provider retry
  count, default `2`.
- `SELF_CORRECTING_LLM_RETRY_BACKOFF_SECONDS`: fixed sleep between provider
  retry attempts, default `0.25`. Numeric provider `Retry-After` response
  headers take precedence for retryable HTTP failures.
- `SELF_CORRECTING_MAX_STEPS`: default max planned steps per run.
- `SELF_CORRECTING_MAX_RETRIES`: default per-step retry budget.

When `SELF_CORRECTING_SERVICE_AUTH_TOKEN` is set, callers must send:

```sh
Authorization: Bearer <token>
```

## systemd

For VM or bare-metal deployments, use
`deploy/systemd/self-correcting-agent.service` as a starting point. Install the
package into `/opt/self-correcting-langgraph-agent/.venv`, copy
`deploy/env.example` to `/etc/self-correcting-agent.env`, adjust values, then
enable the unit with systemd. The unit runs with `Restart=on-failure` and basic
process hardening flags. It also runs
`self-correcting-agent-doctor --production` as `ExecStartPre`, so the service
will not start until `/etc/self-correcting-agent.env` provides bearer auth,
trace persistence, per-client rate limiting, and bounded run concurrency.
The unit declares `StateDirectory=self-correcting-agent` and
`ReadWritePaths=/var/lib/self-correcting-agent`, then uses `ProtectSystem=strict`
so persisted traces have an explicit writable state boundary. The unit passes
`--trace-dir /var/lib/self-correcting-agent/traces` to both the production
doctor and the service process so trace persistence is validated before startup
and used at runtime.
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
`SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS=30`, so systemd gives the service
time to handle `SIGTERM`, close the HTTP server, and let bounded runs finish
before sending a final kill signal.

## Kubernetes

Use `deploy/kubernetes/self-correcting-agent.yaml` as a production-oriented
cluster starting point:

```sh
kubectl apply -f deploy/kubernetes/self-correcting-agent.yaml
```

Before applying it to a real cluster, replace
`SELF_CORRECTING_SERVICE_AUTH_TOKEN` in the Secret with a long random token and
update the image reference to an immutable registry tag. The checked-in
`replace-with-a-long-random-token` value is intentionally a deployment
placeholder; the initContainer production doctor rejects it with
`auth_token_placeholder` so the pod will not start with the example secret. The
manifest includes a ConfigMap for runtime controls, a Secret for bearer auth, a
PVC for persisted trace artifacts, a Deployment with two replicas, rolling
updates, `minReadySeconds`, `progressDeadlineSeconds`,
`topologySpreadConstraints` that prefer spreading service pods across nodes by
`kubernetes.io/hostname`, and a ClusterIP Service.

The Deployment runs `self-correcting-agent-doctor --production` as an
initContainer before the service starts. The service container uses a
`startupProbe` against `/ready` so cold starts, trace PVC setup, and readiness
dependency checks can finish before liveness restarts are considered. When
`SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_PATH` is set, both the production
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
`self-correcting-agent-trace-prune` against the same trace volume every day and
deletes old terminal Codex-style runtime trace JSON files older than 7 days
with `--runtime-only`. That mode protects pending `requires_approval` traces
by default and reports `protected_pending` plus `matched_by_status`. Run the
command without `--delete` first when changing the retention window so
operators can review the JSON dry-run summary before applying a destructive
cleanup.
The pod sets `terminationGracePeriodSeconds: 45`, which is longer than the
default `SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS=30`, so Kubernetes gives
the service time to handle `SIGTERM`, close the HTTP server, and let bounded
runs return controlled responses before the container is killed.

The manifest also includes a `PodDisruptionBudget` with `minAvailable: 1` for
voluntary disruption protection and a `NetworkPolicy` that permits service
ingress on port `8000` only from pods whose namespace and pod labels both set
`self-correcting-agent-access: "true"`, while restricting egress to DNS and
HTTPS. Label the ingress gateway, monitoring scraper, or internal caller
namespace and pods before relying on the policy in a real cluster.

Prometheus alerting rules live in
`deploy/prometheus/self-correcting-agent-rules.yaml`. Prometheus Operator
clusters can apply
`deploy/prometheus/self-correcting-agent-servicemonitor.yaml` to scrape the
ClusterIP Service through a `ServiceMonitor`; clusters without the
`monitoring.coreos.com` CRDs can continue using the pod scrape annotations in
the base Kubernetes manifest. Load the rules into your Prometheus or Prometheus
Operator rule pipeline after adjusting the `job` selector to match your scrape
configuration. The baseline rules include service availability, HTTP 5xx rate,
`SelfCorrectingAgentHighRequestLatency`, `SelfCorrectingAgentSlowAgentRuns`,
`SelfCorrectingAgentSlowRuntimeRuns`,
run timeout, failed-run, Codex-style runtime failed-run, runtime approval
pressure, runtime budget exhaustion, rate-limit, idempotency conflict,
per-subject runtime resume alerting, runtime tool execution timeout,
idempotency cache eviction, request body timeout,
`SelfCorrectingAgentMalformedRunRequests`,
`SelfCorrectingAgentOversizedRunRequests`, and unknown route or method alerts.
Grafana dashboard JSON for the same runtime signals lives in
`deploy/grafana/self-correcting-agent-dashboard.json`; import it after the
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

Set `SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS` below the upstream reverse
proxy timeout so slow execution routes return a controlled JSON `504` response.
Set `SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS` low enough to close
slow or incomplete HTTP requests before they hold handler threads for too long.
Set `SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS` according to CPU and memory
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
