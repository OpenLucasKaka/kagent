import json

from self_correcting_langgraph_agent.providers.llm import FakeLLMProvider
from self_correcting_langgraph_agent.runtime import run_runtime_agent
from self_correcting_langgraph_agent.runtime import tools as runtime_tools
from self_correcting_langgraph_agent.runtime.policy import RuntimePolicy
from self_correcting_langgraph_agent.runtime.tools import (
    RuntimeToolSpec,
    default_runtime_tools,
)
from self_correcting_langgraph_agent.runtime.types import (
    MAX_ACTION_REASON_CHARS,
    MAX_PLAN_ACTIONS,
    MAX_PLAN_FINAL_ANSWER_CHARS,
)


def test_runtime_entrypoint_is_delegated_to_runtime_agent_module():
    from self_correcting_langgraph_agent.runtime.agent import (
        run_runtime_agent as runtime_agent_run_runtime_agent,
    )

    assert run_runtime_agent is runtime_agent_run_runtime_agent


def test_runtime_agent_runs_fake_llm_plan_through_policy_and_tools():
    provider = FakeLLMProvider(
        '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"},"reason":"capture"}]}'
    )

    result = run_runtime_agent("capture hello", provider=provider)

    assert result["status"] == "done"
    assert result["trace_type"] == "codex_runtime"
    assert result["goal"] == "capture hello"
    assert result["plan"]["actions"][0]["tool"] == "note"
    assert result["observations"][0]["status"] == "ok"
    assert result["observations"][0]["output"] == {"text": "hello"}
    assert result["events"][0]["node"] == "planner"
    assert result["events"][1]["node"] == "policy"
    assert result["events"][2]["node"] == "executor"


def test_runtime_agent_result_includes_run_duration_seconds():
    provider = FakeLLMProvider(
        '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"},"reason":"capture"}]}'
    )

    result = run_runtime_agent("capture hello", provider=provider)

    assert float(result["duration_seconds"]) >= 0
    assert result["duration_seconds"].count(".") == 1
    assert len(result["duration_seconds"].split(".")[1]) == 4


def test_runtime_agent_result_includes_iteration_budget_metadata():
    provider = SequentialLLMProvider(
        [
            (
                '{"actions":[{"id":"step-1","tool":"note",'
                '"input":{"text":"hello"},"reason":"capture"}]}'
            ),
            '{"actions":[],"final_answer":"ok"}',
        ]
    )

    result = run_runtime_agent("capture then finish", provider=provider, max_iterations=3)

    assert result["iteration_count"] == "2"
    assert result["max_iterations"] == "3"
    assert result["iteration_budget_remaining"] == "1"


def test_runtime_agent_result_includes_run_metadata_and_tags():
    provider = FakeLLMProvider(
        '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"},"reason":"capture"}]}'
    )

    result = run_runtime_agent(
        "capture hello",
        provider=provider,
        metadata={"workflow": "launch", "ticket": "REL-123"},
        tags=["ops", "release"],
    )

    assert result["metadata"] == {"ticket": "REL-123", "workflow": "launch"}
    assert result["tags"] == ["ops", "release"]


def test_runtime_agent_result_describes_prompt_observation_compaction():
    provider = FakeLLMProvider('{"actions":[],"final_answer":"ok"}')

    result = run_runtime_agent("inspect prompt compaction", provider=provider)

    assert result["prompt_observation_compaction"] == {
        "artifact_content_omitted": True,
        "max_string_chars": "500",
        "long_string_shape": "text_prefix/original_chars/truncated_chars",
    }


def test_runtime_agent_system_prompt_declares_runtime_identity_boundary():
    provider = FakeLLMProvider('{"actions":[],"final_answer":"ok"}')

    run_runtime_agent("inspect identity boundary", provider=provider)

    system_prompt = provider.calls[0]["system"]
    assert "self-correcting LangGraph agent runtime" in system_prompt
    assert "OpenAI-compatible provider" in system_prompt
    assert "underlying model provider" in system_prompt


