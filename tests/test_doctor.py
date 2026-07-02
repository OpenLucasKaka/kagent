import json
import os
import subprocess
import sys

from self_correcting_langgraph_agent.ops.doctor import doctor_payload
from self_correcting_langgraph_agent.providers.llm import LLMProviderConfig
from self_correcting_langgraph_agent.service.runtime import ServiceConfig


def test_doctor_payload_reports_readiness_config_version_and_tool_count(tmp_path):
    payload = doctor_payload(ServiceConfig(trace_dir=str(tmp_path / "traces")))

    assert payload["status"] == "ready"
    assert payload["readiness"]["status"] == "ready"
    assert payload["readiness"]["checks"]["trace_persistence"] == "ok"
    assert payload["config"]["trace_persistence"] == "enabled"
    assert payload["version"] == "0.1.0"
    assert int(payload["tool_count"]) > 0
    assert payload["runtime_policy"]["trace_type"] == "codex_runtime"
    assert payload["runtime_policy"]["effective_policy_source"] == "default"
    assert payload["runtime_policy"]["effective_allowed_tool_count"] == "10"
    assert "open_url" in payload["runtime_policy"]["effective_allowed_tools"]
    assert len(payload["runtime_policy"]["effective_tool_policy_sha256"]) == 64


def test_doctor_payload_reports_runtime_policy_without_tokens(tmp_path):
    payload = doctor_payload(
        ServiceConfig(
            trace_dir=str(tmp_path / "traces"),
            auth_token="long-random-admin-token",
            auth_tokens={"team-a": "long-random-team-token"},
            runtime_allowed_tools=("note",),
            runtime_allowed_tools_by_subject={"team-a": ("artifact", "note")},
        )
    )

    serialized = json.dumps(payload)

    assert payload["runtime_policy"]["effective_policy_source"] == "global"
    assert payload["runtime_policy"]["effective_allowed_tools"] == ["note"]
    assert payload["runtime_policy"]["subject_policy_count"] == "1"
    assert payload["runtime_policy"]["effective_allowed_tool_count"] == "1"
    assert payload["runtime_policy"]["approval_required_tool_count"] == "10"
    assert "long-random-admin-token" not in serialized
    assert "long-random-team-token" not in serialized


def test_doctor_payload_warns_when_public_bind_has_no_auth_token():
    payload = doctor_payload(ServiceConfig(host="0.0.0.0", auth_token=""))

    assert payload["status"] == "ready"
    assert payload["policy"]["status"] == "warning"
    assert payload["policy"]["warnings"] == ["public_bind_without_auth"]
    assert payload["policy"]["failures"] == []


def test_doctor_payload_can_require_auth_for_release_gates():
    payload = doctor_payload(ServiceConfig(auth_token=""), require_auth=True)

    assert payload["status"] == "not_ready"
    assert payload["policy"]["status"] == "failed"
    assert payload["policy"]["failures"] == ["auth_required"]


def test_doctor_payload_require_auth_rejects_unsafe_auth_token():
    payload = doctor_payload(
        ServiceConfig(auth_token="long-random-token-é"),
        require_auth=True,
    )

    assert payload["status"] == "not_ready"
    assert payload["policy"]["status"] == "failed"
    assert payload["policy"]["failures"] == ["auth_token_unsafe"]


def test_doctor_payload_require_auth_rejects_placeholder_auth_token():
    payload = doctor_payload(
        ServiceConfig(auth_token="replace-with-a-long-random-token"),
        require_auth=True,
    )

    assert payload["status"] == "not_ready"
    assert payload["policy"]["status"] == "failed"
    assert payload["policy"]["failures"] == ["auth_token_placeholder"]


def test_doctor_payload_production_rejects_short_auth_token(tmp_path):
    payload = doctor_payload(
        ServiceConfig(
            auth_token="short-token",
            trace_dir=str(tmp_path / "traces"),
            rate_limit_per_minute=60,
            max_concurrent_runs=4,
            protect_diagnostics=True,
        ),
        require_production_controls=True,
    )

    assert payload["status"] == "not_ready"
    assert payload["policy"]["status"] == "failed"
    assert payload["policy"]["failures"] == ["auth_token_too_short"]


