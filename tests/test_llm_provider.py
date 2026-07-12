import io
import stat
import urllib.error
from pathlib import Path

import kagent.providers.llm as llm_provider
from kagent.providers.llm import (
    DEFAULT_LLM_MODEL,
    FakeLLMProvider,
    LLMProviderConfig,
    OpenAICompatibleProvider,
    ProviderKind,
    SequentialFakeLLMProvider,
    build_llm_provider,
    default_provider_config_path,
    detect_provider_kind,
    load_provider_config,
    missing_provider_config_fields,
    provider_display_name,
    provider_setup_options,
    save_provider_config,
    validate_provider_setup_config,
)


def test_provider_config_reads_openai_compatible_environment_without_exposing_key():
    config = LLMProviderConfig.from_env(
        {
            "KAGENT_LLM_PROVIDER": "deepseek",
            "KAGENT_LLM_BASE_URL": "https://llm.example/v1",
            "KAGENT_LLM_API_KEY": "redactme",
            "KAGENT_LLM_MODEL": "agent-model",
            "KAGENT_LLM_TIMEOUT_SECONDS": "12.5",
            "KAGENT_LLM_MAX_RETRIES": "2",
            "KAGENT_LLM_RETRY_BACKOFF_SECONDS": "0.25",
        }
    )

    assert config.provider == ProviderKind.DEEPSEEK
    assert config.base_url == "https://llm.example/v1"
    assert config.model == "agent-model"
    assert config.timeout_seconds == 12.5
    assert config.max_retries == 2
    assert config.retry_backoff_seconds == 0.25
    assert config.redacted_snapshot() == {
        "llm_provider": "deepseek",
        "llm_provider_display_name": "DeepSeek",
        "llm_base_url": "configured",
        "llm_base_url_configured": "true",
        "llm_model": "agent-model",
        "llm_api_key_configured": "true",
        "llm_timeout_seconds": "12.5",
        "llm_max_retries": "2",
        "llm_retry_backoff_seconds": "0.25",
    }
    assert "redactme" not in str(config.redacted_snapshot())
    assert "https://llm.example/v1" not in str(config.redacted_snapshot())


def test_provider_config_defaults_to_unconfigured_runtime():
    config = LLMProviderConfig.from_env({})

    assert config.redacted_snapshot() == {
        "llm_provider": "unconfigured",
        "llm_provider_display_name": "Unconfigured",
        "llm_base_url": "",
        "llm_base_url_configured": "false",
        "llm_model": "",
        "llm_api_key_configured": "false",
        "llm_timeout_seconds": "30.0",
        "llm_max_retries": "2",
        "llm_retry_backoff_seconds": "0.25",
    }


