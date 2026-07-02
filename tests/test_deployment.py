import json
from pathlib import Path


def test_dockerfile_defines_runtime_image_healthcheck_and_non_root_user():
    dockerfile = Path("Dockerfile").read_text()

    assert "FROM python:" in dockerfile
    assert "PIP_NO_CACHE_DIR=1" in dockerfile
    assert "PIP_DISABLE_PIP_VERSION_CHECK=1" in dockerfile
    assert "pip install --no-cache-dir ." in dockerfile
    assert "USER 10001" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "/ready" in dockerfile
    assert "self-correcting-agent-serve" in dockerfile
    assert "--host" in dockerfile
    assert "0.0.0.0" in dockerfile
    assert "SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS=4096" in dockerfile
    assert "SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS=10" in dockerfile
    assert "SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS=4" in dockerfile
    assert "SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS=30" in dockerfile
    assert "SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS=10" in dockerfile


def test_dockerignore_excludes_local_and_generated_artifacts():
    dockerignore = Path(".dockerignore").read_text()

    assert ".venv" in dockerignore
    assert "__pycache__" in dockerignore
    assert ".pytest_cache" in dockerignore
    assert "build" in dockerignore
    assert "dist" in dockerignore
    assert "src/self_correcting_langgraph_agent.egg-info" in dockerignore


def test_gitignore_excludes_build_artifacts():
    gitignore = Path(".gitignore").read_text()

    assert "build/" in gitignore
    assert "dist/" in gitignore


def test_deployment_documentation_is_linked_from_readme():
    readme = Path("README.md").read_text()
    deployment = Path("docs/deployment.md").read_text()

    assert "docs/deployment.md" in readme
    assert "Docker" in deployment
    assert "built-in\n`HEALTHCHECK` against `/ready`" in deployment
    assert "Kubernetes" in deployment
    assert "deploy/kubernetes/self-correcting-agent.yaml" in deployment
    assert "PodDisruptionBudget" in deployment
    assert "NetworkPolicy" in deployment
    assert "CronJob" in deployment
    assert "deploy/prometheus/self-correcting-agent-rules.yaml" in deployment
    assert "deploy/prometheus/self-correcting-agent-servicemonitor.yaml" in deployment
    assert "SelfCorrectingAgentHighRequestLatency" in deployment
    assert "SelfCorrectingAgentSlowAgentRuns" in deployment
    assert "SelfCorrectingAgentSlowRuntimeRuns" in deployment
    assert "runtime tool execution timeout" in deployment
    assert "per-subject runtime resume alerting" in deployment
    assert "SelfCorrectingAgentMalformedRunRequests" in deployment
    assert "SelfCorrectingAgentOversizedRunRequests" in deployment
    assert "ServiceMonitor" in deployment
    assert "request body timeout" in deployment
    assert "SELF_CORRECTING_SERVICE_AUTH_TOKEN" in deployment
    assert "SELF_CORRECTING_SERVICE_AUTH_TOKENS" in deployment
    assert "auth_subject" in deployment
    assert "at least 16 characters" in deployment
    assert "`--require-auth` rejects placeholder tokens" in deployment
    assert "auth_token_placeholder" in deployment
    assert "replace-with-a-long-random-token" in deployment
    assert "SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS" in deployment
    assert "SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE" in deployment
    assert "SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS" in deployment
    assert "--require-auth" in deployment
    assert "--production" in deployment
    assert "SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS" in deployment
    assert "SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_PATH" in deployment
    assert "SQLite" in deployment
    assert "SQLite idempotency persistence" in deployment
    assert "ReadWriteMany" in deployment
    assert "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS" in deployment
    assert "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT" in deployment
    assert "Unknown runtime tool names fail" in deployment
    assert "SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS" in deployment
    assert "SIGTERM" in deployment
    assert "143" in deployment
    assert "bounded request threads" in deployment
    assert "block_on_close" in deployment
    assert "HEALTHCHECK" in deployment
    assert "access log schema" in deployment
    assert "idempotency_key_present" in deployment
    assert "without logging raw" in deployment
    assert "self-correcting-agent-trace-prune" in deployment
    assert "unknown route" in deployment
    assert "startupProbe" in deployment
    assert "topologySpreadConstraints" in deployment


