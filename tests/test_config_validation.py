import pytest

from self_correcting_langgraph_agent.utils.config_validation import optional_json_int


def test_optional_json_int_uses_default_for_missing_or_empty_values():
    assert optional_json_int({}, "max_steps", 6) == 6
    assert optional_json_int({"max_steps": ""}, "max_steps", 6) == 6


def test_optional_json_int_accepts_json_integer_values():
    assert optional_json_int({"max_steps": 3}, "max_steps", 6) == 3


def test_optional_json_int_rejects_non_integer_json_values():
    for value in [True, False, 2.5, "2"]:
        with pytest.raises(ValueError, match="max_steps must be an integer"):
            optional_json_int({"max_steps": value}, "max_steps", 6)