def test_provider_config_can_be_saved_loaded_and_overridden_by_env(tmp_path):
    config_path = tmp_path / "provider.json"

    saved_path = save_provider_config(
        LLMProviderConfig(
            provider=ProviderKind.QWEN_OPENAI_COMPATIBLE,
            base_url="https://stored.example/v1",
            api_key="stored-key",
            model=DEFAULT_LLM_MODEL,
        ),
        str(config_path),
    )

    loaded = load_provider_config(str(config_path))
    merged = LLMProviderConfig.from_sources(
        {
            "KAGENT_LLM_BASE_URL": "https://env.example/v1",
            "KAGENT_LLM_MODEL": "env-model",
        },
        config_path=str(config_path),
    )

    assert saved_path == str(config_path)
    assert loaded.provider == ProviderKind.QWEN_OPENAI_COMPATIBLE
    assert loaded.base_url == "https://stored.example/v1"
    assert loaded.api_key == "stored-key"
    assert loaded.model == DEFAULT_LLM_MODEL
    assert merged.base_url == "https://env.example/v1"
    assert merged.api_key == "stored-key"
    assert merged.model == "env-model"
    assert stat.S_IMODE(config_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_provider_config_reinfers_provider_when_env_overrides_base_or_model(tmp_path):
    config_path = tmp_path / "provider.json"
    save_provider_config(
        LLMProviderConfig(
            provider=ProviderKind.QWEN_OPENAI_COMPATIBLE,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="stored-key",
            model="qwen-plus",
        ),
        str(config_path),
    )

    merged = LLMProviderConfig.from_sources(
        {
            "KAGENT_LLM_BASE_URL": "https://api.deepseek.com/v1",
            "KAGENT_LLM_MODEL": "deepseek-chat",
        },
        config_path=str(config_path),
    )

    assert merged.provider == ProviderKind.DEEPSEEK
    assert merged.api_key == "stored-key"


def test_provider_config_keeps_explicit_env_provider_when_url_is_generic(tmp_path):
    config_path = tmp_path / "provider.json"
    save_provider_config(
        LLMProviderConfig(
            provider=ProviderKind.QWEN_OPENAI_COMPATIBLE,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-plus",
        ),
        str(config_path),
    )

    merged = LLMProviderConfig.from_sources(
        {
            "KAGENT_LLM_PROVIDER": "deepseek",
            "KAGENT_LLM_BASE_URL": "https://gateway.example/v1",
            "KAGENT_LLM_MODEL": "gateway-model",
        },
        config_path=str(config_path),
    )

    assert merged.provider == ProviderKind.DEEPSEEK


def test_provider_config_autodetects_provider_when_provider_env_is_missing():
    config = LLMProviderConfig.from_env(
        {
            "KAGENT_LLM_BASE_URL": "https://api.deepseek.com/v1",
            "KAGENT_LLM_MODEL": "deepseek-chat",
        }
    )

    assert config.provider == ProviderKind.DEEPSEEK
    assert config.redacted_snapshot()["llm_provider_display_name"] == "DeepSeek"


def test_detect_provider_kind_uses_url_and_model_hints_conservatively():
    assert (
        detect_provider_kind("https://api.deepseek.com/v1", "deepseek-chat")
        == ProviderKind.DEEPSEEK
    )
    assert (
        detect_provider_kind("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus")
        == ProviderKind.QWEN_OPENAI_COMPATIBLE
    )
    assert (
        detect_provider_kind("http://localhost:11434/v1", "llama3")
        == ProviderKind.OLLAMA_OPENAI_COMPATIBLE
    )
    assert (
        detect_provider_kind("https://company.example/v1", "qwen/qwen3-coder-next")
        == ProviderKind.QWEN_OPENAI_COMPATIBLE
    )
    assert (
        detect_provider_kind("https://company.example/v1", "custom-model")
        == ProviderKind.OPENAI_COMPATIBLE
    )


def test_provider_display_names_are_stable_for_setup_and_audit_output():
    assert provider_display_name(ProviderKind.OPENAI_COMPATIBLE) == "OpenAI-compatible"
    assert provider_display_name(ProviderKind.QWEN_OPENAI_COMPATIBLE) == "Qwen"
    assert provider_display_name("unknown") == "OpenAI-compatible"


def test_provider_setup_options_are_protocol_ready_and_keep_ollama_key_optional():
    options = provider_setup_options("default-model")

    assert [option["provider"] for option in options] == [
        "qwen_openai_compatible",
        "deepseek",
        "ollama_openai_compatible",
        "openai_compatible",
    ]
    assert options[0]["model"] == "default-model"
    assert options[1]["model"] == "deepseek-chat"
    assert options[2]["api_key_required"] is False


def test_validate_provider_setup_config_checks_url_model_and_required_key():
    valid = LLMProviderConfig(
        provider=ProviderKind.DEEPSEEK,
        base_url="https://api.deepseek.com/v1",
        api_key="secret",
        model="deepseek-chat",
    )

    validate_provider_setup_config(valid)

    invalid_configs = [
        (LLMProviderConfig(model="model"), "base_url is required"),
        (
            LLMProviderConfig(base_url="not-a-url", model="model"),
            "absolute http or https URL",
        ),
        (
            LLMProviderConfig(base_url="https://example.com/v1"),
            "model is required",
        ),
        (
            LLMProviderConfig(
                provider=ProviderKind.QWEN_OPENAI_COMPATIBLE,
                base_url="https://example.com/v1",
                model="qwen",
            ),
            "api_key is required",
        ),
    ]
    for config, expected_message in invalid_configs:
        try:
            validate_provider_setup_config(config)
        except ValueError as exc:
            assert expected_message in str(exc)
        else:
            raise AssertionError("invalid provider setup config was accepted")


def test_validate_provider_setup_config_allows_ollama_without_api_key():
    validate_provider_setup_config(
        LLMProviderConfig(
            provider=ProviderKind.OLLAMA_OPENAI_COMPATIBLE,
            base_url="http://localhost:11434/v1",
            model="llama3",
        )
    )


def test_missing_provider_config_fields_requires_keys_only_for_hosted_native_options():
    qwen = LLMProviderConfig(
        provider=ProviderKind.QWEN_OPENAI_COMPATIBLE,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
    )
    custom = LLMProviderConfig(
        provider=ProviderKind.OPENAI_COMPATIBLE,
        base_url="https://gateway.example/v1",
        model="internal-model",
    )

    assert missing_provider_config_fields(qwen) == ["KAGENT_LLM_API_KEY"]
    assert missing_provider_config_fields(custom) == []


def test_build_llm_provider_uses_configured_provider_kind():
    provider = build_llm_provider(
        LLMProviderConfig(
            provider=ProviderKind.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
            api_key="x",
            model="deepseek-chat",
        ),
        urlopen=lambda request, *, timeout: None,
    )

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.config.provider == ProviderKind.DEEPSEEK


def test_default_provider_config_path_uses_kagent_home_after_migration(
    tmp_path,
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        llm_provider,
        "migrate_legacy_kagent_state",
        lambda env: calls.append(env),
        raising=False,
    )

    env = {"HOME": str(tmp_path)}

    assert default_provider_config_path(env) == str(
        tmp_path / ".kagent" / "config" / "provider.json"
    )
    assert calls == [env]


def test_default_provider_config_path_explicit_override_skips_migration(
    tmp_path,
    monkeypatch,
):
    explicit = tmp_path / "explicit.json"
    monkeypatch.setattr(
        llm_provider,
        "migrate_legacy_kagent_state",
        lambda env: (_ for _ in ()).throw(AssertionError("migration called")),
        raising=False,
    )

    assert default_provider_config_path({"KAGENT_LLM_CONFIG_PATH": str(explicit)}) == str(
        explicit
    )


def test_provider_config_rejects_symlink_paths(tmp_path):
    target = tmp_path / "target.json"
    link = tmp_path / "provider-link.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o600)
    link.symlink_to(target)

    try:
        save_provider_config(
            LLMProviderConfig(base_url="https://llm.example/v1", model="agent"),
            str(link),
        )
    except ValueError as exc:
        assert "provider config path must not contain symlinks" in str(exc)
    else:
        raise AssertionError("provider config was saved through a symlink")


def test_provider_config_allows_root_owned_macos_var_alias(tmp_path):
    if not Path("/var").is_symlink() or not str(tmp_path).startswith("/private/var/"):
        return
    aliased_path = Path(str(tmp_path).replace("/private/var/", "/var/", 1)) / "provider.json"

    save_provider_config(
        LLMProviderConfig(
            base_url="https://llm.example/v1",
            model="agent-model",
        ),
        str(aliased_path),
    )

    assert aliased_path.exists()
    assert stat.S_IMODE(aliased_path.stat().st_mode) == 0o600


def test_fake_llm_provider_returns_configured_text_response():
    provider = FakeLLMProvider('{"actions": []}')

    assert provider.complete("system", "user") == '{"actions": []}'
    assert list(provider.stream_complete("system-stream", "user-stream")) == ['{"actions": []}']
    assert provider.calls == [{"system": "system", "user": "user"}]
    assert provider.stream_calls == [{"system": "system-stream", "user": "user-stream"}]


def test_sequential_fake_llm_provider_returns_configured_responses_in_order():
    provider = SequentialFakeLLMProvider(
        ['{"actions": []}', '{"actions": [], "final_answer": "ok"}']
    )

    assert provider.complete("system-1", "user-1") == '{"actions": []}'
    assert provider.complete("system-2", "user-2") == '{"actions": [], "final_answer": "ok"}'
    assert provider.complete("system-3", "user-3") == '{"actions": [], "final_answer": "ok"}'
    assert provider.calls == [
        {"system": "system-1", "user": "user-1"},
        {"system": "system-2", "user": "user-2"},
        {"system": "system-3", "user": "user-3"},
    ]


def test_openai_compatible_provider_retries_transient_http_errors():
    calls = []
    responses = [
        urllib.error.HTTPError(
            url="https://llm.example/v1/chat/completions",
            code=503,
            msg="temporarily unavailable",
            hdrs={},
            fp=io.BytesIO(b"temporary"),
        ),
        _FakeHTTPResponse(
            b'{"choices":[{"message":{"content":"{\\"actions\\":[]}"}}]}'
        ),
    ]

    def open_url(request, *, timeout):
        calls.append({"request": request, "timeout": timeout})
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    provider = OpenAICompatibleProvider(
        LLMProviderConfig(
            base_url="https://llm.example/v1",
            api_key="x",
            model="agent-model",
            max_retries=1,
        ),
        urlopen=open_url,
        sleep=lambda seconds: None,
    )

    assert provider.complete("system", "user") == '{"actions":[]}'
    assert len(calls) == 2


def test_openai_compatible_provider_streams_chat_completion_deltas():
    calls = []
    response = _FakeHTTPResponse(
        (
            'data: {"choices":[{"delta":{"content":"{\\"actions\\":[],"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"\\"final_answer\\":\\"你"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"好\\"}"}}]}\n\n'
            "data: [DONE]\n\n"
        ).encode("utf-8")
    )

    def open_url(request, *, timeout):
        calls.append({"request": request, "timeout": timeout})
        return response

    provider = OpenAICompatibleProvider(
        LLMProviderConfig(
            base_url="https://llm.example/v1",
            api_key="x",
            model="agent-model",
        ),
        urlopen=open_url,
    )

    assert list(provider.stream_complete("system", "user")) == [
        '{"actions":[],',
        '"final_answer":"你',
        '好"}',
    ]
    request_payload = calls[0]["request"].data.decode("utf-8")
    assert '"stream": true' in request_payload


def test_openai_compatible_provider_does_not_retry_non_transient_http_errors():
    calls = []

    def open_url(request, *, timeout):
        calls.append({"request": request, "timeout": timeout})
        raise urllib.error.HTTPError(
            url="https://llm.example/v1/chat/completions",
            code=400,
            msg="bad request",
            hdrs={},
            fp=io.BytesIO(b"bad request"),
        )

    provider = OpenAICompatibleProvider(
        LLMProviderConfig(
            base_url="https://llm.example/v1",
            api_key="x",
            model="agent-model",
            max_retries=3,
        ),
        urlopen=open_url,
        sleep=lambda seconds: None,
    )

    try:
        provider.complete("system", "user")
    except RuntimeError as exc:
        assert str(exc) == "llm provider request failed: http_status=400 body=bad request"
    else:
        raise AssertionError("expected non-transient provider error")
    assert len(calls) == 1


def test_openai_compatible_provider_retries_model_unloaded_http_errors():
    calls = []
    responses = [
        urllib.error.HTTPError(
            url="https://llm.example/v1/chat/completions",
            code=400,
            msg="bad request",
            hdrs={},
            fp=io.BytesIO(b'{"error":"Model unloaded."}'),
        ),
        _FakeHTTPResponse(
            b'{"choices":[{"message":{"content":"{\\"actions\\":[]}"}}]}'
        ),
    ]

    def open_url(request, *, timeout):
        calls.append({"request": request, "timeout": timeout})
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    provider = OpenAICompatibleProvider(
        LLMProviderConfig(
            base_url="https://llm.example/v1",
            api_key="x",
            model="agent-model",
            max_retries=1,
        ),
        urlopen=open_url,
        sleep=lambda seconds: None,
    )

    assert provider.complete("system", "user") == '{"actions":[]}'
    assert len(calls) == 2
    assert provider.request_diagnostics()["attempt_count"] == "2"
    assert provider.request_diagnostics()["retry_count"] == "1"
    assert provider.request_diagnostics()["status"] == "ok"
    assert provider.request_diagnostics()["stream"] == "false"
    assert float(provider.request_diagnostics()["duration_seconds"]) >= 0


def test_openai_compatible_provider_classifies_exhausted_model_unloaded_errors():
    def open_url(_request, *, timeout):
        raise urllib.error.HTTPError(
            url="https://llm.example/v1/chat/completions",
            code=400,
            msg="bad request",
            hdrs={},
            fp=io.BytesIO(b'{"error":"Model unloaded."}'),
        )

    provider = OpenAICompatibleProvider(
        LLMProviderConfig(
            base_url="https://llm.example/v1",
            api_key="x",
            model="agent-model",
            max_retries=0,
        ),
        urlopen=open_url,
        sleep=lambda seconds: None,
    )

    try:
        provider.complete("system", "user")
    except RuntimeError as exc:
        assert "Model unloaded" in str(exc)
    else:
        raise AssertionError("expected exhausted model unloaded provider error")
    assert provider.request_diagnostics()["status"] == "failed"
    assert provider.request_diagnostics()["error_type"] == "http_error"
    assert provider.request_diagnostics()["http_status"] == "400"
    assert provider.request_diagnostics()["retryable_reason"] == "model_unloaded"


def test_openai_compatible_provider_uses_numeric_retry_after_header():
    calls = []
    sleeps = []
    responses = [
        urllib.error.HTTPError(
            url="https://llm.example/v1/chat/completions",
            code=429,
            msg="rate limited",
            hdrs={"Retry-After": "1.5"},
            fp=io.BytesIO(b"rate limited"),
        ),
        _FakeHTTPResponse(
            b'{"choices":[{"message":{"content":"{\\"actions\\":[]}"}}]}'
        ),
    ]

    def open_url(request, *, timeout):
        calls.append({"request": request, "timeout": timeout})
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    provider = OpenAICompatibleProvider(
        LLMProviderConfig(
            base_url="https://llm.example/v1",
            api_key="x",
            model="agent-model",
            max_retries=1,
            retry_backoff_seconds=0.25,
        ),
        urlopen=open_url,
        sleep=sleeps.append,
    )

    assert provider.complete("system", "user") == '{"actions":[]}'
    assert len(calls) == 2
    assert sleeps == [1.5]


def test_openai_compatible_provider_redacts_secret_like_error_body_values():
    api_key = "sk-" + "test-redaction-token"

    def open_url(request, *, timeout):
        raise urllib.error.HTTPError(
            url="https://llm.example/v1/chat/completions",
            code=401,
            msg="unauthorized",
            hdrs={},
            fp=io.BytesIO(
                f'{{"error":"invalid api key {api_key} for request"}}'.encode()
            ),
        )

    provider = OpenAICompatibleProvider(
        LLMProviderConfig(
            base_url="https://llm.example/v1",
            api_key=api_key,
            model="agent-model",
        ),
        urlopen=open_url,
    )

    try:
        provider.complete("system", "user")
    except RuntimeError as exc:
        message = str(exc)
        assert "http_status=401" in message
        assert api_key not in message
        assert "[REDACTED]" in message
    else:
        raise AssertionError("expected provider error")
    assert provider.request_diagnostics()["attempt_count"] == "1"
    assert provider.request_diagnostics()["retry_count"] == "0"
    assert provider.request_diagnostics()["status"] == "failed"
    assert provider.request_diagnostics()["error_type"] == "http_error"
    assert provider.request_diagnostics()["http_status"] == "401"
    assert api_key not in str(provider.request_diagnostics())


def test_openai_compatible_provider_redacts_bearer_and_url_credentials_from_errors():
    def open_url(request, *, timeout):
        raise urllib.error.HTTPError(
            url="https://llm.example/v1/chat/completions",
            code=500,
            msg="server error",
            hdrs={},
            fp=io.BytesIO(
                b"upstream echoed Authorization: Bearer provider-secret-token "
                b"and callback https://user:password@example.test/path?token=abc123"
            ),
        )

    provider = OpenAICompatibleProvider(
        LLMProviderConfig(
            base_url="https://llm.example/v1",
            api_key="configured-key",
            model="agent-model",
            max_retries=0,
        ),
        urlopen=open_url,
    )

    try:
        provider.complete("system", "user")
    except RuntimeError as exc:
        message = str(exc)
        assert "http_status=500" in message
        assert "provider-secret-token" not in message
        assert "user:password" not in message
        assert "token=abc123" not in message
        assert "[REDACTED]" in message
    else:
        raise AssertionError("expected provider error")


class _FakeHTTPResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self.body

    def readline(self) -> bytes:
        if not hasattr(self, "_lines"):
            self._lines = self.body.splitlines(keepends=True)
            self._line_index = 0
        if self._line_index >= len(self._lines):
            return b""
        line = self._lines[self._line_index]
        self._line_index += 1
        return line