def test_runtime_agent_executor_event_includes_tool_timing_metadata():
    provider = FakeLLMProvider(
        '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"},"reason":"capture"}]}'
    )

    result = run_runtime_agent("capture hello", provider=provider)

    observation = result["observations"][0]
    executor_event = result["events"][2]
    assert observation["started_at"].endswith("+00:00")
    assert observation["completed_at"].endswith("+00:00")
    assert float(observation["duration_seconds"]) >= 0
    assert executor_event["duration_seconds"] == observation["duration_seconds"]
    assert executor_event["started_at"] == observation["started_at"]
    assert executor_event["completed_at"] == observation["completed_at"]


def test_runtime_agent_events_include_dependency_status_metadata():
    provider = FakeLLMProvider(
        '{"actions":['
        '{"id":"step-1","tool":"note",'
        '"input":{"text":"hello"},"reason":"capture"},'
        '{"id":"step-2","tool":"note","input":{"text":"done"},'
        '"reason":"persist","depends_on":["step-1"]}'
        "]}"
    )

    result = run_runtime_agent("normalize then persist", provider=provider)

    dependent_policy_event = result["events"][3]
    dependent_executor_event = result["events"][4]
    assert dependent_policy_event["node"] == "policy"
    assert dependent_policy_event["action_id"] == "step-2"
    assert dependent_policy_event["depends_on"] == ["step-1"]
    assert dependent_policy_event["dependency_statuses"] == {"step-1": "ok"}
    assert dependent_executor_event["node"] == "executor"
    assert dependent_executor_event["action_id"] == "step-2"
    assert dependent_executor_event["depends_on"] == ["step-1"]
    assert dependent_executor_event["dependency_statuses"] == {"step-1": "ok"}


def test_runtime_agent_planner_and_policy_events_include_timing_metadata():
    provider = FakeLLMProvider(
        '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"},"reason":"capture"}]}'
    )

    result = run_runtime_agent("capture hello", provider=provider)

    planner_event = result["events"][0]
    policy_event = result["events"][1]
    for event in [planner_event, policy_event]:
        assert event["started_at"].endswith("+00:00")
        assert event["completed_at"].endswith("+00:00")
        assert float(event["duration_seconds"]) >= 0
        assert event["duration_seconds"].count(".") == 1
        assert len(event["duration_seconds"].split(".")[1]) == 4


def test_runtime_agent_reports_policy_denial_as_requires_approval():
    provider = FakeLLMProvider(
        '{"actions":[{"id":"step-1","tool":"http_request","input":{"url":"https://example.com"},"reason":"fetch"}]}'
    )

    result = run_runtime_agent("fetch site", provider=provider)

    assert result["status"] == "requires_approval"
    assert result["observations"][0]["status"] == "requires_approval"
    assert result["observations"][0]["error_code"] == "tool_not_allowed"
    assert result["observations"][0]["started_at"].endswith("+00:00")
    assert result["observations"][0]["completed_at"].endswith("+00:00")
    assert float(result["observations"][0]["duration_seconds"]) >= 0
    assert result["pending_approval"]["id"] == "step-1"
    assert result["pending_approval"]["tool"] == "http_request"
    assert result["events"][1]["started_at"].endswith("+00:00")
    assert result["events"][1]["completed_at"].endswith("+00:00")
    assert float(result["events"][1]["duration_seconds"]) >= 0


def test_runtime_agent_can_execute_action_after_explicit_approval():
    provider = FakeLLMProvider(
        '{"actions":[{"id":"step-1","tool":"transform_text",'
        '"input":{"text":"hello","mode":"uppercase"},"reason":"normalize"}]}'
    )

    result = run_runtime_agent(
        "normalize hello",
        provider=provider,
        policy=RuntimePolicy(allowed_tools={"note"}),
        approved_action_ids={"step-1"},
    )

    assert result["status"] == "done"
    assert result["approved_action_ids"] == ["step-1"]
    assert result["approved_action_count"] == "1"
    assert result["observations"][0]["status"] == "ok"
    assert result["observations"][0]["output"] == {"text": "HELLO"}
    assert result["events"][1]["status"] == "approved"