def test_doctor_payload_production_rejects_placeholder_auth_token(tmp_path):
    payload = doctor_payload(
        ServiceConfig(
            auth_token="replace-with-a-long-random-token",
            trace_dir=str(tmp_path / "traces"),
            rate_limit_per_minute=60,
            max_concurrent_runs=4,
            protect_diagnostics=True,
        ),
        require_production_controls=True,
    )

    assert payload["status"] == "not_ready"
    assert payload["policy"]["status"] == "failed"
    assert payload["policy"]["failures"] == ["auth_token_placeholder"]


def test_doctor_payload_production_rejects_unsafe_auth_token(tmp_path):
    payload = doctor_payload(
        ServiceConfig(
            auth_token="long-random-token-é",
            trace_dir=str(tmp_path / "traces"),
            rate_limit_per_minute=60,
            max_concurrent_runs=4,
            protect_diagnostics=True,
        ),
        require_production_controls=True,
    )

    assert payload["status"] == "not_ready"
    assert payload["policy"]["status"] == "failed"
    assert payload["policy"]["failures"] == ["auth_token_unsafe"]


def test_doctor_payload_production_rejects_full_trace_http_responses(tmp_path):
    payload = doctor_payload(
        ServiceConfig(
            auth_token="long-random-token",
            trace_dir=str(tmp_path / "traces"),
            rate_limit_per_minute=60,
            max_concurrent_runs=4,
            protect_diagnostics=True,
            allow_full_trace_response=True,
        ),
        require_production_controls=True,
    )

    assert payload["status"] == "not_ready"
    assert payload["policy"]["status"] == "failed"
    assert payload["policy"]["failures"] == ["full_trace_response_must_be_disabled"]


def test_doctor_payload_can_require_production_controls():
    payload = doctor_payload(
        ServiceConfig(
            host="0.0.0.0",
            auth_token="",
            trace_dir="",
            rate_limit_per_minute=0,
            max_concurrent_runs=0,
        ),
        require_production_controls=True,
    )

    assert payload["status"] == "not_ready"
    assert payload["policy"]["status"] == "failed"
    assert payload["policy"]["failures"] == [
        "auth_required",
        "trace_dir_required",
        "rate_limit_required",
        "concurrency_limit_required",
        "diagnostics_protection_required",
    ]


def test_doctor_payload_passes_production_controls_when_required_controls_exist(tmp_path):
    payload = doctor_payload(
        ServiceConfig(
            host="0.0.0.0",
            auth_token="long-random-token",
            trace_dir=str(tmp_path / "traces"),
            rate_limit_per_minute=60,
            max_concurrent_runs=4,
            protect_diagnostics=True,
        ),
        require_production_controls=True,
    )

    assert payload["status"] == "ready"
    assert payload["policy"]["status"] == "ok"
    assert payload["policy"]["failures"] == []


def test_doctor_payload_reports_unusable_sqlite_idempotency_cache_path(tmp_path):
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("not a directory", encoding="utf-8")

    payload = doctor_payload(
        ServiceConfig(
            idempotency_cache_size=8,
            idempotency_cache_path=str(blocked_parent / "idempotency.sqlite3"),
        )
    )

    assert payload["status"] == "not_ready"
    assert payload["readiness"]["checks"]["idempotency_cache_persistence"] == (
        "failed: idempotency_cache_unavailable"
    )
    assert payload["policy"]["status"] == "ok"


def test_doctor_payload_accepts_named_internal_auth_tokens_for_production(tmp_path):
    payload = doctor_payload(
        ServiceConfig(
            host="0.0.0.0",
            auth_tokens={"team-a": "long-random-team-token"},
            trace_dir=str(tmp_path / "traces"),
            rate_limit_per_minute=60,
            max_concurrent_runs=4,
            protect_diagnostics=True,
        ),
        require_production_controls=True,
    )

    assert payload["status"] == "ready"
    assert payload["policy"]["status"] == "ok"
    assert payload["policy"]["failures"] == []


