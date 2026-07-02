# Security Policy

## Supported Versions

The actively maintained version is `0.1.x`. Security fixes should target the
current `main` branch and pass `scripts/run_checks.sh` before release.

## Reporting a Vulnerability

Report vulnerabilities privately to the project maintainer before opening a
public issue. Include:

- affected version or commit,
- reproduction steps,
- expected and observed behavior,
- relevant logs with secrets removed.

Do not include API tokens, bearer tokens, production traces, or private request
payloads in public reports.

## Runtime Controls

The HTTP service includes these production controls:

- `SELF_CORRECTING_SERVICE_AUTH_TOKEN` protects `POST /run` with bearer auth;
  bearer token checks use constant-time comparison, and failed auth responses
  include `WWW-Authenticate: Bearer`. Production doctor gates require the token
  to be at least 16 characters and reject common placeholder values such as
  `replace-with-a-long-random-token` with `auth_token_placeholder`. Malformed
  or non-ASCII `Authorization` header values are rejected as unauthorized
  instead of raising service errors, and raw HTTP requests must use a
  single-valued `Authorization` header. Production doctor gates also reject bearer
  tokens that cannot be represented as safe HTTP header values with
  `auth_token_unsafe`.
- `SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS` reuses the bearer token for
  diagnostic endpoints (`/config`, `/tools`, `/metrics`, `/metrics.prom`, and
  `/openapi.json`) while keeping health, readiness, and version probes public.
- `self-correcting-agent-doctor --require-auth` fails deployment self-checks
  when bearer auth is disabled; use it in externally exposed environments.
  `--require-auth` rejects placeholder tokens with `auth_token_placeholder`.
- `self-correcting-agent-doctor --production` fails deployment self-checks
  unless bearer auth, diagnostic endpoint protection, trace persistence, rate
  limiting, bounded concurrency, and disabled full trace HTTP responses are
  configured. Placeholder bearer tokens fail with `auth_token_placeholder`.
  Enabling full trace HTTP responses in production fails with
  `full_trace_response_must_be_disabled`.
- `SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE` limits per-client `/run`
  traffic.
- `SELF_CORRECTING_SERVICE_TRUST_FORWARDED_FOR` is disabled by default; enable
  it only behind a trusted reverse proxy that overwrites `X-Forwarded-For`.
  Empty, overlong, control-character, or non-IP unsafe `X-Forwarded-For`
  values fall back to the socket remote address before rate limiting. Valid
  forwarded client IPs are normalized to a canonical address string before
  rate-limit keys are updated.
- `SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS` caps in-flight `/run`
  executions to reduce resource exhaustion risk.
- `SELF_CORRECTING_SERVICE_MAX_REQUEST_BYTES` rejects oversized request bodies
  before the agent runs.
- Duplicate, malformed, or negative HTTP `Content-Length` headers are rejected
  before the service reads request bodies.
- Any HTTP `Transfer-Encoding` header is rejected with
  `invalid_transfer_encoding`; the service accepts only bounded
  `Content-Length` request bodies.
- Any HTTP `Expect` header is rejected with `expectation_failed`; the service
  does not support continue-style request body negotiation.
- Duplicate HTTP `Content-Type` headers are rejected before request body parsing
  or routing; `/run` requires a single-valued `application/json` header.
- `Idempotency-Key` must be single-valued so intermediaries and clients cannot
  disagree about which retry key controls response reuse.
- `SELF_CORRECTING_SERVICE_AUTH_TOKENS` subject tokens can list or inspect only
  persisted runtime traces with the same `auth_subject`; the primary service
  bearer token remains the operator/admin diagnostic token for all traces.
  Subject tokens also get subject-scoped runtime resume: they can resume only
  pending runtime traces with the same `auth_subject`, while the primary token
  can recover runs across subjects. Resumed traces preserve the original
  `auth_subject` owner and record the approver in `resumed_by_auth_subject`.
- `SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_PATH` enables SQLite-backed retry
  response reuse; readiness validates `idempotency_cache_persistence` and
  returns only stable failure labels instead of local path details.
- `SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS` restricts which Codex-style
  runtime tools can execute without approval in a deployment. Unknown tool
  names fail configuration before startup, and the active allowlist is exposed
  only as non-secret audit metadata in config and metrics.
- `SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT` applies stricter
  or broader direct-execution tool policies to specific authenticated
  `auth_subject` values. Matching subject entries override the global
  allowlist; audit surfaces expose only
  `runtime_allowed_tools_by_subject_count`, not bearer tokens.
- `SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS` bounds HTTP request reads;
  stalled request bodies return controlled `408 request_body_timeout` JSON
  errors.
- `SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS` bounds `/run` execution and
  returns controlled `504` JSON errors for slow runs.
- `SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE` is disabled by default;
  when disabled, client requests with `full_trace=true` return
  `full_trace_disabled` instead of exposing internal trace events in HTTP
  responses.
- Structured failure responses include stable `error_code` values so clients
  and alerts can branch without parsing human-readable messages.
- `SELF_CORRECTING_SERVICE_TRACE_DIR` persists full traces only when explicitly
  configured.
- The systemd unit sets `UMask=0077` so persisted trace and state files default
  to owner-only permissions on VM or bare-metal deployments.
- Trace persistence writes owner-only `0600` JSON files through same-directory
  owner-only temporary files before atomic replacement, and tightens the trace
  directory to `0700`, so direct Docker, Kubernetes, or CLI runs do not depend
  only on process umask for trace confidentiality.
- HTTP responses include `X-Content-Type-Options: nosniff` so intermediaries
  and browser-like clients do not reinterpret JSON or metrics payloads.
- HTTP responses include `Cache-Control: no-store` so intermediaries and
  clients do not retain runtime config, agent results, metrics, or structured
  error payloads.
- HTTP responses include `Referrer-Policy: no-referrer` to reduce request path
  or query leakage when browser-like clients or proxies follow links from API
  responses.
- HTTP responses include `Content-Security-Policy: default-src 'none';
  frame-ancestors 'none'; base-uri 'none'` so browser-like clients do not
  execute response content, embed the API in frames, or resolve relative base
  URLs from service responses.
- HTTP responses also include `X-Frame-Options: DENY` for legacy clients and
  gateway audits that still check frame protection outside CSP support.
- HTTP `Server` headers expose only the service product token and do not expose
  the Python runtime version.
- Caller-provided `X-Request-ID` values are accepted only when they are
  non-empty printable ASCII strings of at most 128 characters; unsafe values
  are replaced with service-generated UUIDs before response echoing or access
  logging.
- Trace persistence keeps generated trace files inside the configured trace
  directory by sanitizing trace file names before writing, preventing path traversal
  through malformed `run_id` values.
- The Kubernetes `NetworkPolicy` permits service ingress on port `8000` only
  from pods whose namespace and pod labels both set
  `self-correcting-agent-access: "true"`. Label trusted ingress gateways,
  monitoring scrapers, or internal callers explicitly instead of relying on
  namespace-wide default reachability.

Keep the service behind a trusted reverse proxy for TLS termination, request
timeouts, and network-level access control when exposed outside localhost.