def test_environment_example_documents_service_runtime_knobs():
    env_example = Path("deploy/env.example").read_text()

    assert "SELF_CORRECTING_SERVICE_HOST=0.0.0.0" in env_example
    assert "SELF_CORRECTING_SERVICE_PORT=8000" in env_example
    assert "SELF_CORRECTING_SERVICE_MAX_REQUEST_BYTES=65536" in env_example
    assert "SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS=4096" in env_example
    assert "SELF_CORRECTING_SERVICE_AUTH_TOKEN=" in env_example
    assert "SELF_CORRECTING_SERVICE_AUTH_TOKENS=" in env_example
    assert "SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE=0" in env_example
    assert "SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS=4" in env_example
    assert "SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_SIZE=0" in env_example
    assert "SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_PATH=" in env_example
    assert "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS=" in env_example
    assert "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT=" in env_example
    assert "SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS=10" in env_example
    assert "SELF_CORRECTING_SERVICE_RUNTIME_PENDING_APPROVAL_STALE_SECONDS=3600" in env_example
    assert "SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE=false" in env_example
    assert "SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS=false" in env_example
    assert "SELF_CORRECTING_SERVICE_TRUST_FORWARDED_FOR=false" in env_example
    assert "SELF_CORRECTING_SERVICE_TRACE_DIR=" in env_example
    assert "SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS=10" in env_example
    assert "SELF_CORRECTING_LLM_BASE_URL=" in env_example
    assert "SELF_CORRECTING_LLM_API_KEY=" in env_example
    assert "SELF_CORRECTING_LLM_MODEL=" in env_example
    assert "SELF_CORRECTING_LLM_TIMEOUT_SECONDS=30" in env_example
    assert "SELF_CORRECTING_LLM_MAX_RETRIES=2" in env_example
    assert "SELF_CORRECTING_LLM_RETRY_BACKOFF_SECONDS=0.25" in env_example


def test_systemd_unit_runs_service_with_restart_policy():
    unit = Path("deploy/systemd/self-correcting-agent.service").read_text()

    assert "ExecStart=" in unit
    assert "ExecStartPre=" in unit
    assert "self-correcting-agent-doctor --production" in unit
    assert "self-correcting-agent-serve" in unit
    assert "Restart=on-failure" in unit
    assert "EnvironmentFile=" in unit


def test_systemd_unit_defines_trace_state_write_boundary():
    unit = Path("deploy/systemd/self-correcting-agent.service").read_text()
    deployment = Path("docs/deployment.md").read_text()

    assert "UMask=0077" in unit
    assert "StateDirectory=self-correcting-agent" in unit
    assert "ReadWritePaths=/var/lib/self-correcting-agent" in unit
    assert (
        "self-correcting-agent-doctor --production --trace-dir "
        "/var/lib/self-correcting-agent/traces"
    ) in unit
    assert "self-correcting-agent-serve --trace-dir /var/lib/self-correcting-agent/traces" in unit
    assert "ProtectSystem=strict" in unit
    assert "StateDirectory" in deployment
    assert "ReadWritePaths" in deployment
    assert "/var/lib/self-correcting-agent/traces" in deployment
    assert "UMask=0077" in deployment


def test_systemd_unit_defines_process_sandbox_boundaries():
    unit = Path("deploy/systemd/self-correcting-agent.service").read_text()
    deployment = Path("docs/deployment.md").read_text()

    assert "CapabilityBoundingSet=" in unit
    assert "PrivateDevices=true" in unit
    assert "LockPersonality=true" in unit
    assert "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX" in unit
    assert "ProtectKernelTunables=true" in unit
    assert "ProtectKernelModules=true" in unit
    assert "ProtectKernelLogs=true" in unit
    assert "ProtectControlGroups=true" in unit
    assert "RestrictSUIDSGID=true" in unit
    assert "RestrictRealtime=true" in unit
    assert "SystemCallArchitectures=native" in unit
    assert "process sandbox boundaries" in deployment
    assert "kernel and control-group surfaces" in deployment


def test_systemd_unit_defines_cgroup_resource_boundaries():
    unit = Path("deploy/systemd/self-correcting-agent.service").read_text()
    deployment = Path("docs/deployment.md").read_text()

    assert "MemoryMax=1G" in unit
    assert "CPUQuota=100%" in unit
    assert "TasksMax=64" in unit
    assert "cgroup resource boundaries" in deployment


def test_systemd_unit_documents_graceful_shutdown_window():
    unit = Path("deploy/systemd/self-correcting-agent.service").read_text()
    deployment = Path("docs/deployment.md").read_text()

    assert "TimeoutStopSec=45" in unit
    assert "TimeoutStopSec" in deployment
    assert "SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS" in deployment