def test_runtime_agent_executes_http_request_after_explicit_approval(monkeypatch):
    class FakeHeaders:
        def get(self, name, default=""):
            if name == "Content-Type":
                return "text/plain"
            return default

    class FakeResponse:
        status = 200
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, _size):
            return b"hello-approved-http"

    class FakeNoRedirectOpener:
        def open(self, _request, *, timeout):
            assert timeout > 0
            return FakeResponse()

    monkeypatch.setattr(
        runtime_tools.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                runtime_tools.socket.AF_INET,
                runtime_tools.socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 443),
            )
        ],
    )
    monkeypatch.setattr(
        runtime_tools.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            runtime_tools.urllib.error.URLError("unexpected redirect follow")
        ),
    )
    monkeypatch.setattr(
        runtime_tools.urllib.request,
        "build_opener",
        lambda *_handlers: FakeNoRedirectOpener(),
    )
    provider = FakeLLMProvider(
        '{"actions":[{"id":"step-1","tool":"http_request",'
        '"input":{"url":"https://example.com/hello"},"reason":"fetch"}]}'
    )

    result = run_runtime_agent(
        "fetch approved test endpoint",
        provider=provider,
        approved_action_ids={"step-1"},
    )

    assert result["status"] == "done"
    assert result["events"][1]["status"] == "approved"
    assert result["observations"][0]["status"] == "ok"
    assert result["observations"][0]["tool"] == "http_request"
    assert result["observations"][0]["output"]["status_code"] == 200
    assert result["observations"][0]["output"]["body_text"] == "hello-approved-http"


def test_runtime_agent_reports_invalid_llm_plan_as_failed():
    provider = FakeLLMProvider("not-json")

    result = run_runtime_agent("capture hello", provider=provider)

    assert result["status"] == "failed"
    assert result["error_code"] == "invalid_plan"
    assert result["events"][0]["node"] == "planner"
    assert result["events"][0]["started_at"].endswith("+00:00")
    assert result["events"][0]["completed_at"].endswith("+00:00")
    assert float(result["events"][0]["duration_seconds"]) >= 0
    assert float(result["duration_seconds"]) >= 0


def test_runtime_agent_includes_tool_input_and_output_schemas_in_planner_prompt():
    provider = FakeLLMProvider('{"actions":[],"final_answer":"ok"}')

    run_runtime_agent("inspect tools", provider=provider)

    assert "Available tools" in provider.calls[0]["user"]
    assert '"approval_required_by_default"' in provider.calls[0]["user"]
    assert '"input_schema"' in provider.calls[0]["user"]
    assert '"output_schema"' in provider.calls[0]["user"]
    assert '"approval_required_by_default": "true"' in provider.calls[0]["user"]
    assert '"required": ["text", "mode"]' in provider.calls[0]["user"]
    assert '"required": ["text"]' in provider.calls[0]["user"]
    assert '"score_percent"' in provider.calls[0]["user"]
    assert '"enum": ["uppercase", "lowercase", "reverse", "trim"]' in provider.calls[0]["user"]


def test_runtime_agent_system_prompt_includes_plan_limits():
    provider = FakeLLMProvider('{"actions":[],"final_answer":"ok"}')

    run_runtime_agent("inspect plan limits", provider=provider)

    system_prompt = provider.calls[0]["system"]
    assert f"at most {MAX_PLAN_ACTIONS}" in system_prompt
    assert f"reason at most {MAX_ACTION_REASON_CHARS}" in system_prompt
    assert f"final_answer at most {MAX_PLAN_FINAL_ANSWER_CHARS}" in system_prompt
    assert "depends_on" in system_prompt
    assert "prior action IDs" in system_prompt


def test_runtime_agent_system_prompt_distinguishes_open_url_from_http_request():
    provider = FakeLLMProvider('{"actions":[],"final_answer":"ok"}')

    run_runtime_agent("打开 github", provider=provider)

    system_prompt = provider.calls[0]["system"]
    assert "open_url" in system_prompt
    assert "http_request" in system_prompt
    assert "open a browser" in system_prompt


def test_runtime_agent_prompts_file_observation_before_file_changes():
    provider = FakeLLMProvider('{"actions":[],"final_answer":"ok"}')

    run_runtime_agent("update plan.md", provider=provider)

    system_prompt = provider.calls[0]["system"]
    user_prompt = provider.calls[0]["user"]
    assert "read_file" in system_prompt
    assert "list_files" in system_prompt
    assert "before changing workspace files" in system_prompt
    assert '"name": "read_file"' in user_prompt
    assert '"name": "list_files"' in user_prompt


class SequentialLLMProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, system, user):
        self.calls.append({"system": system, "user": user})
        return self.responses.pop(0)


def test_runtime_agent_can_replan_from_previous_observations():
    provider = SequentialLLMProvider(
        [
            (
                '{"actions":[{"id":"step-1","tool":"transform_text",'
                '"input":{"text":"hello","mode":"uppercase"},'
                '"reason":"normalize"}]}'
            ),
            (
                '{"actions":[{"id":"step-2","tool":"note",'
                '"input":{"text":"HELLO"},"reason":"persist"}]}'
            ),
        ]
    )

    result = run_runtime_agent("normalize then persist", provider=provider, max_iterations=2)

    assert result["status"] == "done"
    assert len(provider.calls) == 2
    assert "Previous observations" in provider.calls[1]["user"]
    assert "HELLO" in provider.calls[1]["user"]
    assert len(result["plans"]) == 2
    assert result["plan"]["actions"][0]["id"] == "step-2"
    assert result["observations"][0]["output"] == {"text": "HELLO"}
    assert result["observations"][1]["output"] == {"text": "HELLO"}
    assert result["events"][0]["iteration"] == "1"
    assert result["events"][3]["iteration"] == "2"


def test_runtime_agent_can_replan_after_tool_input_failure():
    provider = SequentialLLMProvider(
        [
            (
                '{"actions":[{"id":"step-1","tool":"transform_text",'
                '"input":{"text":" hello ","mode":"strip"},'
                '"reason":"normalize"}]}'
            ),
            (
                '{"actions":[{"id":"step-2","tool":"transform_text",'
                '"input":{"text":" hello ","mode":"trim"},'
                '"reason":"retry with valid mode"}],'
                '"final_answer":"trimmed"}'
            ),
        ]
    )

    result = run_runtime_agent("trim hello", provider=provider, max_iterations=2)

    assert result["status"] == "done"
    assert len(provider.calls) == 2
    assert "invalid_tool_input" in provider.calls[1]["user"]
    assert result["observations"][0]["status"] == "failed"
    assert result["observations"][0]["error_code"] == "invalid_tool_input"
    assert result["observations"][1]["status"] == "ok"
    assert result["observations"][1]["output"] == {"text": "hello"}
    assert result["plan"]["actions"][0]["id"] == "step-2"
    assert result["answer"] == "trimmed"


def test_runtime_agent_can_replan_after_tool_output_failure():
    provider = SequentialLLMProvider(
        [
            (
                '{"actions":[{"id":"step-1","tool":"bad_output",'
                '"input":{"text":"hello"},"reason":"produce"}]}'
            ),
            (
                '{"actions":[{"id":"step-2","tool":"note",'
                '"input":{"text":"fallback"},"reason":"recover"}],'
                '"final_answer":"recovered"}'
            ),
        ]
    )
    tools = default_runtime_tools()
    tools["bad_output"] = RuntimeToolSpec(
        name="bad_output",
        description="returns the wrong output shape",
        handler=lambda input_payload: {"unexpected": input_payload["text"]},
        input_schema={
            "type": "object",
            "required": ["text"],
            "properties": {"text": {"type": "string"}},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["text"],
            "properties": {"text": {"type": "string"}},
            "additionalProperties": False,
        },
    )

    result = run_runtime_agent(
        "recover from bad tool output",
        provider=provider,
        max_iterations=2,
        policy=RuntimePolicy(allowed_tools=set(tools)),
        tools=tools,
    )

    assert result["status"] == "done"
    assert len(provider.calls) == 2
    assert "invalid_tool_output" in provider.calls[1]["user"]
    assert result["observations"][0]["status"] == "failed"
    assert result["observations"][0]["error_code"] == "invalid_tool_output"
    assert result["observations"][1]["status"] == "ok"
    assert result["observations"][1]["output"] == {"text": "fallback"}
    assert result["answer"] == "recovered"


