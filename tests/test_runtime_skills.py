from __future__ import annotations

import json

import pytest

from kagent.runtime.skills import RuntimeSkillRegistry
from kagent.runtime.tools import default_runtime_tools, execute_runtime_tool


def test_runtime_skill_registry_lists_and_reads_json_skills(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "research.json").write_text(
        json.dumps(
            {
                "name": "research",
                "description": "Research a business topic",
                "instructions": "Collect facts, compare options, cite assumptions.",
                "tags": ["analysis", "business"],
            }
        ),
        encoding="utf-8",
    )

    registry = RuntimeSkillRegistry(skills_dir)

    assert registry.list_skills() == [
        {
            "name": "research",
            "description": "Research a business topic",
            "tags": ["analysis", "business"],
        }
    ]
    assert registry.get_skill("research") == {
        "name": "research",
        "description": "Research a business topic",
        "instructions": "Collect facts, compare options, cite assumptions.",
        "tags": ["analysis", "business"],
    }


def test_runtime_skill_registry_rejects_unsafe_skill_name(tmp_path):
    registry = RuntimeSkillRegistry(tmp_path)

    with pytest.raises(ValueError, match="skill name must be a safe identifier"):
        registry.get_skill("../secret")


def test_runtime_skill_tools_use_configured_skill_directory(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "briefing.json").write_text(
        json.dumps(
            {
                "name": "briefing",
                "description": "Create concise internal briefings",
                "instructions": "Summarize context, risks, and next actions.",
            }
        ),
        encoding="utf-8",
    )

    tools = default_runtime_tools(runtime_skills_dir=str(skills_dir))
    listed = execute_runtime_tool(tools, "skill_list", {}, action_id="step-1")
    fetched = execute_runtime_tool(
        tools,
        "skill_get",
        {"name": "briefing"},
        action_id="step-2",
    )

    assert listed.status == "ok"
    assert listed.output["skills"][0]["name"] == "briefing"
    assert fetched.status == "ok"
    assert fetched.output["instructions"] == "Summarize context, risks, and next actions."