def test_kubernetes_manifest_defines_production_runtime_resources():
    manifest = Path("deploy/kubernetes/self-correcting-agent.yaml").read_text()

    assert "kind: Secret" in manifest
    assert "kind: ConfigMap" in manifest
    assert "kind: PersistentVolumeClaim" in manifest
    assert "kind: Deployment" in manifest
    assert "kind: Service" in manifest
    assert "replicas: 2" in manifest
    assert "self-correcting-agent-doctor" in manifest
    assert "--production" in manifest
    assert "readinessProbe:" in manifest
    assert "path: /ready" in manifest
    assert "startupProbe:" in manifest
    assert "livenessProbe:" in manifest
    assert "path: /health" in manifest
    assert "prometheus.io/scrape: \"true\"" in manifest
    assert "prometheus.io/path: /metrics.prom" in manifest
    assert "runAsNonRoot: true" in manifest
    assert "readOnlyRootFilesystem: true" in manifest
    assert "resources:" in manifest
    assert "SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE" in manifest
    assert "SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS" in manifest
    assert "SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_SIZE" in manifest
    assert "SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_PATH" in manifest
    assert "/var/lib/self-correcting-agent/traces/.idempotency.sqlite3" in manifest
    assert "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS" in manifest
    assert "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT" in manifest
    assert "SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS" in manifest
    assert "SELF_CORRECTING_SERVICE_RUNTIME_PENDING_APPROVAL_STALE_SECONDS" in manifest
    assert "SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE" in manifest
    assert "SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS" in manifest
    assert "SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS" in manifest
    assert "SELF_CORRECTING_SERVICE_TRACE_DIR" in manifest
    assert "configMapRef:" in manifest
    assert "secretRef:" in manifest


def test_kubernetes_manifest_uses_cluster_safe_pod_hardening():
    manifest = Path("deploy/kubernetes/self-correcting-agent.yaml").read_text()

    assert "automountServiceAccountToken: false" in manifest
    assert "ReadWriteMany" in manifest
    assert "PYTHONDONTWRITEBYTECODE" in manifest
    assert "seccompProfile:" in manifest
    assert "drop:" in manifest
    assert "- ALL" in manifest
    assert "emptyDir:" in manifest
    assert "sizeLimit: 64Mi" in manifest
    assert "`64Mi` `sizeLimit`" in Path("docs/deployment.md").read_text()


def test_kubernetes_manifest_sets_runtime_default_seccomp_on_each_container():
    manifest = Path("deploy/kubernetes/self-correcting-agent.yaml").read_text()
    container_sections = {
        "production-doctor": manifest.split("- name: production-doctor", 1)[1].split(
            "- name: service",
            1,
        )[0],
        "service": manifest.split("- name: service", 1)[1].split("volumes:", 1)[0],
        "trace-prune": manifest.split("- name: trace-prune", 1)[1].split("volumes:", 1)[0],
    }

    for section in container_sections.values():
        assert "seccompProfile:" in section
        assert "type: RuntimeDefault" in section


def test_kubernetes_manifest_bounds_production_doctor_init_container_resources():
    manifest = Path("deploy/kubernetes/self-correcting-agent.yaml").read_text()
    init_container = manifest.split("- name: production-doctor", 1)[1].split(
        "- name: service", 1
    )[0]

    assert "resources:" in init_container
    assert "requests:" in init_container
    assert "limits:" in init_container
    assert "cpu: 50m" in init_container
    assert "memory: 128Mi" in init_container
    assert "ephemeral-storage: 32Mi" in init_container
    assert "ephemeral-storage: 64Mi" in init_container
    assert "release-gate checks remain bounded" in Path("docs/deployment.md").read_text()


def test_kubernetes_manifest_bounds_runtime_ephemeral_storage():
    manifest = Path("deploy/kubernetes/self-correcting-agent.yaml").read_text()
    service_container = manifest.split("- name: service", 1)[1].split("volumes:", 1)[0]
    trace_prune_container = manifest.split("- name: trace-prune", 1)[1].split("volumes:", 1)[0]

    assert "ephemeral-storage: 64Mi" in service_container
    assert "ephemeral-storage: 128Mi" in service_container
    assert "ephemeral-storage: 32Mi" in trace_prune_container
    assert "ephemeral-storage: 64Mi" in trace_prune_container
    assert "runtime containers have ephemeral-storage requests" in Path(
        "docs/deployment.md"
    ).read_text()


