from self_correcting_langgraph_agent.core.tools import (
    execute_step,
    expected_answer,
    matching_tool_name,
    registered_tool_metadata,
    registered_tool_names,
)


def test_execute_step_returns_structured_tool_result():
    assert execute_step("uppercase text in 'agent loop'") == {
        "tool": "uppercase_text",
        "input": "agent loop",
        "output": "AGENT LOOP",
    }


def test_uppercase_text_supports_empty_text():
    assert execute_step("uppercase text in ''") == {
        "tool": "uppercase_text",
        "input": "",
        "output": "",
    }


def test_execute_step_supports_multiplication():
    assert execute_step("multiply 6 * 7") == {
        "tool": "multiply_numbers",
        "input": "multiply 6 * 7",
        "output": "42",
    }


def test_execute_step_supports_subtraction():
    assert execute_step("subtract 10 - 4") == {
        "tool": "subtract_numbers",
        "input": "subtract 10 - 4",
        "output": "6",
    }


def test_count_words_supports_empty_text():
    assert execute_step("count words in ''") == {
        "tool": "count_words",
        "input": "",
        "output": "0",
    }


def test_execute_step_supports_reversing_text_with_original_case():
    assert execute_step("reverse text in 'Agent Loop'") == {
        "tool": "reverse_text",
        "input": "Agent Loop",
        "output": "pooL tnegA",
    }


def test_execute_step_supports_lowercase_text_with_original_input():
    assert execute_step("lowercase text in 'Agent Loop'") == {
        "tool": "lowercase_text",
        "input": "Agent Loop",
        "output": "agent loop",
    }


def test_execute_step_supports_trimming_text_with_original_input():
    assert execute_step("trim text in '  Agent Loop  '") == {
        "tool": "trim_text",
        "input": "  Agent Loop  ",
        "output": "Agent Loop",
    }


def test_expected_answer_returns_none_for_unknown_steps():
    assert expected_answer("search the web") is None
    assert matching_tool_name("search the web") is None


def test_matching_tool_name_returns_registry_entry():
    assert matching_tool_name("count words in 'hello world'") == "count_words"
    assert matching_tool_name("multiply 6 * 7") == "multiply_numbers"


def test_registered_tool_names_are_stable_and_discoverable():
    assert registered_tool_names() == [
        "calculate_sum",
        "count_words",
        "lowercase_text",
        "multiply_numbers",
        "reverse_text",
        "subtract_numbers",
        "trim_text",
        "uppercase_text",
    ]


def test_registered_tool_metadata_is_stable_and_automation_friendly():
    metadata = registered_tool_metadata()

    assert metadata[0] == {
        "name": "calculate_sum",
        "command": "calculate N + M",
        "description": "Add two integers.",
        "example": "calculate 2 + 3",
    }
    assert metadata[-1] == {
        "name": "uppercase_text",
        "command": "uppercase text in 'text'",
        "description": "Convert quoted text to uppercase.",
        "example": "uppercase text in 'agent loop'",
    }
