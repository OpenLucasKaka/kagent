from __future__ import annotations

from kagent.providers.llm import FakeLLMProvider
from kagent.runtime import run_runtime_agent
from kagent.runtime.context import RuntimeContextManager


def test_runtime_context_manager_compacts_long_strings_and_counts_truncation():
    manager = RuntimeContextManager(max_string_chars=5)

    compacted = manager.compact_value({"text": "abcdefghij"})
    report = manager.report()

    assert compacted == {
        "text": {
            "text_prefix": "abcde",
            "original_chars": 10,
            "truncated_chars": 5,
        }
    }
    assert report["truncated_string_count"] == "1"
    assert report["truncated_chars"] == "5"


def test_runtime_context_manager_omits_artifact_content_from_prompt_payload():
    manager = RuntimeContextManager(max_string_chars=500)

    compacted = manager.compact_observation_output(
        {
            "artifact_id": "artifact-1",
            "title": "Launch report",
            "kind": "report",
            "format": "markdown",
            "content": "sensitive detail",
            "tags": ["launch"],
            "bytes": 16,
        }
    )

    assert compacted == {
        "artifact_id": "artifact-1",
        "title": "Launch report",
        "kind": "report",
        "format": "markdown",
        "tags": ["launch"],
        "bytes": 16,
        "content_omitted": True,
    }
    assert manager.report()["omitted_artifact_content_count"] == "1"


def test_runtime_agent_reports_prompt_context_manager_statistics():
    provider = FakeLLMProvider('{"actions":[],"final_answer":"ok"}')

    result = run_runtime_agent("inspect context manager", provider=provider)

    assert result["prompt_observation_compaction"]["strategy"] == "runtime_context_manager"
    assert result["prompt_observation_compaction"]["max_string_chars"] == "500"
    assert "truncated_string_count" in result["prompt_observation_compaction"]
