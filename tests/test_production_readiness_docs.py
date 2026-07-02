from pathlib import Path


def test_production_readiness_checklist_documents_release_gates():
    readme = Path("README.md").read_text()
    readiness = Path("docs/production-readiness.md").read_text()

    assert "docs/production-readiness.md" in readme
    assert "docs/internal-rollout.md" in readme
    assert "Release Gates" in readiness
    assert "scripts/run_checks.sh" in readiness
    assert "scripts/smoke_service.sh" in readiness
    assert "scripts/smoke_internal_runtime.sh" in readiness
    assert "scripts/staging_acceptance.sh" in readiness
    assert "self-correcting-agent-doctor" in readiness
    assert "--production" in readiness
    assert "Docker" in readiness
    assert "Kubernetes" in readiness
    assert "deploy/kubernetes/self-correcting-agent.yaml" in readiness
    assert "deploy/prometheus/self-correcting-agent-rules.yaml" in readiness
    assert "deploy/prometheus/self-correcting-agent-servicemonitor.yaml" in readiness
    assert "ServiceMonitor" in readiness
    assert "idempotency conflict" in readiness
    assert "trace persistence failure" in readiness
    assert "high request latency" in readiness
    assert "slow agent runs" in readiness
    assert "slow runtime run" in readiness
    assert "runtime tool execution timeout" in readiness
    assert "per-subject runtime failure alerting" in readiness
    assert "concurrency saturation" in readiness
    assert "request body timeout" in readiness
    assert "malformed run request" in readiness
    assert "oversized run request" in readiness
    assert "suspicious HTTP framing" in readiness
    assert "unknown route" in readiness
    assert "eviction gauges" in readiness
    assert "request duration histogram" in readiness
    assert "agent run duration histogram" in readiness
    assert "runtime run duration histogram" in readiness
    assert "runtime tool timeout" in readiness
    assert "PodDisruptionBudget" in readiness
    assert "NetworkPolicy" in readiness
    assert "self-correcting-agent-access" in readiness
    assert "CronJob" in readiness
    assert "startupProbe" in readiness
    assert "topologySpreadConstraints" in readiness
    assert "listen backlog" in readiness
    assert "bounded request threads" in readiness
    assert "block_on_close" in readiness
    assert "access log schema" in readiness
    assert "X-Trace-Path" in readiness
    assert "Referrer-Policy" in readiness
    assert "Content-Security-Policy" in readiness
    assert "X-Frame-Options" in readiness
    assert "security_response_headers" in readiness
    assert "raw-key-free idempotency" in readiness
    assert "SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_PATH" in readiness
    assert "same-volume replica retry reuse" in readiness
    assert "idempotency_cache_persistence" in readiness
    assert "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS" in readiness
    assert "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT" in readiness
    assert "runtime tool execution policy" in readiness
    assert "auth_subject" in readiness
    assert "subject-scoped runtime trace reads" in readiness
    assert "subject-scoped runtime resume" in readiness
    assert "per-subject usage metrics" in readiness
    assert "per-subject runtime trace audit" in readiness
    assert "per-subject runtime outcome metrics" in readiness
    assert "per-subject runtime resume metrics" in readiness
    assert "per-subject runtime resume alerting" in readiness
    assert "stale pending approval gauges" in readiness
    assert "self_correcting_agent_runtime_stale_pending_approvals_current" in readiness
    assert "SELF_CORRECTING_SERVICE_AUTH_TOKENS" in readiness
    assert "bind host" in readiness
    assert "bind port" in readiness
    assert "max request bytes" in readiness
    assert "trusted-forwarded-for" in readiness
    assert "Retry-After" in readiness
    assert "slow-client" in readiness
    assert "goal length" in readiness
    assert "full trace responses" in readiness
    assert "full_trace_response_must_be_disabled" in readiness
    assert "`--require-auth` rejects placeholder tokens" in readiness
    assert "auth_token_placeholder" in readiness
    assert "auth_token_unsafe" in readiness
    assert "SIGTERM" in readiness
    assert "143" in readiness
    assert "termination grace" in readiness
    assert "wheel artifact" in readiness
    assert "release manifest" in readiness
    assert "14-day artifact retention" in readiness
    assert "package mismatch" in readiness
    assert "version mismatch" in readiness
    assert "artifact_count mismatch" in readiness
    assert "artifacts must be a list" in readiness
    assert "artifact entry must be an object" in readiness
    assert "artifact path missing" in readiness
    assert "artifact path invalid" in readiness
    assert "artifact is not a file" in readiness
    assert "sha256" in readiness
    assert "verify" in readiness
    assert "release evidence bundle" in readiness
    assert "evidence_secret_detected" in readiness
    assert "evidence_secret_findings" in readiness
    assert "self-correcting-agent-release-evidence" in readiness
    assert "Known External Dependencies" in readiness
    assert "redacted LLM provider audit fields" in readiness
    assert "llm_api_key_configured" in readiness
    assert "llm_max_retries" in readiness
    assert "llm_retry_backoff_seconds" in readiness
    assert "--require-runtime-provider" in readiness
    assert "llm_base_url_required" in readiness
    assert "llm_model_required" in readiness
    assert "llm_api_key_required" in readiness
    assert "runtime_iterations_too_low" in readiness
    assert "scripts/smoke_real_llm_runtime.sh" in readiness
    assert "evidence_schema_version" in readiness
    assert "provider_snapshot" in readiness
    assert "llm_base_url_host" in readiness
    assert "capability_checks" in readiness
    assert "trace_status" in readiness
    assert "timeline" in readiness
    assert "invalid_evidence" in readiness
    assert "docs/internal-rollout.md" in readiness
    assert "internal rollout sign-off" in readiness
    assert "OpenAPI contract hash" in readiness
    assert "openapi_contract" in readiness
    assert "configuration" in readiness
    assert "env example semantic check" in readiness
    assert "service_keys_present" in readiness
    assert "runtime_keys_present" in readiness
    assert "provider_keys_present" in readiness
    assert "integration" in readiness
    assert "internal runtime client semantic check" in readiness
    assert "commands_present" in readiness
    assert "idempotency_present" in readiness
    assert "runtime_routes_present" in readiness
    assert "/runtime/runs/summary" in readiness
    assert "observability" in readiness
    assert "Grafana dashboard semantic check" in readiness
    assert "Prometheus alert rules semantic check" in readiness
    assert "ServiceMonitor semantic check" in readiness
    assert "scrape_target_present" in readiness
    assert "selector_present" in readiness
    assert "deployment" in readiness
    assert "Kubernetes manifest semantic check" in readiness
    assert "systemd unit semantic check" in readiness
    assert "required_resources_present" in readiness
    assert "hardening_present" in readiness
    assert "rollout_controls_present" in readiness
    assert "service_controls_present" in readiness
    assert "sandboxing_present" in readiness
    assert "resource_controls_present" in readiness
    assert "trace_state_boundary_present" in readiness
    assert "required_metrics_present" in readiness
    assert "required_alerts_present" in readiness
    assert "--provider-smoke-evidence" in readiness
    assert "--require-provider-smoke" in readiness
    assert "--staging-acceptance-evidence" in readiness
    assert "--require-staging-acceptance" in readiness
    assert "scripts/production_approval_bundle.sh --strict" in readiness
    assert "unknown_argument" in readiness
    assert "release_manifest_missing" in readiness
    assert "evidence_max_age_invalid" in readiness
    assert "blocked" in readiness
    assert "exit code 1" in readiness


def test_readme_documents_service_runtime_controls():
    readme = Path("README.md").read_text()

    assert "SELF_CORRECTING_SERVICE_AUTH_TOKEN" in readme
    assert "SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE" in readme
    assert "SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS" in readme
    assert "SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS" in readme
    assert "SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE" in readme
    assert "SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS" in readme
    assert "SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS" in readme
    assert "SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS" in readme
    assert "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS" in readme
    assert "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT" in readme
    assert "SELF_CORRECTING_SERVICE_TRUST_FORWARDED_FOR" in readme
    assert "SELF_CORRECTING_SERVICE_TRACE_DIR" in readme
    assert "SSRF" in readme
    assert "does not follow redirects" in readme