def test_doctor_payload_runtime_provider_gate_rejects_missing_provider_config(tmp_path):
    payload = doctor_payload(
        ServiceConfig(
            auth_token="long-random-token",
            trace_dir=str(tmp_path / "traces"),
            rate_limit_per_minute=60,
            max_concurrent_runs=4,
            protect_diagnostics=True,
            runtime_max_iterations=1,
        ),
        require_production_controls=True,
        require_runtime_provider=True,
        llm_config=LLMProviderConfig(),
    )

    assert payload["status"] == "not_ready"
    assert payload["policy"]["status"] == "failed"
    assert payload["policy"]["failures"] == [
        "llm_base_url_required",
        "llm_model_required",
        "llm_api_key_required",
        "runtime_iterations_too_low",
    ]


def test_doctor_payload_runtime_provider_gate_passes_when_provider_is_configured(tmp_path):
    payload = doctor_payload(
        ServiceConfig(
            auth_token="long-random-token",
            trace_dir=str(tmp_path / "traces"),
            rate_limit_per_minute=60,
            max_concurrent_runs=4,
            protect_diagnostics=True,
            runtime_max_iterations=2,
        ),
        require_production_controls=True,
        require_runtime_provider=True,
        llm_config=LLMProviderConfig(
            base_url="https://llm.example.test/v1",
            api_key="provider-token",
            model="agent-runtime-model",
        ),
    )

    assert payload["status"] == "ready"
    assert payload["policy"]["status"] == "ok"
    assert payload["policy"]["failures"] == []


def test_doctor_module_require_auth_exits_nonzero_when_auth_is_missing():
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "self_correcting_langgraph_agent.ops.doctor",
            "--require-auth",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "not_ready"
    assert payload["policy"]["failures"] == ["auth_required"]


def test_doctor_module_require_auth_rejects_unsafe_auth_token():
    env = os.environ.copy()
    env["SELF_CORRECTING_SERVICE_AUTH_TOKEN"] = "long-random-token-é"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "self_correcting_langgraph_agent.ops.doctor",
            "--require-auth",
        ],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "not_ready"
    assert payload["policy"]["failures"] == ["auth_token_unsafe"]


def test_doctor_module_require_auth_rejects_placeholder_auth_token():
    env = os.environ.copy()
    env["SELF_CORRECTING_SERVICE_AUTH_TOKEN"] = "replace-with-a-long-random-token"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "self_correcting_langgraph_agent.ops.doctor",
            "--require-auth",
        ],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "not_ready"
    assert payload["policy"]["failures"] == ["auth_token_placeholder"]


def test_doctor_module_production_exits_nonzero_when_controls_are_missing():
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "self_correcting_langgraph_agent.ops.doctor",
            "--production",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "not_ready"
    assert payload["policy"]["failures"] == [
        "auth_required",
        "trace_dir_required",
        "rate_limit_required",
        "diagnostics_protection_required",
    ]