def test_runtime_agent_compacts_artifact_observations_in_replanning_prompt():
    large_content = "launch-secret-detail-" * 200
    provider = SequentialLLMProvider(
        [
            json.dumps(
                {
                    "actions": [
                        {
                            "id": "step-1",
                            "tool": "artifact",
                            "input": {
                                "title": "Launch report",
                                "kind": "report",
                                "content": large_content,
                                "format": "markdown",
                            },
                        },
                        {
                            "id": "step-2",
                            "tool": "transform_text",
                            "input": {"text": " hello ", "mode": "strip"},
                            "reason": "force replan",
                        },
                    ]
                }
            ),
            '{"actions":[],"final_answer":"reviewed"}',
        ]
    )

    result = run_runtime_agent("write report then recover", provider=provider, max_iterations=2)

    replan_prompt = provider.calls[1]["user"]
    assert result["status"] == "done"
    assert "Previous observations" in replan_prompt
    assert "Launch report" in replan_prompt
    assert "artifact_" in replan_prompt
    assert "launch-secret-detail" not in replan_prompt
    assert "invalid_tool_input" in replan_prompt


def test_runtime_agent_truncates_long_observation_strings_in_replanning_prompt():
    long_note = "runtime-context-detail-" * 200
    provider = SequentialLLMProvider(
        [
            json.dumps(
                {
                    "actions": [
                        {
                            "id": "step-1",
                            "tool": "note",
                            "input": {"text": long_note},
                            "reason": "capture long note",
                        },
                        {
                            "id": "step-2",
                            "tool": "transform_text",
                            "input": {"text": " hello ", "mode": "strip"},
                            "reason": "force replan",
                        },
                    ]
                }
            ),
            '{"actions":[],"final_answer":"reviewed"}',
        ]
    )

    result = run_runtime_agent(
        "capture long note then recover",
        provider=provider,
        max_iterations=2,
    )

    replan_prompt = provider.calls[1]["user"]
    assert result["status"] == "done"
    assert result["observations"][0]["output"] == {"text": long_note}
    assert "runtime-context-detail-runtime-context-detail" in replan_prompt
    assert long_note not in replan_prompt
    assert "truncated_chars" in replan_prompt
    assert "invalid_tool_input" in replan_prompt


def test_runtime_agent_can_replan_after_invalid_planner_output():
    provider = SequentialLLMProvider(
        [
            "not-json",
            (
                '{"actions":[{"id":"step-1","tool":"note",'
                '"input":{"text":"recovered"},"reason":"recover"}],'
                '"final_answer":"recovered"}'
            ),
        ]
    )

    result = run_runtime_agent("capture after bad plan", provider=provider, max_iterations=2)

    assert result["status"] == "done"
    assert len(provider.calls) == 2
    assert "invalid_plan" in provider.calls[1]["user"]
    assert result["observations"][0]["tool"] == "planner"
    assert result["observations"][0]["status"] == "failed"
    assert result["observations"][0]["error_code"] == "invalid_plan"
    assert result["observations"][1]["output"] == {"text": "recovered"}
    assert result["plans"] == [result["plan"]]
    assert result["answer"] == "recovered"


def test_runtime_agent_reports_failed_when_tool_failure_exhausts_iteration_budget():
    provider = SequentialLLMProvider(
        [
            (
                '{"actions":[{"id":"step-1","tool":"transform_text",'
                '"input":{"text":"hello","mode":"strip"},'
                '"reason":"normalize"}]}'
            )
        ]
    )

    result = run_runtime_agent("trim hello", provider=provider, max_iterations=1)

    assert result["status"] == "failed"
    assert result["error_code"] == "invalid_tool_input"
    assert "mode" in result["error"]
    assert result["observations"][0]["status"] == "failed"
    assert result["observations"][0]["error_code"] == "invalid_tool_input"


def test_runtime_agent_does_not_report_final_answer_when_action_failed():
    provider = SequentialLLMProvider(
        [
            (
                '{"actions":[{"id":"step-1","tool":"transform_text",'
                '"input":{"text":"hello","mode":"strip"},'
                '"reason":"normalize"}],'
                '"final_answer":"success even though tool will fail"}'
            )
        ]
    )

    result = run_runtime_agent("trim hello", provider=provider, max_iterations=1)

    assert result["status"] == "failed"
    assert result["error_code"] == "invalid_tool_input"
    assert "answer" not in result


