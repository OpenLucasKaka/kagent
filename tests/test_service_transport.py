import json

from self_correcting_langgraph_agent.service import transport as service_transport
from self_correcting_langgraph_agent.service.transport import (
    CACHE_CONTROL_HEADER_VALUE,
    error_code_from_payload,
    response_body,
)


def test_response_body_encodes_json_payload_with_stable_content_type():
    data, content_type = response_body({"status": "ok"})

    assert json.loads(data.decode("utf-8")) == {"status": "ok"}
    assert content_type == "application/json"


def test_response_body_encodes_prometheus_text_payload_with_text_content_type():
    data, content_type = response_body("metric_total 1\n")

    assert data == b"metric_total 1\n"
    assert content_type == "text/plain; version=0.0.4; charset=utf-8"


def test_cache_control_header_value_disables_response_storage():
    assert CACHE_CONTROL_HEADER_VALUE == "no-store"


def test_referrer_policy_header_value_disables_referrer_leakage():
    assert service_transport.REFERRER_POLICY_HEADER_VALUE == "no-referrer"


def test_error_code_from_payload_returns_empty_for_success_payloads():
    assert error_code_from_payload({"status": "ok"}) == ""
    assert error_code_from_payload("metric_total 1\n") == ""


def test_error_code_from_payload_extracts_structured_failure_code():
    assert (
        error_code_from_payload(
            {
                "status": "failed",
                "error_code": "not_found",
                "error": "not found",
            }
        )
        == "not_found"
    )
