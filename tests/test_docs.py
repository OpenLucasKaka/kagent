from pathlib import Path


def test_architecture_document_is_linked_from_readme():
    readme = Path("README.md").read_text()

    assert "docs/architecture.md" in readme
    assert Path("docs/architecture.md").exists()


def test_architecture_document_names_runtime_and_operational_boundaries():
    architecture = Path("docs/architecture.md").read_text()

    assert "LangGraph runtime" in architecture
    assert "Codex-style runtime" in architecture
    assert "max_iterations" in architecture
    assert "iteration_count" in architecture
    assert "iteration_budget_remaining" in architecture
    assert "approved_action_ids" in architecture
    assert "explicit `plan` or `plan_sequence`" in architecture
    assert "must reference action ids" in architecture
    assert "approvals must resume" in architecture
    assert "approved_action_count" in architecture
    assert "consumed approval audit" in architecture
    assert "actually bypassed policy" in architecture
    assert "approved_tool_counts" in architecture
    assert "pending_approval_action_id" in architecture
    assert "pending_approval_tool" in architecture
    assert "lists omit full `pending_approval` payloads" in architecture
    assert "next_cursor" in architecture
    assert "cursor" in architecture
    assert "has_more" in architecture
    assert "unique, non-empty action IDs" in architecture
    assert "only the pending approval action" in architecture
    assert "final_answer" in architecture
    assert "empty-action `final_answer`" in architecture
    assert "latest observation is still failed" in architecture
    assert "input_schema" in architecture
    assert "output_schema" in architecture
    assert "timeout_seconds" in architecture
    assert "tool_execution_timeout" in architecture
    assert "invalid_tool_output" in architecture
    assert "minLength" in architecture
    assert "maxLength" in architecture
    assert "maxItems" in architecture
    assert "minimum" in architecture
    assert "maximum" in architecture
    assert "boolean" in architecture
    assert "MAX_PLAN_ACTIONS" in architecture
    assert "MAX_ACTION_REASON_CHARS" in architecture
    assert "MAX_PLAN_FINAL_ANSWER_CHARS" in architecture
    assert "`invalid_plan` observations" in architecture
    assert "`llm_provider_error` observations" in architecture
    assert "llm_provider_request" in architecture
    assert "llm_provider_request_status" in architecture
    assert "llm_provider_status=failed" in architecture
    assert "has_llm_provider_retries=true" in architecture
    assert "runtime_llm_provider_requests_total" in architecture
    assert "kagent_runtime_llm_provider_*" in architecture
    assert "content_omitted=true" in architecture
    assert "truncated_chars" in architecture
    assert "prompt_observation_compaction" in architecture
    assert "depends_on" in architecture
    assert "dependency_statuses" in architecture
    assert "unknown action fields" in architecture
    assert "artifact" in architecture
    assert "decision_matrix" in architecture
    assert "list_files" in architecture
    assert "symlink entries" in architecture
    assert "http_request" in architecture
    assert "shell_command" in architecture
    assert "secret-exposing environment reads" in architecture
    assert "SSRF" in architecture
    assert "private, loopback, and link-local" in architecture
    assert "url credentials" in architecture
    assert "secret-like query or fragment" in architecture
    assert "secret-like plain-text" in architecture
    assert "shell command output" in architecture
    assert "does not follow redirects" in architecture
    assert "rubric_score" in architecture
    assert "plans" in architecture
    assert "action-level timing" in architecture
    assert "planner, policy, and executor" in architecture
    assert "run-level duration" in architecture
    assert "failed_observation_count" in architecture
    assert "lifecycle_state" in architecture
    assert "lifecycle_state_counts" in architecture
    assert "lifecycle_state=waiting_approval" in architecture
    assert "planner_failure_count" in architecture
    assert "tool_failure_count" in architecture
    assert "latest_failed_action_id" in architecture
    assert "latest_failed_tool" in architecture
    assert "latest_failed_error_code" in architecture
    assert "error_code_counts" in architecture
    assert "latest_plan_action_count" in architecture
    assert "latest_plan_action_ids" in architecture
    assert "dependency_edge_count" in architecture
    assert "terminal tool failure" in architecture
    assert "artifact_count" in architecture
    assert "artifact_kinds" in architecture
    assert "sandbox.env_policy" in architecture
    assert "artifact_formats" in architecture
    assert "artifact_tags" in architecture
    assert "artifact_total_bytes" in architecture
    assert "artifact_bytes_by_kind" in architecture
    assert "has_artifacts" in architecture
    assert "has_errors" in architecture
    assert "has_failures" in architecture
    assert "has_approvals" in architecture
    assert "has_pending_approval=true" in architecture
    assert "auth_subject=team-a" in architecture
    assert "authenticated internal subject" in architecture
    assert "subject-mapped bearer tokens" in architecture
    assert "cross-subject run IDs" in architecture
    assert "subject-scoped runtime resume" in architecture
    assert "KAGENT_SERVICE_IDEMPOTENCY_CACHE_PATH" in architecture
    assert "stdlib SQLite cache" in architecture
    assert "SQLite idempotency readiness" in architecture
    assert "anonymous scope" in architecture
    assert "KAGENT_SERVICE_RUNTIME_ALLOWED_TOOLS" in architecture
    assert "KAGENT_SERVICE_RUNTIME_ALLOWED_TOOLS_BY_SUBJECT" in architecture
    assert "approved_action_id=step-1" in architecture
    assert "approved_by_auth_subject=default" in architecture
    assert "resumed_from_run_id=pending-run" in architecture
    assert "resumed_by_auth_subject" in architecture
    assert "resumed_by_auth_subject=default" in architecture
    assert "pending_approval_tool=http_request" in architecture
    assert "pending_approval_action_id=step-1" in architecture
    assert "status=failed" in architecture
    assert "tool=artifact" in architecture
    assert "error_code=invalid_tool_input" in architecture
    assert "latest_failed_error_code=invalid_tool_input" in architecture
    assert "latest_failed_action_id=fetch-site" in architecture
    assert "latest_failed_tool=planner" in architecture
    assert "iteration_budget_remaining=0" in architecture
    assert "artifact_kind=report" in architecture
    assert "artifact_format=markdown" in architecture
    assert "artifact_tag=release" in architecture
    assert "has_errors=true" in architecture
    assert "has_failures=true" in architecture
    assert "has_approvals=true" in architecture
    assert "Deterministic tools" in architecture
    assert "Operational gates" in architecture
    assert "unreadable trace files" in architecture
    assert "trace_read_failed" in architecture
    assert "runtime identity boundary" in architecture
    assert "identity is `kagent`" in architecture
    assert "Provider details stay behind the configuration boundary" in architecture
    assert "preventing duplicate side effects" in architecture
    assert "previous_path" in architecture
    assert "final_answer_guardrail" in architecture
    assert "unresolved_failure_boundary" in architecture
    assert "final_answer_guardrail_applied_count" in architecture
    assert "final_answer_guardrail_reason_counts" in architecture
    assert "kagent_runtime_final_answer_guardrails_total" in architecture
    assert "runtime_runs_by_lifecycle_state" in architecture
    assert "kagent_runtime_run_lifecycle_state_total" in architecture
    assert "kagent_runtime_run_lifecycle_state_by_auth_subject_total" in architecture


