from self_correcting_langgraph_agent.service.contract import (
    ALLOWED_HTTP_METHODS,
    service_openapi,
)
from self_correcting_langgraph_agent.service.errors import ERROR_CODES


def test_service_contract_reports_openapi_paths_and_allowed_methods():
    payload = service_openapi()

    assert payload["openapi"] == "3.1.0"
    assert ALLOWED_HTTP_METHODS == "GET, HEAD, OPTIONS, POST"
    assert payload["paths"]["/run"]["options"]["responses"]["204"]["description"] == (
        "Allow: GET, HEAD, OPTIONS, POST"
    )
    assert payload["paths"]["/run"]["post"]["responses"]["504"]["description"] == (
        "Agent run timed out"
    )
    assert payload["paths"]["/runtime/run"]["post"]["responses"]["504"]["description"] == (
        "Agent run timed out"
    )
    assert payload["paths"]["/runtime/resume"]["post"]["responses"]["504"]["description"] == (
        "Agent run timed out"
    )
    assert payload["paths"]["/runtime/resume"]["post"]["responses"]["500"]["description"] == (
        "Trace read or persistence failed"
    )
    assert payload["paths"]["/runtime/runs/{run_id}/cancel"]["post"]["responses"]["409"][
        "description"
    ] == "Runtime run is already terminal"
    assert payload["paths"]["/runtime/runs/{run_id}"]["get"]["responses"]["500"][
        "description"
    ] == "Runtime trace could not be read"
    assert payload["paths"]["/run"]["post"]["responses"]["409"]["description"] == (
        "Idempotency key was reused with a different request body"
    )
    assert payload["paths"]["/run"]["post"]["responses"]["408"]["description"] == (
        "Request body read timed out"
    )
    assert payload["paths"]["/run"]["post"]["responses"]["403"]["description"] == (
        "Full trace responses are disabled"
    )
    assert payload["paths"]["/run"]["post"]["responses"]["415"]["description"] == (
        "Content-Type is missing, duplicated, or not single-valued application/json"
    )
    assert payload["paths"]["/run"]["post"]["responses"]["417"]["description"] == (
        "Expect request headers are unsupported"
    )
    bad_request_description = payload["paths"]["/run"]["post"]["responses"]["400"][
        "description"
    ]
    assert "incomplete body" in bad_request_description
    assert "unsupported transfer encoding" in bad_request_description


def test_service_contract_documents_structured_error_response_schema():
    payload = service_openapi()

    error_schema = payload["components"]["schemas"]["ErrorResponse"]

    assert error_schema["required"] == ["status", "error_code", "error"]
    assert error_schema["properties"]["error_code"]["type"] == "string"
    assert error_schema["properties"]["error_code"]["enum"] == list(ERROR_CODES)
    assert error_schema["properties"]["retry_after_seconds"] == {
        "type": "string",
        "pattern": r"^[1-9]\d*$",
    }
    assert payload["paths"]["/run"]["post"]["responses"]["401"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}
    }


