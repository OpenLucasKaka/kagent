from pathlib import Path


def test_operations_runbook_documents_continuous_iteration_and_failure_triage():
    readme = Path("README.md").read_text()
    runbook = Path("docs/operations.md").read_text()

    assert "docs/operations.md" in readme
    assert "Continuous iteration" in runbook
    assert "Failure triage" in runbook
    assert "Service operation" in runbook
    assert "scripts/continuous_iterate.sh" in runbook
    assert "scripts/smoke_real_llm_runtime.sh" in runbook
    assert "real LLM runtime smoke" in runbook
    assert "self_correcting_langgraph_agent.ops.metrics" in runbook
    assert "self-correcting-agent-release-manifest" in runbook
    assert "scripts/production_approval_bundle.sh" in runbook
    assert "scripts/production_approval_bundle.sh --strict" in runbook
    assert "unknown_argument" in runbook
    assert "release_manifest_missing" in runbook
    assert "evidence_max_age_invalid" in runbook
    assert "blocked" in runbook
    assert "exit code 1" in runbook
    assert "evidence_secret_detected" in runbook
    assert "evidence_secret_findings" in runbook
    assert "self-correcting-agent-trace-prune" in runbook
    assert "self-correcting-agent-trace-replay" in runbook
    assert "self-correcting agent ready  /help" in runbook
    assert "live progress" in runbook
    assert "compact operator" in runbook
    assert "--session-memory PATH" in runbook
    assert "owner-only" in runbook
    assert "progress_event_count" in runbook
    assert "exclude tool inputs" in runbook
    assert "--runtime-only" in runbook
    assert "protected_pending" in runbook
    assert "matched_by_status" in runbook
    assert "redacted summary" in runbook
    assert "0700" in runbook
    assert "0600" in runbook
    assert "sha256" in runbook
    assert "package mismatch" in runbook
    assert "version mismatch" in runbook
    assert "artifact_count mismatch" in runbook
    assert "artifacts must be a list" in runbook
    assert "artifact entry must be an object" in runbook
    assert "artifact path missing" in runbook
    assert "artifact path invalid" in runbook
    assert "artifact is not a file" in runbook
    assert "--verify" in runbook
    assert "self-correcting-agent-doctor" in runbook
    assert "RunRequest" in runbook
    assert "RunResponse" in runbook
    assert "JSON integers" in runbook
    assert "X-Run-ID" in runbook
    assert "X-Trace-Path" in runbook
    assert "X-Request-ID" in runbook
    assert "X-Content-Type-Options" in runbook
    assert "Referrer-Policy" in runbook
    assert "Content-Security-Policy" in runbook
    assert "X-Frame-Options" in runbook
    assert "security_response_headers" in runbook
    assert "self_correcting_agent_build_info" in runbook
    assert "content_security_policy_header" in runbook
    assert "x_frame_options_header" in runbook
    assert "WWW-Authenticate" in runbook
    assert "non-ASCII `Authorization`" in runbook
    assert "single-valued `Authorization`" in runbook
    assert "at least 16 characters" in runbook
    assert "`--require-auth` rejects" in runbook
    assert "`--require-auth` rejects placeholder tokens" in runbook
    assert "auth_token_placeholder" in runbook
    assert "auth_token_unsafe" in runbook
    assert "replace-with-a-long-random-token" in runbook
    assert "Retry-After" in runbook
    assert "retry_after_seconds" in runbook
    assert "408 request_body_timeout" in runbook
    assert 'retry_after_seconds: "1"' in runbook
    assert "dynamic" in runbook
    assert "concurrency-saturation" in runbook
    assert "HEAD /health" in runbook
    assert "HEAD /ready" in runbook
    assert "OPTIONS /run" in runbook
    assert "GET /metrics.prom" in runbook
    assert "GET /runtime/tools" in runbook
    assert "output_schema" in runbook
    assert "timeout_seconds" in runbook
    assert "tool_execution_timeout" in runbook
    assert "invalid_tool_output" in runbook
    assert "GET /runtime/approvals" in runbook
    assert "pending_approval.input" in runbook
    assert "GET /runtime/runs" in runbook
    assert "GET /runtime/runs/summary" in runbook
    assert "pending_approval_count" in runbook
    assert "GET /runtime/runs/{run_id}" in runbook
    assert "GET /runtime/runs/{run_id}/timeline" in runbook
    assert "GET /runtime/runs/{run_id}/artifacts" in runbook
    assert "GET /runtime/runs/{run_id}/artifacts/{artifact_id}" in runbook
    assert "POST /runtime/runs/{run_id}/cancel" in runbook
    assert "cancelled_by_auth_subject" in runbook
    assert "compact timeline" in runbook
    assert "artifact metadata" in runbook
    assert "POST /runtime/resume" in runbook
    assert "operationId" in runbook
    assert "run_id" in runbook
    assert "trace_path" in runbook
    assert "/runtime/run trace persistence" in runbook
    assert "--delete" in runbook
    assert "flush" in runbook
    assert "access log schema" in runbook
    assert "status_code" in runbook
    assert "request_body_bytes" in runbook
    assert "remote_addr" in runbook
    assert "auth_subject" in runbook
    assert "runtime_owner_auth_subject" in runbook
    assert "resumed_by_auth_subject access log field" in runbook
    assert "idempotency_key_present" in runbook
    assert "raw key is never logged" in runbook
    assert "Error Code Catalog" in runbook
    assert "agent_run_timeout" in runbook
    assert "goal_too_large" in runbook
    assert "SelfCorrectingAgentMalformedRunRequests" in runbook
    assert "SelfCorrectingAgentOversizedRunRequests" in runbook
    assert "SelfCorrectingAgentHighRequestLatency" in runbook
    assert "SelfCorrectingAgentSlowAgentRuns" in runbook
    assert "SelfCorrectingAgentSlowRuntimeRuns" in runbook
    assert "runtime run latency" in runbook
    assert "full_trace_disabled" in runbook
    assert "incomplete_request_body" in runbook
    assert "duplicate" in runbook
    assert "invalid_transfer_encoding" in runbook
    assert "`Transfer-Encoding`" in runbook
    assert "expectation_failed" in runbook
    assert "`Expect`" in runbook
    assert "idempotency_key_conflict" in runbook
    assert "invalid_idempotency_key" in runbook
    assert "`Content-Type`" in runbook
    assert "single-valued `application/json`" in runbook
    assert "single-valued" in runbook
    assert "request_body_timeout" in runbook
    assert "Idempotency-Key" in runbook
    assert "authenticated internal subject" in runbook
    assert "anonymous scope" in runbook
    assert "SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_PATH" in runbook
    assert "backend is `memory` or `sqlite`" in runbook
    assert "idempotency_cache_persistence" in runbook
    assert "idempotency_cache_unavailable" in runbook
    assert "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS" in runbook
    assert "SELF_CORRECTING_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT" in runbook
    assert "runtime_allowed_tools" in runbook
    assert "runtime_allowed_tools_by_subject_count" in runbook
    assert "evictions" in runbook
    assert "SELF_CORRECTING_SERVICE_MAX_GOAL_CHARS" in runbook
    assert "SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_SIZE" in runbook
    assert "SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS" in runbook
    assert "SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE" in runbook
    assert "full_trace_response_must_be_disabled" in runbook
    assert "SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS" in runbook
    assert "SELF_CORRECTING_SERVICE_AUTH_TOKENS" in runbook
    assert "operator/admin diagnostic token" in runbook
    assert "subject-scoped runtime trace reads" in runbook
    assert "subject-scoped runtime resume" in runbook
    assert "cross-subject run IDs are hidden" in runbook
    assert "trace_persistence_failed" in runbook
    assert "trace_read_failed" in runbook
    assert "unreadable trace files" in runbook
    assert "readiness_failed" in runbook
    assert "failed_checks" in runbook
    assert "has_artifacts" in runbook
    assert "has_errors" in runbook
    assert "has_failures" in runbook
    assert "has_approvals" in runbook
    assert "has_pending_approval=true" in runbook
    assert "auth_subject=team-a" in runbook
    assert "who initiated a persisted runtime run" in runbook
    assert "approved_action_id=step-1" in runbook
    assert "resumed_from_run_id=pending-run" in runbook
    assert "resumed_by_auth_subject" in runbook
    assert "resumed_by_auth_subject=default" in runbook
    assert "pending_approval_tool=http_request" in runbook
    assert "pending_approval_action_id=step-1" in runbook
    assert "min_pending_age_seconds=3600" in runbook
    assert "pending_age_seconds" in runbook
    assert "stale_pending_count" in runbook
    assert "max_pending_age_seconds" in runbook
    assert "status=failed" in runbook
    assert "tool=artifact" in runbook
    assert "error_code=invalid_tool_input" in runbook
    assert "latest_failed_error_code=invalid_tool_input" in runbook
    assert "latest_failed_action_id=fetch-site" in runbook
    assert "latest_failed_tool=planner" in runbook
    assert "iteration_budget_remaining=0" in runbook
    assert "artifact_kind=report" in runbook
    assert "artifact_format=markdown" in runbook
    assert "artifact_tag=release" in runbook
    assert "tag=internal-smoke" in runbook
    assert "metadata_key=workflow" in runbook
    assert "metadata_value=internal" in runbook
    assert "metadata_key_counts" in runbook
    assert "tag_counts" in runbook
    assert "has_errors=true" in runbook
    assert "has_failures=true" in runbook
    assert "has_approvals=true" in runbook
    assert "SELF_CORRECTING_SERVICE_REQUEST_TIMEOUT_SECONDS" in runbook
    assert "--runtime" in runbook
    assert "--runtime-plan" in runbook
    assert "SELF_CORRECTING_LLM_BASE_URL" in runbook
    assert "SELF_CORRECTING_LLM_API_KEY" in runbook
    assert "SELF_CORRECTING_LLM_MODEL" in runbook
    assert "SELF_CORRECTING_LLM_MAX_RETRIES" in runbook
    assert "SELF_CORRECTING_LLM_RETRY_BACKOFF_SECONDS" in runbook
    assert "evidence_schema_version" in runbook
    assert "provider_snapshot" in runbook
    assert "llm_base_url_host" in runbook
    assert "capability_checks" in runbook
    assert "trace_status" in runbook
    assert "timeline" in runbook
    assert "invalid_evidence" in runbook
    assert "max_iterations" in runbook
    assert "iteration_count" in runbook
    assert "iteration_budget_remaining" in runbook
    assert "approved_action_ids" in runbook
    assert "approved_action_count" in runbook
    assert "approval audit" in runbook
    assert "pending_approval_action_id" in runbook
    assert "pending_approval_tool" in runbook
    assert "lists omit full `pending_approval` payloads" in runbook
    assert "next_cursor" in runbook
    assert "cursor" in runbook
    assert "has_more" in runbook
    assert "unique, non-empty action IDs" in runbook
    assert "only the pending approval action" in runbook
    assert "pending_approval" in runbook
    assert "artifact" in runbook
    assert "decision_matrix" in runbook
    assert "http_request" in runbook
    assert "SSRF" in runbook
    assert "private, loopback, and link-local" in runbook
    assert "does not follow redirects" in runbook
    assert "rubric_score" in runbook
    assert "blocking failures" in runbook
    assert "plans" in runbook
    assert "final_answer" in runbook
    assert "llm_provider" in runbook
    assert "minLength" in runbook
    assert "maxLength" in runbook
    assert "maxItems" in runbook
    assert "minimum" in runbook
    assert "maximum" in runbook
    assert "boolean" in runbook
    assert "MAX_PLAN_ACTIONS" in runbook
    assert "MAX_ACTION_REASON_CHARS" in runbook
    assert "MAX_PLAN_FINAL_ANSWER_CHARS" in runbook
    assert "invalid_plan" in runbook
    assert "Planner parse failures" in runbook
    assert "content_omitted=true" in runbook
    assert "truncated_chars" in runbook
    assert "prompt_observation_compaction" in runbook
    assert "depends_on" in runbook
    assert "dependency_statuses" in runbook
    assert "unknown action fields" in runbook
    assert "oversized plans fail" in runbook
    assert "llm_base_url" in runbook
    assert "llm_model" in runbook
    assert "llm_api_key_configured" in runbook
    assert "llm_timeout_seconds" in runbook
    assert "llm_max_retries" in runbook
    assert "llm_retry_backoff_seconds" in runbook
    assert "--require-runtime-provider" in runbook
    assert "llm_base_url_required" in runbook
    assert "llm_model_required" in runbook
    assert "llm_api_key_required" in runbook
    assert "runtime_iterations_too_low" in runbook
    assert "runtime identity boundary" in runbook
    assert "self-correcting LangGraph agent runtime" in runbook
    assert "underlying model provider" in runbook
    assert "final_answer_guardrail" in runbook
    assert "raw API key is never exposed" in runbook
    assert "bind_host" in runbook
    assert "bind_port" in runbook
    assert "max_request_bytes" in runbook
    assert "trust_forwarded_for" in runbook
    assert "active_rate_limit_windows" in runbook
    assert "unsafe `X-Forwarded-For`" in runbook
    assert "non-IP" in runbook
    assert "canonical" in runbook
    assert "requests_by_method" in runbook
    assert "requests_by_auth_subject" in runbook
    assert "self_correcting_agent_requests_by_method_total" in runbook
    assert "self_correcting_agent_requests_by_auth_subject_total" in runbook
    assert "internal usage dashboards" in runbook
    assert "self_correcting_agent_request_duration_seconds_bucket" in runbook
    assert "self_correcting_agent_agent_run_duration_seconds_bucket" in runbook
    assert "self_correcting_agent_runtime_run_duration_seconds_bucket" in runbook
    assert "self_correcting_agent_runtime_runs_total" in runbook
    assert "self_correcting_agent_runtime_run_status_total" in runbook
    assert "runtime_runs_by_auth_subject" in runbook
    assert "runtime_runs_by_auth_subject_status" in runbook
    assert "runtime_resumes_by_auth_subject" in runbook
    assert "self_correcting_agent_runtime_runs_by_auth_subject_total" in runbook
    assert "self_correcting_agent_runtime_run_status_by_auth_subject_total" in runbook
    assert "self_correcting_agent_runtime_resumes_by_auth_subject_total" in runbook
    assert "self_correcting_agent_runtime_failed_observations_total" in runbook
    assert "self_correcting_agent_runtime_observation_errors_total" in runbook
    assert "self_correcting_agent_runtime_approval_required_total" in runbook
    assert "self_correcting_agent_runtime_final_answer_guardrails_total" in runbook
    assert (
        "self_correcting_agent_runtime_final_answer_guardrails_by_reason_total"
        in runbook
    )
    assert "self_correcting_agent_runtime_pending_approvals_current" in runbook
    assert "self_correcting_agent_runtime_stale_pending_approvals_current" in runbook
    assert "self_correcting_agent_runtime_max_pending_approval_age_seconds" in runbook
    assert "self_correcting_agent_runtime_pending_approval_stale_seconds" in runbook
    assert "self_correcting_agent_runtime_failed_budget_exhaustions_total" in runbook
    assert "action-level timing" in runbook
    assert "planner, policy, and executor" in runbook
    assert "run-level duration" in runbook
    assert "failed_observation_count" in runbook
    assert "planner_failure_count" in runbook
    assert "tool_failure_count" in runbook
    assert "latest_failed_action_id" in runbook
    assert "latest_failed_tool" in runbook
    assert "latest_failed_error_code" in runbook
    assert "error_code_counts" in runbook
    assert "latest_plan_action_count" in runbook
    assert "latest_plan_action_ids" in runbook
    assert "dependency_edge_count" in runbook
    assert "approval_required_count" in runbook
    assert "tool_names" in runbook
    assert "artifact_kinds" in runbook
    assert "artifact_formats" in runbook
    assert "artifact_tags" in runbook
    assert "terminal tool failure" in runbook
    assert "artifact_count" in runbook
    assert "artifact_ids" in runbook
    assert "artifact_total_bytes" in runbook
    assert "artifact_bytes_by_kind" in runbook
    assert "unknown HTTP methods" in runbook
    assert "__unknown__" in runbook
    assert "high-cardinality" in runbook
    assert "expired rate-limit windows" in runbook
    assert "invalid environment configuration" in runbook
    assert "service and doctor entrypoints" in runbook
    assert "without a Python traceback" in runbook
    assert "SIGTERM" in runbook
    assert "143" in runbook
    assert "curl" in runbook