def test_readme_documents_console_script_entrypoints():
    readme = Path("README.md").read_text()

    assert "kagent" in readme
    assert "kagent-batch" in readme
    assert "kagent-eval" in readme
    assert "kagent-metrics" in readme
    assert "kagent-doctor" in readme
    assert "kagent-release-manifest" in readme
    assert "kagent-serve" in readme
    assert "kagent-trace-prune" in readme
    assert "--fail-on-errors" in readme
    assert "kagent-trace-replay" in readme
    old_console_name = "-".join(["self", "correcting", "agent"])
    assert old_console_name not in readme
    assert "live progress" in readme
    assert "compact operator transcript" in readme
    assert "moving" in readme
    assert "apply_patch" in readme
    assert "bounded local shell commands" in readme
    assert "secret-exposing" in readme
    assert "--session-memory PATH" in readme
    assert "KAGENT_SESSION_MEMORY_PATH" in readme
    assert "session-memory.json" in readme
    assert "KAGENT_HISTORY_PATH" in readme
    assert "kagent/history" in readme
    assert "prompt history" in readme
    assert "/reset" in readme
    assert "/doctor" in readme
    assert "/save-trace PATH" in readme
    assert "owner-only on read and write" in readme
    assert "0700" in readme
    assert "rejects symlink memory files" in readme
    assert "parent directories" in readme
    assert "before reusing memory" in readme
    assert "writing it to disk" in readme
    assert "progress_event_count" in readme
    assert 'kagent "draft an internal rollout checklist"' in readme
    assert "--deterministic" in readme
    assert "--runtime-plan" in readme
    assert "--max-iterations" in readme
    assert "JSON integers" in readme