def test_service_contract_documents_named_success_schemas():
    payload = service_openapi()
    schemas = payload["components"]["schemas"]

    for schema_name in [
        "HealthResponse",
        "ReadinessResponse",
        "ConfigResponse",
        "VersionResponse",
        "ToolsResponse",
        "MetricsResponse",
        "RunRequest",
        "RunResponse",
        "RuntimeResumeRequest",
        "RuntimeRunListResponse",
        "RuntimeRunListItemResponse",
        "RuntimeRunSummaryResponse",
            "RuntimeApprovalQueueResponse",
            "RuntimeApprovalSummaryResponse",
            "RuntimePolicyResponse",
            "RuntimeToolMetadata",
        "RuntimeEvent",
        "RuntimeObservation",
        "RuntimeArtifactListResponse",
        "RuntimeArtifactResponse",
        "RuntimeTimelineResponse",
        "RuntimeCancelRequest",
        "RuntimeRunStatusResponse",
        "RuntimeToolsResponse",
    ]:
        assert schema_name in schemas

    assert payload["paths"]["/run"]["post"]["requestBody"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/RunRequest"}}
    }
    assert payload["paths"]["/run"]["post"]["responses"]["200"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/RunResponse"}}
    }
    assert payload["paths"]["/runtime/run"]["post"]["responses"]["200"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/RuntimeRunResponse"}}
    }
    assert payload["paths"]["/runtime/resume"]["post"]["responses"]["200"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/RuntimeRunResponse"}}
    }
    assert payload["paths"]["/runtime/runs/{run_id}/cancel"]["post"]["requestBody"][
        "content"
    ] == {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/RuntimeCancelRequest"}
        }
    }
    assert payload["paths"]["/runtime/runs/{run_id}/cancel"]["post"]["responses"]["200"][
        "content"
    ] == {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/RuntimeRunStatusResponse"}
        }
    }
    assert payload["paths"]["/run"]["post"]["responses"]["200"]["headers"]["X-Run-ID"] == {
        "description": "Agent run identifier for request/log/trace correlation",
        "schema": {"type": "string"},
    }
    assert payload["paths"]["/run"]["post"]["responses"]["200"]["headers"]["X-Trace-Path"] == {
        "description": "Persisted trace artifact path when trace persistence is enabled",
        "schema": {"type": "string"},
    }
    assert payload["paths"]["/runtime/run"]["post"]["responses"]["200"]["headers"][
        "X-Trace-Path"
    ] == {
        "description": "Persisted runtime trace artifact path when trace persistence is enabled",
        "schema": {"type": "string"},
    }
    assert payload["paths"]["/runtime/resume"]["post"]["responses"]["200"]["headers"][
        "X-Trace-Path"
    ] == {
        "description": "Persisted resumed runtime trace artifact path",
        "schema": {"type": "string"},
    }
    assert payload["paths"]["/run"]["post"]["parameters"][0] == {
        "name": "Idempotency-Key",
        "in": "header",
        "required": False,
        "description": (
            "Optional retry key scoped to this execution route and resource when "
            "applicable; must be printable ASCII."
        ),
        "schema": {"type": "string", "maxLength": 128},
    }
    assert payload["paths"]["/runtime/run"]["post"]["parameters"][0] == (
        payload["paths"]["/run"]["post"]["parameters"][0]
    )
    assert payload["paths"]["/runtime/resume"]["post"]["parameters"][0] == (
        payload["paths"]["/run"]["post"]["parameters"][0]
    )
    assert payload["paths"]["/runtime/run"]["post"]["responses"]["409"]["description"] == (
        "Idempotency key was reused with a different request body"
    )
    assert payload["paths"]["/runtime/resume"]["post"]["responses"]["409"]["description"] == (
        "Idempotency key was reused with a different request body"
    )
    assert payload["paths"]["/health"]["get"]["responses"]["200"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/HealthResponse"}}
    }
    assert payload["paths"]["/metrics"]["get"]["responses"]["200"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/MetricsResponse"}}
    }
    assert payload["paths"]["/runtime/tools"]["get"]["responses"]["200"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/RuntimeToolsResponse"}}
    }
    assert payload["paths"]["/runtime/runs/{run_id}"]["get"]["responses"]["200"][
        "content"
    ] == {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/RuntimeRunStatusResponse"}
        }
    }
    assert payload["paths"]["/runtime/runs"]["get"]["responses"]["200"]["content"] == {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/RuntimeRunListResponse"}
        }
    }
    assert payload["paths"]["/runtime/runs/summary"]["get"]["responses"]["200"][
        "content"
    ] == {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/RuntimeRunSummaryResponse"}
        }
    }
    assert payload["paths"]["/runtime/approvals"]["get"]["responses"]["200"][
        "content"
    ] == {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/RuntimeApprovalQueueResponse"}
        }
    }
    assert payload["paths"]["/runtime/approvals/summary"]["get"]["responses"]["200"][
        "content"
    ] == {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/RuntimeApprovalSummaryResponse"}
        }
    }
    assert payload["paths"]["/runtime/policy"]["get"]["responses"]["200"][
        "content"
    ] == {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/RuntimePolicyResponse"}
        }
    }
    assert payload["paths"]["/runtime/runs/{run_id}/timeline"]["get"][
        "responses"
    ]["200"]["content"] == {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/RuntimeTimelineResponse"}
        }
    }
    assert payload["paths"]["/runtime/runs/{run_id}/artifacts"]["get"][
        "responses"
    ]["200"]["content"] == {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/RuntimeArtifactListResponse"}
        }
    }
    assert payload["paths"]["/runtime/runs/{run_id}/artifacts/{artifact_id}"]["get"][
        "responses"
    ]["200"]["content"] == {
        "application/json": {
            "schema": {"$ref": "#/components/schemas/RuntimeArtifactResponse"}
        }
    }
    runtime_runs_parameters = payload["paths"]["/runtime/runs"]["get"]["parameters"]
    assert runtime_runs_parameters[0] == {
        "name": "limit",
        "in": "query",
        "required": False,
        "description": "Maximum persisted runtime runs to return, from 1 to 100",
        "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
    }
    assert runtime_runs_parameters[1:] == [
        {
            "name": "cursor",
            "in": "query",
            "required": False,
            "description": "Opaque pagination cursor from a previous runtime run list response",
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "auth_subject",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs by authenticated internal subject"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "status",
            "in": "query",
            "required": False,
            "description": "Filter persisted runtime runs by terminal status",
            "schema": {
                "type": "string",
                "enum": ["cancelled", "done", "failed", "requires_approval"],
            },
        },
        {
            "name": "tool",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs whose compact tool_names include this tool"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "error_code",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs whose compact error_code_counts include "
                "this error code"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "latest_failed_error_code",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs whose compact latest_failed_error_code "
                "matches this error code"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "latest_failed_action_id",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs whose compact latest_failed_action_id "
                "matches this action id"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "latest_failed_tool",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs whose compact latest_failed_tool "
                "matches this tool"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "iteration_budget_remaining",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs whose compact "
                "iteration_budget_remaining equals this count"
            ),
            "schema": {"type": "integer", "minimum": 0},
        },
        {
            "name": "artifact_kind",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs whose compact artifact_kinds include "
                "this artifact kind"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "artifact_format",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs whose compact artifact_formats include "
                "this artifact format"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "artifact_tag",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs whose compact artifact_tags include "
                "this artifact tag"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "tag",
            "in": "query",
            "required": False,
            "description": "Filter persisted runtime runs whose compact tags include this tag",
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "metadata_key",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs whose compact metadata contains this key"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "metadata_value",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs whose compact metadata contains this value"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "has_artifacts",
            "in": "query",
            "required": False,
            "description": "Filter persisted runtime runs by whether artifacts were produced",
            "schema": {"type": "boolean"},
        },
        {
            "name": "has_errors",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs by whether compact summaries contain "
                "observation or run-level errors"
            ),
            "schema": {"type": "boolean"},
        },
        {
            "name": "has_failures",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs by whether compact summaries contain "
                "failed observations"
            ),
            "schema": {"type": "boolean"},
        },
        {
            "name": "has_approvals",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs by whether compact summaries contain "
                "approved actions"
            ),
            "schema": {"type": "boolean"},
        },
        {
            "name": "has_pending_approval",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs by whether compact summaries contain "
                "a pending approval action"
            ),
            "schema": {"type": "boolean"},
        },
        {
            "name": "has_final_answer_guardrail",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs by whether compact summaries contain "
                "an applied final-answer guardrail"
            ),
            "schema": {"type": "boolean"},
        },
        {
            "name": "final_answer_guardrail_reason",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs whose applied final-answer guardrail "
                "has this reason"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "approved_action_id",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs whose compact approved_action_ids "
                "include this action id"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "resumed_from_run_id",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs resumed from this original run id"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "resumed_by_auth_subject",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs by the subject that performed resume"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "pending_approval_tool",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs whose compact pending_approval_tool "
                "matches this tool"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
        {
            "name": "pending_approval_action_id",
            "in": "query",
            "required": False,
            "description": (
                "Filter persisted runtime runs whose compact pending_approval_action_id "
                "matches this action id"
            ),
            "schema": {"type": "string", "minLength": 1},
        },
    ]
    assert schemas["RunRequest"]["properties"]["goal"]["maxLength"] == 4096
    assert "disabled by default" in schemas["RunRequest"]["properties"]["full_trace"][
        "description"
    ]
    assert schemas["RuntimeRunRequest"]["properties"]["max_iterations"] == {
        "type": "integer",
        "minimum": 1,
        "description": "Bounded by the service runtime_max_iterations configuration.",
    }
    assert schemas["RuntimeRunRequest"]["properties"]["plan_sequence"] == {
        "type": "array",
        "minItems": 1,
        "items": {"type": "object"},
        "description": (
            "Optional ordered strict runtime plans for deterministic replay tests; "
            "mutually exclusive with plan."
        ),
    }
    assert schemas["RuntimeRunRequest"]["properties"]["approved_action_ids"] == {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
    }
    assert schemas["RuntimeRunRequest"]["properties"]["metadata"] == {
        "type": "object",
        "maxProperties": 16,
        "additionalProperties": {
            "type": "string",
            "maxLength": 256,
        },
        "description": (
            "Optional non-secret string metadata for internal audit and filtering."
        ),
    }
    assert schemas["RuntimeRunRequest"]["properties"]["tags"] == {
        "type": "array",
        "maxItems": 16,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1, "maxLength": 64},
        "description": "Optional non-secret run tags for internal audit and filtering.",
    }
    assert schemas["RuntimeResumeRequest"]["required"] == ["run_id", "approved_action_ids"]
    assert schemas["RuntimeResumeRequest"]["properties"]["run_id"] == {"type": "string"}
    assert schemas["RuntimeResumeRequest"]["properties"]["approved_action_ids"] == {
        "type": "array",
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
    }
    assert schemas["RuntimeCancelRequest"] == {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "maxLength": 500,
                "description": "Optional operator-visible cancellation reason.",
            }
        },
        "additionalProperties": False,
    }
    assert schemas["RuntimeRunResponse"]["properties"]["answer"] == {"type": "string"}
    final_answer_guardrail_schema = {
        "type": "object",
        "properties": {
            "applied": {"type": "string", "enum": ["true"]},
            "reason": {
                "type": "string",
                "enum": [
                    "runtime_identity_boundary",
                    "runtime_deployment_boundary",
                ],
            },
            "original_answer_omitted": {"type": "string", "enum": ["true"]},
        },
        "additionalProperties": False,
    }
    assert (
        schemas["RuntimeRunResponse"]["properties"]["final_answer_guardrail"]
        == final_answer_guardrail_schema
    )
    assert schemas["RuntimeRunResponse"]["properties"]["trace_type"] == {
        "type": "string",
        "const": "codex_runtime",
    }
    assert schemas["RuntimeRunResponse"]["properties"]["trace_path"] == {"type": "string"}
    assert schemas["RuntimeRunResponse"]["properties"]["resumed_by_auth_subject"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunResponse"]["properties"]["duration_seconds"] == {
        "type": "string",
        "pattern": r"^\d+\.\d{4}$",
    }
    assert schemas["RuntimeRunResponse"]["properties"]["iteration_count"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunResponse"]["properties"]["max_iterations"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunResponse"]["properties"][
        "iteration_budget_remaining"
    ] == {"type": "string"}
    assert schemas["RuntimeRunResponse"]["properties"]["prompt_observation_compaction"] == {
        "type": "object"
    }
    assert schemas["RuntimeRunResponse"]["properties"]["approved_action_count"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunResponse"]["properties"]["approved_action_ids"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert schemas["RuntimeRunResponse"]["properties"]["metadata"] == {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }
    assert schemas["RuntimeRunResponse"]["properties"]["tags"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert schemas["RuntimeRunResponse"]["properties"]["status"]["enum"] == [
        "cancelled",
        "done",
        "failed",
        "requires_approval",
    ]
    assert schemas["RuntimeRunResponse"]["properties"]["observations"] == {
        "type": "array",
        "items": {"$ref": "#/components/schemas/RuntimeObservation"},
    }
    assert schemas["RuntimeRunResponse"]["properties"]["events"] == {
        "type": "array",
        "items": {"$ref": "#/components/schemas/RuntimeEvent"},
    }
    assert schemas["RuntimeToolsResponse"]["properties"]["tools"] == {
        "type": "array",
        "items": {"$ref": "#/components/schemas/RuntimeToolMetadata"},
    }
    assert schemas["RuntimeToolMetadata"]["required"] == [
        "name",
        "description",
        "approval_required_by_default",
        "input_schema",
        "output_schema",
        "timeout_seconds",
    ]
    assert schemas["RuntimeToolMetadata"]["properties"][
        "approval_required_by_default"
    ] == {"type": "string", "enum": ["true", "false"]}
    assert schemas["RuntimeToolMetadata"]["properties"]["output_schema"] == {
        "type": "object"
    }
    assert schemas["RuntimeToolMetadata"]["properties"]["timeout_seconds"] == {
        "type": "string",
        "pattern": r"^\d+\.\d$",
    }
    assert schemas["RuntimeObservation"]["properties"]["duration_seconds"] == {
        "type": "string",
        "pattern": r"^\d+\.\d{4}$",
    }
    assert schemas["RuntimeObservation"]["properties"]["started_at"] == {"type": "string"}
    assert schemas["RuntimeObservation"]["properties"]["completed_at"] == {"type": "string"}
    assert schemas["RuntimeEvent"]["properties"]["duration_seconds"] == {
        "type": "string",
        "pattern": r"^\d+\.\d{4}$",
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["trace_type"] == {
        "type": "string",
        "const": "codex_runtime",
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["status"]["enum"] == [
        "cancelled",
        "done",
        "failed",
        "requires_approval",
    ]
    assert schemas["RuntimeRunStatusResponse"]["properties"]["plan_count"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["iteration_count"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["max_iterations"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"][
        "iteration_budget_remaining"
    ] == {"type": "string"}
    assert schemas["RuntimeRunStatusResponse"]["properties"]["latest_plan_action_count"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["latest_plan_action_ids"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["observation_count"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["event_count"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["progress_event_count"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["failed_observation_count"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["planner_failure_count"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["tool_failure_count"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["approval_required_count"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"][
        "latest_failed_action_id"
    ] == {"type": "string"}
    assert schemas["RuntimeRunStatusResponse"]["properties"]["latest_failed_tool"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"][
        "latest_failed_error_code"
    ] == {"type": "string"}
    assert schemas["RuntimeRunStatusResponse"]["properties"]["approved_action_count"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["approved_action_ids"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["metadata"] == {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["metadata_keys"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["tags"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["cancelled_at"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"][
        "cancelled_by_auth_subject"
    ] == {"type": "string"}
    assert schemas["RuntimeRunStatusResponse"]["properties"]["cancel_reason"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["error_code_counts"] == {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["dependency_edge_count"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["tool_names"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["artifact_count"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["artifact_ids"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["artifact_kinds"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["artifact_formats"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["artifact_tags"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["artifact_total_bytes"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["artifact_bytes_by_kind"] == {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["duration_seconds"] == {
        "type": "string",
        "pattern": r"^\d+\.\d{4}$",
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"]["auth_subject"] == {
        "type": "string"
    }
    assert (
        schemas["RuntimeRunStatusResponse"]["properties"]["final_answer_guardrail"]
        == final_answer_guardrail_schema
    )
    assert (
        schemas["RuntimeRunListItemResponse"]["properties"]["final_answer_guardrail"]
        == final_answer_guardrail_schema
    )
    assert schemas["RuntimeRunStatusResponse"]["properties"]["resumed_by_auth_subject"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunListItemResponse"]["properties"]["auth_subject"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunListItemResponse"]["properties"][
        "resumed_by_auth_subject"
    ] == {"type": "string"}
    assert schemas["RuntimeRunStatusResponse"]["properties"]["pending_approval"] == {
        "type": "object"
    }
    assert schemas["RuntimeRunStatusResponse"]["properties"][
        "pending_approval_action_id"
    ] == {"type": "string"}
    assert schemas["RuntimeRunStatusResponse"]["properties"]["pending_approval_tool"] == {
        "type": "string"
    }
    assert "pending_approval" not in schemas["RuntimeRunListItemResponse"]["properties"]
    assert schemas["RuntimeRunListItemResponse"]["properties"][
        "pending_approval_action_id"
    ] == {"type": "string"}
    assert schemas["RuntimeRunListItemResponse"]["properties"]["pending_approval_tool"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunListResponse"]["properties"]["runs"] == {
        "type": "array",
        "items": {"$ref": "#/components/schemas/RuntimeRunListItemResponse"},
    }
    assert schemas["RuntimeRunListResponse"]["properties"]["next_cursor"] == {
        "type": "string"
    }
    assert schemas["RuntimeRunListResponse"]["properties"]["has_more"] == {
        "type": "string",
        "enum": ["true", "false"],
    }
    assert schemas["RuntimeRunSummaryResponse"]["required"] == [
        "trace_type",
        "run_count",
        "status_counts",
        "auth_subject_counts",
        "tool_counts",
        "error_code_counts",
        "failed_observation_count",
        "approval_required_count",
        "pending_approval_count",
        "final_answer_guardrail_applied_count",
        "final_answer_guardrail_reason_counts",
        "artifact_count",
        "artifact_total_bytes",
        "tag_counts",
        "metadata_key_counts",
    ]
    assert schemas["RuntimeRunSummaryResponse"]["properties"]["status_counts"] == {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }
    assert schemas["RuntimeRunSummaryResponse"]["properties"]["auth_subject_counts"] == {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }
    assert schemas["RuntimeRunSummaryResponse"]["properties"]["tool_counts"] == {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }
    assert schemas["RuntimeRunSummaryResponse"]["properties"][
        "final_answer_guardrail_applied_count"
    ] == {"type": "string"}
    assert schemas["RuntimeRunSummaryResponse"]["properties"][
        "final_answer_guardrail_reason_counts"
    ] == {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }
    assert schemas["RuntimeRunSummaryResponse"]["properties"]["tag_counts"] == {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }
    assert schemas["RuntimeRunSummaryResponse"]["properties"]["metadata_key_counts"] == {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }
    assert schemas["RuntimeApprovalQueueResponse"]["required"] == [
        "trace_type",
        "count",
        "approvals",
    ]
    assert schemas["RuntimeApprovalQueueResponse"]["properties"]["approvals"] == {
        "type": "array",
        "items": {"type": "object"},
    }
    assert schemas["RuntimeApprovalSummaryResponse"]["required"] == [
        "trace_type",
        "pending_approval_count",
        "stale_pending_count",
        "max_pending_age_seconds",
        "auth_subject_counts",
        "tool_counts",
    ]
    assert schemas["RuntimeApprovalSummaryResponse"]["properties"][
        "stale_pending_count"
    ] == {"type": "string"}
    assert schemas["RuntimeApprovalSummaryResponse"]["properties"][
        "max_pending_age_seconds"
    ] == {"type": "string"}
    assert schemas["RuntimeApprovalSummaryResponse"]["properties"]["tool_counts"] == {
        "type": "object",
        "additionalProperties": {"type": "string"},
    }
    approval_parameters = payload["paths"]["/runtime/approvals"]["get"]["parameters"]
    approval_summary_parameters = payload["paths"]["/runtime/approvals/summary"]["get"][
        "parameters"
    ]
    stale_filter_parameter = {
        "name": "min_pending_age_seconds",
        "in": "query",
        "required": False,
        "description": "Filter pending approvals older than this many seconds",
        "schema": {"type": "integer", "minimum": 0},
    }
    assert stale_filter_parameter in approval_parameters
    assert stale_filter_parameter in approval_summary_parameters
    assert schemas["RuntimePolicyResponse"]["required"] == [
        "trace_type",
        "auth_subject",
        "is_admin",
        "default_allowed_tools",
        "global_allowed_tools",
        "subject_policy_count",
        "subject_allowed_tools",
        "effective_allowed_tools",
        "effective_policy_source",
        "effective_tool_policy",
        "effective_tool_policy_sha256",
    ]
    assert schemas["RuntimePolicyResponse"]["properties"]["subject_allowed_tools"] == {
        "type": "object",
        "additionalProperties": {
            "type": "array",
            "items": {"type": "string"},
        },
    }
    assert schemas["RuntimePolicyResponse"]["properties"]["effective_tool_policy"] == {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["name", "allowed", "approval_required"],
            "properties": {
                "name": {"type": "string"},
                "allowed": {"type": "string", "enum": ["true", "false"]},
                "approval_required": {
                    "type": "string",
                    "enum": ["true", "false"],
                },
            },
            "additionalProperties": False,
        },
    }
    assert schemas["RuntimePolicyResponse"]["properties"][
        "effective_tool_policy_sha256"
    ] == {
        "type": "string",
        "pattern": r"^[a-f0-9]{64}$",
    }
    assert schemas["RuntimeArtifactListResponse"]["required"] == [
        "trace_type",
        "run_id",
        "trace_path",
        "count",
        "artifacts",
    ]
    assert schemas["RuntimeArtifactListResponse"]["properties"]["artifacts"] == {
        "type": "array",
        "items": {"type": "object"},
    }
    assert schemas["RuntimeArtifactResponse"]["required"] == [
        "trace_type",
        "run_id",
        "trace_path",
        "action_id",
        "tool",
        "artifact",
    ]
    assert schemas["RuntimeArtifactResponse"]["properties"]["trace_path"] == {
        "type": "string"
    }
    assert schemas["RuntimeArtifactResponse"]["properties"]["artifact"] == {
        "type": "object"
    }
    assert schemas["RuntimeTimelineResponse"]["required"] == [
        "trace_type",
        "run_id",
        "trace_path",
        "event_count",
        "progress_event_count",
        "observation_count",
        "events",
        "progress_events",
        "observations",
    ]
    assert schemas["RuntimeTimelineResponse"]["properties"]["events"] == {
        "type": "array",
        "items": {"type": "object"},
    }
    assert schemas["RuntimeTimelineResponse"]["properties"]["progress_events"] == {
        "type": "array",
        "items": {"type": "object"},
    }


def test_service_contract_documents_trace_permission_audit_fields():
    payload = service_openapi()
    schemas = payload["components"]["schemas"]
    expected_properties = {
        "trace_directory_permissions": {"type": "string", "const": "0700"},
        "trace_file_permissions": {"type": "string", "const": "0600"},
        "trace_probe_file_permissions": {"type": "string", "const": "0600"},
    }

    for schema_name in ["ConfigResponse", "MetricsResponse"]:
        schema_properties = schemas[schema_name]["properties"]

        for property_name, expected_schema in expected_properties.items():
            assert schema_properties[property_name] == expected_schema


def test_service_contract_documents_internal_auth_audit_fields():
    payload = service_openapi()
    schemas = payload["components"]["schemas"]

    for schema_name in ["ConfigResponse", "MetricsResponse"]:
        schema_properties = schemas[schema_name]["properties"]

        assert schema_properties["auth_subject_count"] == {"type": "string"}
        assert schema_properties["idempotency_cache_backend"] == {
            "type": "string",
            "enum": ["memory", "sqlite"],
        }
        assert schema_properties["idempotency_cache_path_configured"] == {
            "type": "string",
            "enum": ["true", "false"],
        }
        assert schema_properties["runtime_allowed_tools"] == {"type": "string"}
        assert schema_properties["runtime_allowed_tools_by_subject_count"] == {
            "type": "string"
        }
        assert schema_properties["runtime_pending_approval_stale_seconds"] == {
            "type": "string"
        }


def test_service_contract_documents_llm_provider_audit_fields():
    payload = service_openapi()
    schemas = payload["components"]["schemas"]
    expected_properties = {
        "llm_provider": {
            "type": "string",
            "enum": ["openai_compatible", "unconfigured"],
        },
        "llm_base_url": {"type": "string"},
        "llm_model": {"type": "string"},
        "llm_api_key_configured": {
            "type": "string",
            "enum": ["true", "false"],
        },
        "llm_timeout_seconds": {"type": "string"},
        "llm_max_retries": {"type": "string"},
        "llm_retry_backoff_seconds": {"type": "string"},
    }

    for schema_name in ["ConfigResponse", "MetricsResponse"]:
        schema_properties = schemas[schema_name]["properties"]

        for property_name, expected_schema in expected_properties.items():
            assert schema_properties[property_name] == expected_schema


def test_service_contract_documents_structured_readiness_failed_checks():
    payload = service_openapi()
    readiness_schema = payload["components"]["schemas"]["ReadinessResponse"]

    assert readiness_schema["required"] == ["status", "checks", "failed_checks"]
    assert readiness_schema["properties"]["error_code"] == {
        "type": "string",
        "const": "readiness_failed",
    }
    assert readiness_schema["properties"]["failed_checks"] == {
        "type": "array",
        "items": {"type": "string"},
    }


def test_service_contract_documents_common_response_headers():
    payload = service_openapi()
    health_headers = payload["paths"]["/health"]["get"]["responses"]["200"]["headers"]
    run_headers = payload["paths"]["/run"]["post"]["responses"]["200"]["headers"]
    error_headers = payload["paths"]["/run"]["post"]["responses"]["400"]["headers"]
    unauthorized_headers = payload["paths"]["/run"]["post"]["responses"]["401"]["headers"]
    request_timeout_headers = payload["paths"]["/run"]["post"]["responses"]["408"]["headers"]
    rate_limited_headers = payload["paths"]["/run"]["post"]["responses"]["429"]["headers"]
    busy_headers = payload["paths"]["/run"]["post"]["responses"]["503"]["headers"]

    for headers in [health_headers, run_headers, error_headers, unauthorized_headers]:
        assert headers["X-Request-ID"]["schema"] == {"type": "string"}
        assert headers["X-Content-Type-Options"]["schema"] == {
            "type": "string",
            "const": "nosniff",
        }
        assert headers["Cache-Control"]["schema"] == {
            "type": "string",
            "const": "no-store",
        }
        assert headers["Referrer-Policy"]["schema"] == {
            "type": "string",
            "const": "no-referrer",
        }
        assert headers["Content-Security-Policy"]["schema"] == {
            "type": "string",
            "const": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        }
        assert headers["X-Frame-Options"]["schema"] == {
            "type": "string",
            "const": "DENY",
        }

    assert run_headers["X-Run-ID"]["schema"] == {"type": "string"}
    assert run_headers["X-Trace-Path"]["schema"] == {"type": "string"}
    assert unauthorized_headers["WWW-Authenticate"]["schema"] == {
        "type": "string",
        "const": "Bearer",
    }
    assert request_timeout_headers["Retry-After"]["schema"] == {
        "type": "string",
        "const": "1",
    }
    assert rate_limited_headers["Retry-After"]["schema"] == {
        "type": "string",
        "pattern": r"^[1-9]\d*$",
    }
    assert busy_headers["Retry-After"]["schema"] == {
        "type": "string",
        "const": "1",
    }


def test_service_contract_documents_stable_operation_ids():
    payload = service_openapi()

    assert payload["paths"]["/health"]["get"]["operationId"] == "getHealth"
    assert payload["paths"]["/health"]["head"]["operationId"] == "headHealth"
    assert payload["paths"]["/ready"]["get"]["operationId"] == "getReady"
    assert payload["paths"]["/ready"]["head"]["operationId"] == "headReady"
    assert payload["paths"]["/config"]["get"]["operationId"] == "getConfig"
    assert payload["paths"]["/version"]["get"]["operationId"] == "getVersion"
    assert payload["paths"]["/tools"]["get"]["operationId"] == "getTools"
    assert payload["paths"]["/runtime/tools"]["get"]["operationId"] == "getRuntimeTools"
    assert payload["paths"]["/metrics"]["get"]["operationId"] == "getMetrics"
    assert payload["paths"]["/metrics.prom"]["get"]["operationId"] == "getPrometheusMetrics"
    assert payload["paths"]["/openapi.json"]["get"]["operationId"] == "getOpenApi"
    assert payload["paths"]["/run"]["options"]["operationId"] == "optionsRun"
    assert payload["paths"]["/run"]["post"]["operationId"] == "postRun"
    assert payload["paths"]["/runtime/resume"]["post"]["operationId"] == "postRuntimeResume"
    assert payload["paths"]["/runtime/approvals"]["get"]["operationId"] == (
        "listRuntimeApprovals"
    )
    assert payload["paths"]["/runtime/approvals/summary"]["get"]["operationId"] == (
        "summarizeRuntimeApprovals"
    )
    assert payload["paths"]["/runtime/policy"]["get"]["operationId"] == (
        "getRuntimePolicy"
    )
    assert payload["paths"]["/runtime/runs"]["get"]["operationId"] == "listRuntimeRuns"
    assert payload["paths"]["/runtime/runs/summary"]["get"]["operationId"] == (
        "summarizeRuntimeRuns"
    )
    assert payload["paths"]["/runtime/runs/{run_id}"]["get"]["operationId"] == (
        "getRuntimeRunStatus"
    )
    assert payload["paths"]["/runtime/runs/{run_id}/timeline"]["get"][
        "operationId"
    ] == "getRuntimeTimeline"
    assert payload["paths"]["/runtime/runs/{run_id}/artifacts"]["get"][
        "operationId"
    ] == "listRuntimeArtifacts"
    assert payload["paths"]["/runtime/runs/{run_id}/artifacts/{artifact_id}"]["get"][
        "operationId"
    ] == "getRuntimeArtifact"


def test_service_contract_documents_optionally_protected_diagnostic_endpoints():
    payload = service_openapi()

    for route in [
        "/config",
        "/tools",
        "/runtime/tools",
        "/runtime/policy",
        "/runtime/approvals",
        "/runtime/approvals/summary",
        "/runtime/runs",
        "/runtime/runs/summary",
        "/runtime/runs/{run_id}/timeline",
        "/runtime/runs/{run_id}/artifacts",
        "/runtime/runs/{run_id}/artifacts/{artifact_id}",
        "/runtime/runs/{run_id}",
        "/metrics",
        "/metrics.prom",
        "/openapi.json",
    ]:
        operation = payload["paths"][route]["get"]

        assert operation["security"] == [{"BearerAuth": []}, {}]
        assert "diagnostic protection" in operation["description"]


def test_service_contract_documents_probe_and_prometheus_responses():
    payload = service_openapi()

    head_response = payload["paths"]["/health"]["head"]["responses"]["200"]
    head_ready_responses = payload["paths"]["/ready"]["head"]["responses"]
    options_response = payload["paths"]["/run"]["options"]["responses"]["204"]
    prometheus_response = payload["paths"]["/metrics.prom"]["get"]["responses"]["200"]

    assert head_response["description"] == "Service is live"
    assert head_response["headers"]["X-Request-ID"]["schema"] == {"type": "string"}
    assert head_ready_responses["200"]["description"] == "Service is ready"
    assert head_ready_responses["503"]["description"] == "Service is not ready"
    assert head_ready_responses["200"]["headers"]["Cache-Control"]["schema"]["const"] == (
        "no-store"
    )
    assert options_response["headers"]["Allow"]["schema"] == {
        "type": "string",
        "const": "GET, HEAD, OPTIONS, POST",
    }
    assert options_response["headers"]["Cache-Control"]["schema"]["const"] == "no-store"
    assert prometheus_response["content"]["text/plain"]["schema"] == {"type": "string"}
