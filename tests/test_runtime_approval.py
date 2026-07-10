from kagent.runtime.approval import build_resumable_plan


def test_build_resumable_plan_keeps_remaining_actions_and_rewrites_dependencies():
    pending_action = {
        "id": "step-2",
        "tool": "http_request",
        "input": {"url": "https://example.com"},
        "reason": "fetch after approval",
        "depends_on": ["step-1"],
    }
    plan = {
        "actions": [
            {
                "id": "step-1",
                "tool": "note",
                "input": {"text": "recorded"},
                "reason": "record context",
            },
            pending_action,
            {
                "id": "step-3",
                "tool": "note",
                "input": {"text": "finished"},
                "reason": "record completion",
                "depends_on": ["step-1", "step-2"],
            },
        ],
        "final_answer": "done",
    }

    resumable = build_resumable_plan(plan, pending_action)

    assert resumable == {
        "actions": [
            {
                "id": "step-2",
                "tool": "http_request",
                "input": {"url": "https://example.com"},
                "reason": "fetch after approval",
            },
            {
                "id": "step-3",
                "tool": "note",
                "input": {"text": "finished"},
                "reason": "record completion",
                "depends_on": ["step-2"],
            },
        ],
        "final_answer": "done",
    }


def test_build_resumable_plan_rejects_pending_action_that_differs_from_plan():
    plan = {
        "actions": [
            {
                "id": "step-1",
                "tool": "open_url",
                "input": {"url": "https://example.com"},
                "reason": "open reviewed URL",
            }
        ]
    }
    pending_action = {
        "id": "step-1",
        "tool": "open_url",
        "input": {"url": "https://attacker.example"},
        "reason": "open substituted URL",
    }

    assert build_resumable_plan(plan, pending_action) is None


def test_build_resumable_plan_rejects_invalid_original_dependencies():
    pending_action = {
        "id": "step-1",
        "tool": "note",
        "input": {"text": "first"},
        "reason": "record",
        "depends_on": ["step-2"],
    }
    plan = {
        "actions": [
            pending_action,
            {
                "id": "step-2",
                "tool": "note",
                "input": {"text": "second"},
                "reason": "record",
            },
        ]
    }

    assert build_resumable_plan(plan, pending_action) is None
