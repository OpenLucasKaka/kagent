import json

from kagent.providers.llm import FakeLLMProvider
from kagent.runtime import derive_runtime_steps, run_runtime_agent


class SequentialLLMProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, _system, _user):
        return self.responses.pop(0)


def test_runtime_steps_project_successful_actions_without_internal_tool_names():
    provider = FakeLLMProvider(
        json.dumps(
            {
                "actions": [
                    {
                        "id": "step-1",
                        "tool": "note",
                        "input": {"text": "hello"},
                        "reason": "Record context",
                    },
                    {
                        "id": "step-2",
                        "tool": "artifact",
                        "input": {
                            "title": "Rollout plan",
                            "kind": "plan",
                            "content": "ship it",
                        },
                        "reason": "Create rollout artifact",
                    },
                ]
            }
        )
    )

    result = run_runtime_agent("create rollout artifact", provider=provider)

    assert result["steps"] == [
        {"index": "1", "state": "done", "title": "Created Rollout plan"},
    ]
    serialized_steps = json.dumps(result["steps"], ensure_ascii=False)
    assert "artifact" not in serialized_steps.lower()
    assert "step-1" not in serialized_steps
    assert "step-2" not in serialized_steps


def test_runtime_steps_hide_internal_note_actions():
    provider = FakeLLMProvider(
        json.dumps(
            {
                "actions": [
                    {
                        "id": "step-1",
                        "tool": "note",
                        "input": {"text": "internal context"},
                        "reason": "Capture internal context",
                    }
                ]
            }
        )
    )

    result = run_runtime_agent("capture internal context", provider=provider)

    assert result["status"] == "done"
    assert result["steps"] == []


def test_runtime_steps_keep_completed_actions_when_final_plan_has_no_actions():
    provider = SequentialLLMProvider(
        [
            json.dumps(
                {
                    "actions": [
                        {
                            "id": "step-1",
                            "tool": "transform_text",
                            "input": {"text": "ready", "mode": "uppercase"},
                            "reason": "Normalize readiness",
                        }
                    ]
                }
            ),
            json.dumps({"actions": [], "final_answer": "Done."}),
        ]
    )

    result = run_runtime_agent("record then answer", provider=provider, max_iterations=2)

    assert result["status"] == "done"
    assert result["answer"] == "Done."
    assert result["plan"] == {"actions": [], "final_answer": "Done."}
    assert result["steps"] == [
        {
            "index": "1",
            "state": "done",
            "title": "Normalize readiness",
        }
    ]


def test_runtime_steps_use_latest_action_when_replan_reuses_action_id():
    provider = SequentialLLMProvider(
        [
            json.dumps(
                {
                    "actions": [
                        {
                            "id": "step-1",
                            "tool": "transform_text",
                            "input": {"text": "hello", "mode": "strip"},
                            "reason": "Normalize text",
                        }
                    ]
                }
            ),
            json.dumps(
                {
                    "actions": [
                        {
                            "id": "step-1",
                            "tool": "transform_text",
                            "input": {"text": "fallback", "mode": "uppercase"},
                            "reason": "Record fallback",
                        }
                    ]
                }
            ),
            json.dumps({"actions": [], "final_answer": "Recovered."}),
        ]
    )

    result = run_runtime_agent(
        "recover from reused action id",
        provider=provider,
        max_iterations=3,
    )

    assert result["status"] == "done"
    assert result["answer"] == "Recovered."
    assert result["steps"] == [
        {
            "index": "1",
            "state": "done",
            "title": "Record fallback",
        }
    ]


def test_runtime_steps_project_pending_approval_from_runtime_payload():
    provider = FakeLLMProvider(
        json.dumps(
            {
                "actions": [
                    {
                        "id": "open-github",
                        "tool": "open_url",
                        "input": {"url": "https://github.com"},
                        "reason": "Open GitHub for the user",
                    }
                ]
            }
        )
    )

    result = run_runtime_agent("open github", provider=provider)

    assert result["status"] == "requires_approval"
    assert result["steps"] == [
        {
            "index": "1",
            "state": "waiting_approval",
            "title": "Open https://github.com",
            "detail": "Open GitHub for the user",
        }
    ]


def test_runtime_steps_project_planner_failure_when_no_actions_exist():
    result = run_runtime_agent(
        "bad plan",
        provider=FakeLLMProvider("not json"),
        max_iterations=1,
    )

    assert result["status"] == "failed"
    assert result["steps"][0]["state"] == "failed"
    assert result["steps"][0]["title"] == "Plan request"
    assert "plan JSON is invalid" in result["steps"][0]["detail"]


def test_runtime_steps_redact_secret_like_step_text():
    payload = {
        "plan": {
            "actions": [
                {
                    "id": "step-1",
                    "tool": "http_request",
                    "input": {
                        "url": "https://example.com/data?api_key=sk-runtime-secret-token"
                    },
                    "reason": "Fetch bearer secret-token-value",
                }
            ]
        },
        "observations": [
            {
                "action_id": "step-1",
                "tool": "http_request",
                "status": "requires_approval",
                "output": {},
            }
        ],
        "pending_approval": {"id": "step-1"},
    }

    steps = derive_runtime_steps(payload)

    serialized = json.dumps(steps, ensure_ascii=False)
    assert "sk-runtime-secret-token" not in serialized
    assert "https://example.com/data?api_key=[REDACTED]" in serialized