def test_kubernetes_manifest_defines_availability_and_network_policies():
    manifest = Path("deploy/kubernetes/self-correcting-agent.yaml").read_text()
    deployment = Path("docs/deployment.md").read_text()
    security = Path("SECURITY.md").read_text()

    assert "kind: PodDisruptionBudget" in manifest
    assert "minReadySeconds: 5" in manifest
    assert "progressDeadlineSeconds: 120" in manifest
    assert "terminationGracePeriodSeconds: 45" in manifest
    assert "topologySpreadConstraints:" in manifest
    assert "topologyKey: kubernetes.io/hostname" in manifest
    assert "whenUnsatisfiable: ScheduleAnyway" in manifest
    assert "minAvailable: 1" in manifest
    assert "kind: NetworkPolicy" in manifest
    assert "policyTypes:" in manifest
    assert "- Ingress" in manifest
    assert "- Egress" in manifest
    assert "namespaceSelector:" in manifest
    assert "podSelector:" in manifest
    assert 'self-correcting-agent-access: "true"' in manifest
    assert "\n  egress:\n" in manifest
    assert "port: 8000" in manifest
    assert "port: 53" in manifest
    assert "minReadySeconds" in deployment
    assert "progressDeadlineSeconds" in deployment
    assert "self-correcting-agent-access" in deployment
    assert "self-correcting-agent-access" in security


def test_kubernetes_manifest_defines_trace_prune_cronjob():
    manifest = Path("deploy/kubernetes/self-correcting-agent.yaml").read_text()

    assert "kind: CronJob" in manifest
    assert "name: self-correcting-agent-trace-prune" in manifest
    assert 'schedule: "17 3 * * *"' in manifest
    assert "concurrencyPolicy: Forbid" in manifest
    assert "successfulJobsHistoryLimit: 3" in manifest
    assert "failedJobsHistoryLimit: 3" in manifest
    assert "self-correcting-agent-trace-prune" in manifest
    assert "--max-age-days" in manifest
    assert "--runtime-only" in manifest
    assert '"7"' in manifest
    assert "--delete" in manifest
    assert "restartPolicy: OnFailure" in manifest
    assert "claimName: self-correcting-agent-traces" in manifest
    assert "readOnlyRootFilesystem: true" in manifest


def test_kubernetes_manifest_documents_graceful_shutdown_window():
    deployment = Path("docs/deployment.md").read_text()

    assert "terminationGracePeriodSeconds" in deployment
    assert "45" in deployment
    assert "SELF_CORRECTING_SERVICE_RUN_TIMEOUT_SECONDS" in deployment


def test_prometheus_alert_rules_cover_service_and_agent_health():
    rules_path = Path("deploy/prometheus/self-correcting-agent-rules.yaml")

    assert rules_path.exists()
    rules = rules_path.read_text()
    alert_count = sum(
        1
        for line in rules.splitlines()
        if line.strip().startswith("- alert: SelfCorrectingAgent")
    )
    assert "groups:" in rules
    assert "  - name: self-correcting-agent.rules" in rules
    assert alert_count == 26
    assert "SelfCorrectingAgentServiceDown" in rules
    assert "SelfCorrectingAgentHighErrorRate" in rules
    assert "SelfCorrectingAgentHighRequestLatency" in rules
    assert "SelfCorrectingAgentSlowAgentRuns" in rules
    assert "SelfCorrectingAgentSlowRuntimeRuns" in rules
    assert "SelfCorrectingAgentRunTimeouts" in rules
    assert "SelfCorrectingAgentRunFailures" in rules
    assert "SelfCorrectingAgentRuntimeRunFailures" in rules
    assert "SelfCorrectingAgentRuntimeSubjectRunFailures" in rules
    assert "SelfCorrectingAgentRuntimeApprovalsPending" in rules
    assert "SelfCorrectingAgentRuntimeSubjectApprovalsPending" in rules
    assert "SelfCorrectingAgentRuntimeStalePendingApprovals" in rules
    assert "SelfCorrectingAgentRuntimeSubjectResumes" in rules
    assert "SelfCorrectingAgentRuntimeBudgetExhausted" in rules
    assert "SelfCorrectingAgentRuntimeToolExecutionTimeouts" in rules
    assert "SelfCorrectingAgentTracePersistenceFailures" in rules
    assert "SelfCorrectingAgentConcurrencySaturated" in rules
    assert "SelfCorrectingAgentRateLimited" in rules
    assert "SelfCorrectingAgentIdempotencyConflicts" in rules
    assert "SelfCorrectingAgentIdempotencyCacheEvictions" in rules
    assert "SelfCorrectingAgentRequestBodyTimeouts" in rules
    assert "SelfCorrectingAgentMalformedRunRequests" in rules
    assert "SelfCorrectingAgentOversizedRunRequests" in rules
    assert "SelfCorrectingAgentSuspiciousHttpFraming" in rules
    assert "SelfCorrectingAgentUnknownMethodTraffic" in rules
    assert "SelfCorrectingAgentUnknownRouteTraffic" in rules
    assert "up{" in rules
    assert "self_correcting_agent_responses_total" in rules
    assert "histogram_quantile" in rules
    assert "self_correcting_agent_request_duration_seconds_bucket" in rules
    assert "self_correcting_agent_agent_run_duration_seconds_bucket" in rules
    assert "self_correcting_agent_runtime_run_duration_seconds_bucket" in rules
    assert "self_correcting_agent_run_status_total" in rules
    assert "self_correcting_agent_runtime_run_status_total" in rules
    assert "self_correcting_agent_runtime_run_status_by_auth_subject_total" in rules
    assert "self_correcting_agent_runtime_resumes_by_auth_subject_total" in rules
    assert "self_correcting_agent_runtime_approval_required_total" in rules
    assert "self_correcting_agent_runtime_stale_pending_approvals_current" in rules
    assert "self_correcting_agent_runtime_failed_budget_exhaustions_total" in rules
    assert "self_correcting_agent_runtime_observation_errors_total" in rules
    assert "tool_execution_timeout" in rules
    assert "self_correcting_agent_error_responses_total" in rules
    assert "trace_persistence_failed" in rules
    assert "too_many_concurrent_runs" in rules
    assert "idempotency_key_conflict" in rules
    assert "self_correcting_agent_idempotency_cache_evictions" in rules
    assert "request_body_timeout" in rules
    assert "invalid_content_length" in rules
    assert "incomplete_request_body" in rules
    assert "unsupported_media_type" in rules
    assert "request_too_large" in rules
    assert "goal_too_large" in rules
    assert "invalid_transfer_encoding" in rules
    assert "expectation_failed" in rules
    assert 'self_correcting_agent_requests_by_method_total{method="__unknown__"}' in rules
    assert "not_found" in rules
    assert "__unknown__" in rules
    assert "severity:" in rules