def test_runtime_agent_stops_replanning_when_provider_returns_no_actions():
    provider = SequentialLLMProvider(
        [
            (
                '{"actions":[{"id":"step-1","tool":"note",'
                '"input":{"text":"hello"},"reason":"capture"}]}'
            ),
            '{"actions":[]}',
        ]
    )

    result = run_runtime_agent("capture hello", provider=provider, max_iterations=3)

    assert result["status"] == "done"
    assert len(provider.calls) == 2
    assert len(result["plans"]) == 2
    assert len(result["observations"]) == 1


def test_runtime_agent_returns_final_answer_from_converged_plan():
    provider = SequentialLLMProvider(
        [
            (
                '{"actions":[{"id":"step-1","tool":"note",'
                '"input":{"text":"hello"},"reason":"capture"}]}'
            ),
            '{"actions":[],"final_answer":"captured hello"}',
        ]
    )

    result = run_runtime_agent("capture hello", provider=provider, max_iterations=3)

    assert result["status"] == "done"
    assert result["answer"] == "captured hello"
    assert result["plan"] == {"actions": [], "final_answer": "captured hello"}


def test_runtime_agent_normalizes_model_identity_answer():
    provider = FakeLLMProvider(
        '{"actions":[],"final_answer":"我是通义千问（Qwen），由阿里云研发。"}'
    )

    result = run_runtime_agent("你是谁", provider=provider)

    assert result["status"] == "done"
    assert "self-correcting LangGraph agent runtime" in result["answer"]
    assert "OpenAI-compatible provider" in result["answer"]
    assert "Qwen" not in result["answer"]
    assert "通义千问" not in result["answer"]
    assert "阿里云研发" not in result["answer"]
    assert result["final_answer_guardrail"] == {
        "applied": "true",
        "reason": "runtime_identity_boundary",
        "original_answer_omitted": "true",
    }
    assert "我是通义千问" not in json.dumps(
        result["final_answer_guardrail"],
        ensure_ascii=False,
    )


def test_runtime_agent_normalizes_model_deployment_answer():
    provider = FakeLLMProvider(
        '{"actions":[],"final_answer":"我部署在阿里云服务器上，可通过网页或 API 访问。"}'
    )

    result = run_runtime_agent("你部署在哪", provider=provider)

    assert result["status"] == "done"
    assert "当前 CLI 或服务进程" in result["answer"]
    assert "底层 LLM provider" in result["answer"]
    assert "阿里云服务器" not in result["answer"]
    assert result["final_answer_guardrail"] == {
        "applied": "true",
        "reason": "runtime_deployment_boundary",
        "original_answer_omitted": "true",
    }


def test_runtime_agent_omits_final_answer_guardrail_when_not_applied():
    provider = FakeLLMProvider('{"actions":[],"final_answer":"captured hello"}')

    result = run_runtime_agent("capture hello", provider=provider)

    assert result["answer"] == "captured hello"
    assert "final_answer_guardrail" not in result


def test_runtime_agent_emits_redacted_progress_events():
    provider = FakeLLMProvider(
        '{"actions":[{"id":"step-1","tool":"note",'
        '"input":{"text":"secret progress body"},"reason":"capture"}],'
        '"final_answer":"done"}'
    )
    progress_events = []

    result = run_runtime_agent(
        "capture hello",
        provider=provider,
        event_sink=progress_events.append,
    )

    assert result["status"] == "done"
    assert result["progress_events"] == progress_events
    assert [event["type"] for event in progress_events] == [
        "planner_started",
        "planner_completed",
        "policy_completed",
        "tool_started",
        "tool_completed",
        "run_completed",
    ]
    assert progress_events[1]["action_count"] == "1"
    assert progress_events[3]["tool"] == "note"
    assert progress_events[-1]["status"] == "done"
    assert progress_events[-1]["duration_seconds"] == result["duration_seconds"]
    assert "secret progress body" not in json.dumps(progress_events)
