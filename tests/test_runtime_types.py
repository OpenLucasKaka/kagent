import json

import pytest

from self_correcting_langgraph_agent.runtime.types import (
    MAX_ACTION_REASON_CHARS,
    MAX_PLAN_ACTIONS,
    MAX_PLAN_FINAL_ANSWER_CHARS,
    parse_agent_plan,
)


def test_parse_agent_plan_accepts_strict_action_json():
    plan = parse_agent_plan(
        '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"},"reason":"capture"}]}'
    )

    assert plan.actions[0].id == "step-1"
    assert plan.actions[0].tool == "note"
    assert plan.actions[0].input == {"text": "hello"}
    assert plan.actions[0].reason == "capture"


def test_parse_agent_plan_accepts_action_dependencies_on_prior_actions():
    plan = parse_agent_plan(
        '{"actions":['
        '{"id":"step-1","tool":"note","input":{"text":"hello"}},'
        '{"id":"step-2","tool":"artifact","input":{"title":"Report","kind":"report",'
        '"content":"ready"},"depends_on":["step-1"]}'
        "]}"
    )

    assert plan.actions[1].depends_on == ["step-1"]
    assert plan.to_dict()["actions"][1]["depends_on"] == ["step-1"]


def test_parse_agent_plan_accepts_optional_final_answer():
    plan = parse_agent_plan('{"actions":[],"final_answer":"finished"}')

    assert plan.actions == []
    assert plan.final_answer == "finished"
    assert plan.to_dict() == {"actions": [], "final_answer": "finished"}


def test_parse_agent_plan_extracts_json_object_from_model_preface():
    plan = parse_agent_plan(
        """The user wants a note.
</think>

{
  "actions": [
    {
      "id": "step-1",
      "tool": "note",
      "input": {"text": "hello-real-llm"},
      "reason": "Record the requested text."
    }
  ],
  "final_answer": "done"
}
"""
    )

    assert plan.actions[0].id == "step-1"
    assert plan.actions[0].input == {"text": "hello-real-llm"}
    assert plan.final_answer == "done"


def test_parse_agent_plan_uses_last_plan_object_after_observation_json():
    plan = parse_agent_plan(
        """Previous observation:
{"action_id":"step-1","output":{"text":"service-real-llm"},"status":"ok","tool":"note"}

Final plan:
{"actions":[],"final_answer":"service-done"}
"""
    )

    assert plan.actions == []
    assert plan.final_answer == "service-done"


def test_parse_agent_plan_uses_last_plan_object_after_example_plan():
    plan = parse_agent_plan(
        """I could return an example like:
{"actions":[{"id":"example","tool":"note","input":{"text":"example"}}]}

But the final answer is:
{"actions":[],"final_answer":"service-done"}
"""
    )

    assert plan.actions == []
    assert plan.final_answer == "service-done"


def test_parse_agent_plan_rejects_unknown_top_level_field():
    with pytest.raises(ValueError, match="plan field is not allowed: extra"):
        parse_agent_plan('{"actions":[],"extra":"ignored"}')


def test_parse_agent_plan_rejects_non_string_final_answer():
    with pytest.raises(ValueError, match="final_answer must be a string"):
        parse_agent_plan('{"actions":[],"final_answer":123}')


def test_parse_agent_plan_rejects_too_long_final_answer():
    payload = {"actions": [], "final_answer": "x" * (MAX_PLAN_FINAL_ANSWER_CHARS + 1)}

    with pytest.raises(
        ValueError,
        match=f"final_answer must contain at most {MAX_PLAN_FINAL_ANSWER_CHARS}",
    ):
        parse_agent_plan(json.dumps(payload))


def test_parse_agent_plan_rejects_missing_action_tool():
    with pytest.raises(ValueError, match="action tool is required"):
        parse_agent_plan('{"actions":[{"id":"step-1","input":{}}]}')


def test_parse_agent_plan_rejects_action_id_with_surrounding_whitespace():
    with pytest.raises(ValueError, match="action id must not contain surrounding whitespace"):
        parse_agent_plan('{"actions":[{"id":" step-1 ","tool":"note","input":{}}]}')


def test_parse_agent_plan_rejects_tool_name_with_surrounding_whitespace():
    with pytest.raises(ValueError, match="action tool must not contain surrounding whitespace"):
        parse_agent_plan('{"actions":[{"id":"step-1","tool":" note ","input":{}}]}')


def test_parse_agent_plan_rejects_duplicate_action_ids():
    with pytest.raises(ValueError, match="duplicate action id"):
        parse_agent_plan(
            '{"actions":['
            '{"id":"step-1","tool":"note","input":{"text":"one"}},'
            '{"id":"step-1","tool":"note","input":{"text":"two"}}'
            "]}"
        )


def test_parse_agent_plan_rejects_non_object_action_input():
    with pytest.raises(ValueError, match="action input must be an object"):
        parse_agent_plan('{"actions":[{"id":"step-1","tool":"note","input":"hello"}]}')


def test_parse_agent_plan_rejects_unknown_action_field():
    with pytest.raises(ValueError, match="action field is not allowed: extra"):
        parse_agent_plan(
            '{"actions":[{"id":"step-1","tool":"note","input":{},"extra":"ignored"}]}'
        )


def test_parse_agent_plan_rejects_non_string_action_dependency():
    payload = {
        "actions": [
            {"id": "step-1", "tool": "note", "input": {"text": "hello"}},
            {
                "id": "step-2",
                "tool": "note",
                "input": {"text": "done"},
                "depends_on": [123],
            },
        ]
    }

    with pytest.raises(ValueError, match="action dependency must be a string"):
        parse_agent_plan(json.dumps(payload))


def test_parse_agent_plan_rejects_dependency_on_unknown_or_later_action():
    payload = {
        "actions": [
            {
                "id": "step-1",
                "tool": "note",
                "input": {"text": "hello"},
                "depends_on": ["step-2"],
            },
            {"id": "step-2", "tool": "note", "input": {"text": "done"}},
        ]
    }

    with pytest.raises(ValueError, match="unknown or later action dependency"):
        parse_agent_plan(json.dumps(payload))


def test_parse_agent_plan_rejects_action_dependency_on_self():
    payload = {
        "actions": [
            {
                "id": "step-1",
                "tool": "note",
                "input": {"text": "hello"},
                "depends_on": ["step-1"],
            }
        ]
    }

    with pytest.raises(ValueError, match="unknown or later action dependency"):
        parse_agent_plan(json.dumps(payload))


def test_parse_agent_plan_rejects_too_long_action_reason():
    payload = {
        "actions": [
            {
                "id": "step-1",
                "tool": "note",
                "input": {"text": "hello"},
                "reason": "x" * (MAX_ACTION_REASON_CHARS + 1),
            }
        ]
    }

    with pytest.raises(
        ValueError,
        match=f"action reason must contain at most {MAX_ACTION_REASON_CHARS}",
    ):
        parse_agent_plan(json.dumps(payload))


def test_parse_agent_plan_rejects_too_many_actions():
    payload = {
        "actions": [
            {"id": f"step-{index}", "tool": "note", "input": {"text": "hello"}}
            for index in range(1, MAX_PLAN_ACTIONS + 2)
        ]
    }

    with pytest.raises(ValueError, match=f"plan actions must contain at most {MAX_PLAN_ACTIONS}"):
        parse_agent_plan(json.dumps(payload))