def test_readme_positions_deterministic_graph_as_smoke_not_demo():
    readme = Path("README.md").read_text()

    assert "deterministic graph runs for local tests, smoke checks, and regression checks" in readme
    assert "local tests, demos, and regression checks" not in readme


def test_architecture_document_names_service_boundary():
    architecture = Path("docs/architecture.md").read_text()

    assert "Service boundary" in architecture
    assert "POST /run" in architecture


def test_architecture_document_tracks_production_service_contract():
    architecture = Path("docs/architecture.md").read_text()

    assert "GET /ready" in architecture
    assert "HEAD /ready" in architecture
    assert "GET /config" in architecture
    assert "GET /runtime/tools" in architecture
    assert "GET /runtime/graph" in architecture
    assert "graph_phases" in architecture
    assert "RuntimeTimelineResponse" in architecture
    assert "graph_phase_count" in architecture
    assert "graph_phase_node_counts" in architecture
    assert "GET /runtime/policy" in architecture
    assert "GET /runtime/approvals" in architecture
    assert "GET /runtime/approvals/summary" in architecture
    assert "approval queue" in architecture
    assert "min_pending_age_seconds=3600" in architecture
    assert "pending_age_seconds" in architecture
    assert "stale_pending_count" in architecture
    assert "max_pending_age_seconds" in architecture
    assert "GET /runtime/runs" in architecture
    assert "GET /runtime/runs/summary" in architecture
    assert "runtime fleet summary" in architecture
    assert "tag_counts" in architecture
    assert "metadata_key_counts" in architecture
    assert "GET /runtime/runs/{run_id}" in architecture
    assert "metadata_keys" in architecture
    assert "GET /runtime/runs/{run_id}/timeline" in architecture
    assert "GET /runtime/runs/{run_id}/artifacts" in architecture
    assert "GET /runtime/runs/{run_id}/artifacts/{artifact_id}" in architecture
    assert "POST /runtime/runs/{run_id}/cancel" in architecture
    assert "cancelled_by_auth_subject" in architecture
    assert "compact timeline" in architecture
    assert "artifact metadata" in architecture
    assert "HEAD /health" in architecture
    assert "HEAD /ready" in architecture
    assert "OPTIONS /run" in architecture
    assert "POST /runtime/resume" in architecture
    assert "trace persistence" in architecture
    assert "/runtime/run trace persistence" in architecture
    assert "wheel build" in architecture
    assert "release manifest" in architecture
    assert "sha256" in architecture
    assert "verify" in architecture


def test_architecture_document_tracks_agent_run_metrics():
    architecture = Path("docs/architecture.md").read_text()

    assert "agent run" in architecture
    assert "outcome/duration" in architecture


def test_architecture_document_tracks_structured_error_codes():
    architecture = Path("docs/architecture.md").read_text()

    assert "error_code" in architecture
    assert "machine-readable" in architecture


def test_architecture_document_names_service_safety_helpers():
    architecture = Path("docs/architecture.md").read_text()

    assert "service/safety.py" in architecture
    assert "request IDs" in architecture
    assert "trace file names" in architecture


def test_architecture_document_names_service_contract_module():
    architecture = Path("docs/architecture.md").read_text()

    assert "service/contract.py" in architecture
    assert "OpenAPI" in architecture
    assert "RunRequest" in architecture
    assert "RunResponse" in architecture
    assert "common response headers" in architecture
    assert "HEAD /health" in architecture
    assert "OPTIONS /run" in architecture
    assert "/metrics.prom" in architecture
    assert "/openapi.json" in architecture
    assert "operationId" in architecture
    assert "content sniffing" in architecture


def test_architecture_document_names_service_status_module():
    architecture = Path("docs/architecture.md").read_text()

    assert "service_status.py" in architecture
    assert "readiness" in architecture
    assert "redacted runtime configuration" in architecture


def test_architecture_document_names_service_trace_store_module():
    architecture = Path("docs/architecture.md").read_text()

    assert "service_trace_store.py" in architecture
    assert "trace persistence" in architecture


def test_architecture_document_names_service_run_module():
    architecture = Path("docs/architecture.md").read_text()

    assert "service_run.py" in architecture
    assert "run request" in architecture


def test_architecture_document_names_service_transport_module():
    architecture = Path("docs/architecture.md").read_text()

    assert "service_transport.py" in architecture
    assert "response encoding" in architecture


def test_architecture_document_names_service_server_module():
    architecture = Path("docs/architecture.md").read_text()

    assert "service_server.py" in architecture
    assert "server bootstrap" in architecture
    assert "ProductionThreadingHTTPServer" in architecture
    assert "listen backlog" in architecture