def test_prometheus_servicemonitor_documents_scrape_target():
    monitor_path = Path("deploy/prometheus/self-correcting-agent-servicemonitor.yaml")

    assert monitor_path.exists()
    monitor = monitor_path.read_text()
    assert "apiVersion: monitoring.coreos.com/v1" in monitor
    assert "kind: ServiceMonitor" in monitor
    assert "name: self-correcting-agent" in monitor
    assert "app.kubernetes.io/name: self-correcting-agent" in monitor
    assert "path: /metrics.prom" in monitor
    assert "port: http" in monitor
    assert "interval: 30s" in monitor
    assert "scrapeTimeout: 5s" in monitor


def test_grafana_dashboard_covers_internal_runtime_operations():
    dashboard_path = Path("deploy/grafana/self-correcting-agent-dashboard.json")
    deployment = Path("docs/deployment.md").read_text()
    rollout = Path("docs/internal-rollout.md").read_text()

    assert dashboard_path.exists()
    dashboard_text = dashboard_path.read_text()
    dashboard = json.loads(dashboard_text)
    payload = json.dumps(dashboard, sort_keys=True)
    panel_titles = {
        panel.get("title")
        for panel in dashboard["panels"]
        if isinstance(panel, dict)
    }

    assert dashboard["title"] == "Self-Correcting Agent Runtime"
    assert dashboard["schemaVersion"] >= 39
    assert "SelfCorrectingAgent" in dashboard["tags"]
    assert "Service Health" in panel_titles
    assert "HTTP 5xx Rate" in panel_titles
    assert "Runtime p95 Latency" in panel_titles
    assert "Runtime Runs by Subject" in panel_titles
    assert "Runtime Outcomes by Subject" in panel_titles
    assert "Runtime Resumes by Subject" in panel_titles
    assert "Runtime Approval Pressure" in panel_titles
    assert "Runtime Stale Pending Approvals" in panel_titles
    assert "Runtime Tool Errors" in panel_titles
    assert 'up{job=\\"self-correcting-agent\\"}' in dashboard_text
    assert "self_correcting_agent_responses_total" in payload
    assert "self_correcting_agent_runtime_run_duration_seconds_bucket" in payload
    assert "self_correcting_agent_runtime_runs_by_auth_subject_total" in payload
    assert "self_correcting_agent_runtime_run_status_by_auth_subject_total" in payload
    assert "self_correcting_agent_runtime_resumes_by_auth_subject_total" in payload
    assert "self_correcting_agent_runtime_approval_required_total" in payload
    assert "self_correcting_agent_runtime_stale_pending_approvals_current" in payload
    assert "self_correcting_agent_runtime_observation_errors_total" in payload
    assert "deploy/grafana/self-correcting-agent-dashboard.json" in deployment
    assert "deploy/grafana/self-correcting-agent-dashboard.json" in rollout
