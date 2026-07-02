import io
import urllib.error

from self_correcting_langgraph_agent.providers.llm import (
    FakeLLMProvider,
    LLMProviderConfig,
    OpenAICompatibleProvider,
    SequentialFakeLLMProvider,
)


def test_provider_config_reads_openai_compatible_environment_without_exposing_key():
    config = LLMProviderConfig.from_env(
        {
            "SELF_CORRECTING_LLM_BASE_URL": "https://llm.example/v1",
            "SELF_CORRECTING_LLM_API_KEY": "secret-key",
            "SELF_CORRECTING_LLM_MODEL": "agent-model",
            "SELF_CORRECTING_LLM_TIMEOUT_SECONDS": "12.5",
            "SELF_CORRECTING_LLM_MAX_RETRIES": "2",
            "SELF_CORRECTING_LLM_RETRY_BACKOFF_SECONDS": "0.25",
        }
    )

    assert config.base_url == "https://llm.example/v1"
    assert config.model == "agent-model"
    assert config.timeout_seconds == 12.5
    assert config.max_retries == 2
    assert config.retry_backoff_seconds == 0.25
    assert config.redacted_snapshot() == {
        "llm_provider": "openai_compatible",
        "llm_base_url": "https://llm.example/v1",
        "llm_model": "agent-model",
        "llm_api_key_configured": "true",
        "llm_timeout_seconds": "12.5",
        "llm_max_retries": "2",
        "llm_retry_backoff_seconds": "0.25",
    }
    assert "secret-key" not in str(config.redacted_snapshot())


def test_provider_config_defaults_to_unconfigured_runtime():
    config = LLMProviderConfig.from_env({})

    assert config.redacted_snapshot() == {
        "llm_provider": "unconfigured",
        "llm_base_url": "",
        "llm_model": "",
        "llm_api_key_configured": "false",
        "llm_timeout_seconds": "30.0",
        "llm_max_retries": "2",
        "llm_retry_backoff_seconds": "0.25",
    }


def test_fake_llm_provider_returns_configured_text_response():
    provider = FakeLLMProvider('{"actions": []}')

    assert provider.complete("system", "user") == '{"actions": []}'
    assert provider.calls == [{"system": "system", "user": "user"}]


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
            api_key="secret-key",
            model="agent-model",
            max_retries=1,
        ),
        urlopen=open_url,
        sleep=lambda seconds: None,
    )

    assert provider.complete("system", "user") == '{"actions":[]}'
    assert len(calls) == 2


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
            api_key="secret-key",
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
            api_key="secret-key",
            model="agent-model",
            max_retries=1,
        ),
        urlopen=open_url,
        sleep=lambda seconds: None,
    )

    assert provider.complete("system", "user") == '{"actions":[]}'
    assert len(calls) == 2


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
            api_key="secret-key",
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
        assert "[redacted]" in message
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