def test_doctor_module_production_rejects_full_trace_http_responses(tmp_path):
    env = os.environ.copy()
    env.update(
        {
            "SELF_CORRECTING_SERVICE_AUTH_TOKEN": "long-random-token",
            "SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE": "60",
            "SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS": "4",
            "SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS": "true",
            "SELF_CORRECTING_SERVICE_ALLOW_FULL_TRACE_RESPONSE": "true",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "self_correcting_langgraph_agent.ops.doctor",
            "--production",
            "--trace-dir",
            str(tmp_path / "traces"),
        ],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "not_ready"
    assert payload["policy"]["failures"] == ["full_trace_response_must_be_disabled"]


def test_doctor_module_production_rejects_placeholder_auth_token(tmp_path):
    env = os.environ.copy()
    env.update(
        {
            "SELF_CORRECTING_SERVICE_AUTH_TOKEN": "replace-with-a-long-random-token",
            "SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE": "60",
            "SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS": "4",
            "SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS": "true",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "self_correcting_langgraph_agent.ops.doctor",
            "--production",
            "--trace-dir",
            str(tmp_path / "traces"),
        ],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "not_ready"
    assert payload["policy"]["failures"] == ["auth_token_placeholder"]


def test_doctor_module_production_rejects_unsafe_auth_token(tmp_path):
    env = os.environ.copy()
    env.update(
        {
            "SELF_CORRECTING_SERVICE_AUTH_TOKEN": "long-random-token-é",
            "SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE": "60",
            "SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS": "4",
            "SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS": "true",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "self_correcting_langgraph_agent.ops.doctor",
            "--production",
            "--trace-dir",
            str(tmp_path / "traces"),
        ],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "not_ready"
    assert payload["policy"]["failures"] == ["auth_token_unsafe"]


def test_doctor_module_runtime_provider_gate_reads_llm_environment(tmp_path):
    env = os.environ.copy()
    env.update(
        {
            "SELF_CORRECTING_SERVICE_AUTH_TOKEN": "long-random-token",
            "SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE": "60",
            "SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS": "4",
            "SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS": "true",
            "SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS": "2",
            "SELF_CORRECTING_LLM_BASE_URL": "https://llm.example.test/v1",
            "SELF_CORRECTING_LLM_API_KEY": "provider-token",
            "SELF_CORRECTING_LLM_MODEL": "agent-runtime-model",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "self_correcting_langgraph_agent.ops.doctor",
            "--production",
            "--require-runtime-provider",
            "--trace-dir",
            str(tmp_path / "traces"),
        ],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 0
    assert payload["status"] == "ready"
    assert payload["policy"]["failures"] == []
    assert payload["config"]["llm_api_key_configured"] == "true"


def test_doctor_module_runtime_provider_gate_exits_nonzero_when_missing_provider(tmp_path):
    env = os.environ.copy()
    env.update(
        {
            "SELF_CORRECTING_SERVICE_AUTH_TOKEN": "long-random-token",
            "SELF_CORRECTING_SERVICE_RATE_LIMIT_PER_MINUTE": "60",
            "SELF_CORRECTING_SERVICE_MAX_CONCURRENT_RUNS": "4",
            "SELF_CORRECTING_SERVICE_PROTECT_DIAGNOSTICS": "true",
            "SELF_CORRECTING_SERVICE_RUNTIME_MAX_ITERATIONS": "1",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "self_correcting_langgraph_agent.ops.doctor",
            "--production",
            "--require-runtime-provider",
            "--trace-dir",
            str(tmp_path / "traces"),
        ],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "not_ready"
    assert payload["policy"]["failures"] == [
        "llm_base_url_required",
        "llm_model_required",
        "llm_api_key_required",
        "runtime_iterations_too_low",
    ]


def test_doctor_module_preserves_idempotency_cache_size_from_environment(tmp_path):
    env = os.environ.copy()
    env["SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_SIZE"] = "17"
    env["SELF_CORRECTING_SERVICE_IDEMPOTENCY_CACHE_PATH"] = str(
        tmp_path / "idempotency.sqlite3"
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "self_correcting_langgraph_agent.ops.doctor",
            "--trace-dir",
            str(tmp_path / "traces"),
        ],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 0
    assert payload["config"]["idempotency_cache_size"] == "17"
    assert payload["config"]["idempotency_cache_backend"] == "sqlite"
    assert payload["config"]["idempotency_cache_path_configured"] == "true"


def test_doctor_module_reports_invalid_environment_config_without_traceback():
    env = os.environ.copy()
    env["SELF_CORRECTING_SERVICE_PORT"] = "not-a-port"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "self_correcting_langgraph_agent.ops.doctor",
            "--production",
        ],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )

    assert completed.returncode == 2
    assert "SELF_CORRECTING_SERVICE_PORT must be an integer" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_doctor_module_exits_nonzero_when_self_check_fails(tmp_path):
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("blocks trace directory creation")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "self_correcting_langgraph_agent.ops.doctor",
            "--trace-dir",
            str(blocking_file / "traces"),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["status"] == "not_ready"
    assert payload["readiness"]["checks"]["trace_persistence"].startswith("failed:")
