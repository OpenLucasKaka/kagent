from pathlib import Path


def test_internal_rollout_guide_is_linked_and_actionable():
    readme = Path("README.md").read_text()
    rollout = Path("docs/internal-rollout.md")

    assert "docs/internal-rollout.md" in readme
    assert rollout.exists()

    guide = rollout.read_text()
    assert "Internal Rollout Guide" in guide
    assert "Team Access Model" in guide
    assert "SELF_CORRECTING_SERVICE_AUTH_TOKEN" in guide
    assert "SELF_CORRECTING_SERVICE_AUTH_TOKENS" in guide
    assert "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT" in guide
    assert "Runtime Tool Policy" in guide
    assert "Provider Smoke" in guide
    assert "scripts/smoke_internal_runtime.sh" in guide
    assert "scripts/smoke_real_llm_runtime.sh" in guide
    assert "evidence_schema_version" in guide
    assert "provider_snapshot" in guide
    assert "llm_base_url_host" in guide
    assert "capability_checks" in guide
    assert "trace_status" in guide
    assert "timeline" in guide
    assert "invalid_evidence" in guide
    assert "scripts/staging_acceptance.sh" in guide
    assert "self_correcting_agent_runtime_stale_pending_approvals_current" in guide
    assert "SelfCorrectingAgentRuntimeStalePendingApprovals" in guide
    assert "--provider-smoke-evidence" in guide
    assert "--require-provider-smoke" in guide
    assert "--staging-acceptance-evidence" in guide
    assert "--require-staging-acceptance" in guide
    assert "do not write provider secrets to files" in guide
    assert "evidence_secret_detected" in guide
    assert "evidence_secret_findings" in guide
    assert "Preflight Gates" in guide
    assert "release evidence bundle" in guide
    assert "self-correcting-agent-release-evidence" in guide
    assert "scripts/production_approval_bundle.sh --strict" in guide
    assert "unknown_argument" in guide
    assert "release_manifest_missing" in guide
    assert "evidence_max_age_invalid" in guide
    assert "blocked" in guide
    assert "exit code 1" in guide
    assert "--run-checks-exit-code" in guide
    assert "self-correcting-agent-doctor --production --require-runtime-provider" in guide
    assert "Staging Acceptance" in guide
    assert "subject-scoped runtime trace reads" in guide
    assert "subject-scoped runtime resume" in guide
    assert "Observability Wiring" in guide
    assert "deploy/prometheus/self-correcting-agent-rules.yaml" in guide
    assert "deploy/prometheus/self-correcting-agent-servicemonitor.yaml" in guide
    assert "Grafana" in guide
    assert "self_correcting_agent_runtime_runs_by_auth_subject_total" in guide
    assert "self_correcting_agent_runtime_resumes_by_auth_subject_total" in guide
    assert "runtime_owner_auth_subject" in guide
    assert "Rollback" in guide
    assert "Sign-off" in guide
