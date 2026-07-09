from __future__ import annotations

import json
import urllib.error

from kagent.providers.embeddings import (
    EmbeddingProviderConfig,
    OpenAICompatibleEmbeddingProvider,
)


def test_embedding_provider_config_reads_env_with_llm_fallback_without_key_leak():
    config = EmbeddingProviderConfig.from_env(
        {
            "KAGENT_LLM_BASE_URL": "https://llm.example/v1",
            "KAGENT_LLM_API_KEY": "llm-key",
            "KAGENT_EMBEDDING_MODEL": "text-embedding-model",
            "KAGENT_EMBEDDING_TIMEOUT_SECONDS": "9.5",
            "KAGENT_EMBEDDING_MAX_RETRIES": "4",
            "KAGENT_EMBEDDING_RETRY_BACKOFF_SECONDS": "0.75",
        }
    )

    assert config.base_url == "https://llm.example/v1"
    assert config.api_key == "llm-key"
    assert config.model == "text-embedding-model"
    assert config.timeout_seconds == 9.5
    assert config.max_retries == 4
    assert config.retry_backoff_seconds == 0.75
    assert config.redacted_snapshot() == {
        "embedding_provider": "openai_compatible",
        "embedding_base_url": "https://llm.example/v1",
        "embedding_model": "text-embedding-model",
        "embedding_api_key_configured": "true",
        "embedding_timeout_seconds": "9.5",
        "embedding_max_retries": "4",
        "embedding_retry_backoff_seconds": "0.75",
    }
    assert "llm-key" not in str(config.redacted_snapshot())


def test_embedding_provider_posts_openai_compatible_embedding_request():
    requests = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps({"data": [{"embedding": [0.1, 0.2, 0.3]}]}).encode(
                "utf-8"
            )

    def urlopen(request, *, timeout):
        requests.append(
            {
                "url": request.full_url,
                "headers": dict(request.header_items()),
                "body": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return FakeResponse()

    provider = OpenAICompatibleEmbeddingProvider(
        EmbeddingProviderConfig(
            base_url="https://llm.example/v1",
            api_key="secret-key",
            model="embed-model",
            timeout_seconds=3.0,
        ),
        urlopen=urlopen,
    )

    vector = provider.embed("remember this")

    assert vector == [0.1, 0.2, 0.3]
    assert requests == [
        {
            "url": "https://llm.example/v1/embeddings",
            "headers": {
                "Content-type": "application/json",
                "Authorization": "Bearer secret-key",
            },
            "body": {"input": "remember this", "model": "embed-model"},
            "timeout": 3.0,
        }
    ]


def test_embedding_provider_retries_retryable_http_failures():
    attempts = []
    sleeps = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps({"data": [{"embedding": [0.4, 0.5]}]}).encode(
                "utf-8"
            )

    def urlopen(_request, *, timeout):
        attempts.append(timeout)
        if len(attempts) == 1:
            raise urllib.error.HTTPError(
                url="https://llm.example/v1/embeddings",
                code=429,
                msg="rate limited",
                hdrs={},
                fp=None,
            )
        return FakeResponse()

    provider = OpenAICompatibleEmbeddingProvider(
        EmbeddingProviderConfig(
            base_url="https://llm.example/v1",
            api_key="secret-key",
            model="embed-model",
            timeout_seconds=3.0,
            max_retries=1,
            retry_backoff_seconds=0.2,
        ),
        urlopen=urlopen,
        sleep=sleeps.append,
    )

    assert provider.embed("remember this") == [0.4, 0.5]
    assert attempts == [3.0, 3.0]
    assert sleeps == [0.2]


def test_embedding_provider_failure_message_does_not_expose_api_key():
    def urlopen(_request, *, timeout):
        raise urllib.error.HTTPError(
            url="https://llm.example/v1/embeddings",
            code=401,
            msg="bad key secret-key",
            hdrs={},
            fp=None,
        )

    provider = OpenAICompatibleEmbeddingProvider(
        EmbeddingProviderConfig(
            base_url="https://llm.example/v1",
            api_key="secret-key",
            model="embed-model",
            max_retries=0,
        ),
        urlopen=urlopen,
    )

    try:
        provider.embed("remember this")
    except RuntimeError as exc:
        assert "secret-key" not in str(exc)
        assert "http_status=401" in str(exc)
    else:
        raise AssertionError("embedding provider HTTPError was not raised")
