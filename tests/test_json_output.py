import json
from enum import Enum

from self_correcting_langgraph_agent.utils.json_output import format_and_write_json, json_ready


class ExampleStatus(Enum):
    DONE = "done"


def test_format_and_write_json_returns_pretty_payload_without_file():
    payload = format_and_write_json({"status": "done"}, "")

    assert json.loads(payload) == {"status": "done"}
    assert payload.endswith("}")


def test_format_and_write_json_preserves_readable_unicode_text():
    payload = format_and_write_json({"answer": "内部工具试运行计划"}, "")

    assert "\\u" not in payload
    assert "内部工具试运行计划" in payload
    assert json.loads(payload) == {"answer": "内部工具试运行计划"}


def test_format_and_write_json_writes_matching_payload_to_file(tmp_path):
    output_path = tmp_path / "payload.json"

    payload = format_and_write_json({"status": "done", "answer": "完成"}, str(output_path))

    assert json.loads(output_path.read_text()) == json.loads(payload)
    assert "完成" in output_path.read_text(encoding="utf-8")


def test_json_ready_converts_nested_enums_to_json_values():
    payload = json_ready({"status": ExampleStatus.DONE, "items": [ExampleStatus.DONE]})

    assert payload == {"status": "done", "items": ["done"]}
