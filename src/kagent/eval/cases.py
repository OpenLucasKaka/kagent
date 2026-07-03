from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List

CaseCheck = Callable[[Dict[str, Any]], bool]


@dataclass(frozen=True)
class EvaluationCase:
    name: str
    category: str
    run: Callable[[], Dict[str, Any]]
    check: CaseCheck


def build_evaluation_cases(AgentConfig, AgentStatus, run_agent) -> List[EvaluationCase]:
    return [
        EvaluationCase(
            "multi_step_success",
            "workflow",
            lambda: run_agent(
                "calculate 2 + 3 then count words in 'ship small reliable agents'",
                config=AgentConfig(max_steps=4, max_retries=1),
            ),
            lambda result: (
                result["status"] == AgentStatus.DONE
                and result["step_results"] == ["5", "4"]
                and result["retry_count"] == 0
                and [item["passed"] for item in result["verification_results"]]
                == ["true", "true"]
                and [item["tool"] for item in result["plan_validations"]]
                == ["calculate_sum", "count_words"]
            ),
        ),
        EvaluationCase(
            "self_correction_success",
            "recovery",
            lambda: run_agent(
                "calculate 2 + 3",
                config=AgentConfig(max_steps=3, max_retries=2),
                fault_plan={"calculate 2 + 3": ["wrong-answer"]},
            ),
            lambda result: (
                result["status"] == AgentStatus.DONE
                and result["answer"] == "5"
                and result["retry_count"] == 1
                and result["reflections"][-1]["actual"] == "6"
                and result["reflections"][-1]["expected"] == "5"
                and [item["passed"] for item in result["verification_results"]]
                == ["false", "true"]
            ),
        ),
        EvaluationCase(
            "retry_budget_failure",
            "failure",
            lambda: run_agent(
                "calculate 2 + 3",
                config=AgentConfig(max_steps=3, max_retries=1),
                fault_plan={"calculate 2 + 3": ["wrong-answer", "wrong-answer"]},
            ),
            lambda result: (
                result["status"] == AgentStatus.FAILED
                and result["errors"][-1] == "retry budget exhausted"
            ),
        ),
        EvaluationCase(
            "uppercase_tool_success",
            "tool",
            lambda: run_agent(
                "uppercase text in 'agent loop'",
                config=AgentConfig(max_steps=3, max_retries=1),
            ),
            lambda result: (
                result["status"] == AgentStatus.DONE
                and result["answer"] == "AGENT LOOP"
                and result["tool_calls"][-1]["tool"] == "uppercase_text"
            ),
        ),
        EvaluationCase(
            "unsupported_plan_failure",
            "failure",
            lambda: run_agent(
                "calculate 1 + 1 then search the web",
                config=AgentConfig(max_steps=4, max_retries=2),
            ),
            lambda result: (
                result["status"] == AgentStatus.FAILED
                and result["errors"] == ["unsupported planned step: search the web"]
                and result["retry_count"] == 0
                and [event["node"] for event in result["events"]] == ["planner"]
                and result["plan_validations"][-1]["supported"] == "false"
            ),
        ),
        EvaluationCase(
            "empty_answer_recovery",
            "recovery",
            lambda: run_agent(
                "uppercase text in 'agent loop'",
                config=AgentConfig(max_steps=4, max_retries=2),
                fault_plan={"uppercase text in 'agent loop'": ["empty-answer"]},
            ),
            lambda result: (
                result["status"] == AgentStatus.DONE
                and result["answer"] == "AGENT LOOP"
                and result["reflections"][-1]["actual"] == ""
                and result["reflections"][-1]["reason"] == "answer was empty"
                and [item["passed"] for item in result["verification_results"]]
                == ["false", "true"]
                and [item["fault"] for item in result["execution_attempts"]]
                == ["empty-answer", ""]
                and result["execution_attempts"][-1]["tool"] == "uppercase_text"
            ),
        ),
        EvaluationCase(
            "per_step_retry_budget_success",
            "recovery",
            lambda: run_agent(
                "calculate 2 + 3 then uppercase text in 'agent loop'",
                config=AgentConfig(max_steps=4, max_retries=1),
                fault_plan={
                    "calculate 2 + 3": ["wrong-answer"],
                    "uppercase text in 'agent loop'": ["empty-answer"],
                },
            ),
            lambda result: (
                result["status"] == AgentStatus.DONE
                and result["retry_count"] == 2
                and result["step_retry_count"] == 0
                and result["step_results"] == ["5", "AGENT LOOP"]
                and [item["retry"] for item in result["verification_results"]]
                == ["0", "1", "0", "1"]
            ),
        ),
        EvaluationCase(
            "multiplication_tool_success",
            "tool",
            lambda: run_agent(
                "multiply 6 * 7",
                config=AgentConfig(max_steps=3, max_retries=1),
            ),
            lambda result: (
                result["status"] == AgentStatus.DONE
                and result["answer"] == "42"
                and result["tool_calls"][-1]["tool"] == "multiply_numbers"
            ),
        ),
        EvaluationCase(
            "reverse_text_tool_success",
            "tool",
            lambda: run_agent(
                "Reverse Text in 'Agent Loop'",
                config=AgentConfig(max_steps=3, max_retries=1),
            ),
            lambda result: (
                result["status"] == AgentStatus.DONE
                and result["answer"] == "pooL tnegA"
                and result["tool_calls"][-1]["tool"] == "reverse_text"
            ),
        ),
        EvaluationCase(
            "lowercase_text_tool_success",
            "tool",
            lambda: run_agent(
                "Lowercase Text in 'Agent Loop'",
                config=AgentConfig(max_steps=3, max_retries=1),
            ),
            lambda result: (
                result["status"] == AgentStatus.DONE
                and result["answer"] == "agent loop"
                and result["tool_calls"][-1]["tool"] == "lowercase_text"
            ),
        ),
        EvaluationCase(
            "trim_text_tool_success",
            "tool",
            lambda: run_agent(
                "Trim Text in '  Agent Loop  '",
                config=AgentConfig(max_steps=3, max_retries=1),
            ),
            lambda result: (
                result["status"] == AgentStatus.DONE
                and result["answer"] == "Agent Loop"
                and result["tool_calls"][-1]["tool"] == "trim_text"
            ),
        ),
        EvaluationCase(
            "subtraction_tool_success",
            "tool",
            lambda: run_agent(
                "subtract 10 - 4",
                config=AgentConfig(max_steps=3, max_retries=1),
            ),
            lambda result: (
                result["status"] == AgentStatus.DONE
                and result["answer"] == "6"
                and result["tool_calls"][-1]["tool"] == "subtract_numbers"
            ),
        ),
        EvaluationCase(
            "tool_error_recovery",
            "recovery",
            lambda: run_agent(
                "reverse text in 'Agent Loop'",
                config=AgentConfig(max_steps=4, max_retries=2),
                fault_plan={"reverse text in 'Agent Loop'": ["tool-error"]},
            ),
            lambda result: (
                result["status"] == AgentStatus.DONE
                and result["answer"] == "pooL tnegA"
                and result["reflections"][-1]["reason"] == "tool execution failed"
                and [item["fault"] for item in result["execution_attempts"]]
                == ["tool-error", ""]
            ),
        ),
        EvaluationCase(
            "empty_plan_failure",
            "failure",
            lambda: run_agent(
                "   ",
                config=AgentConfig(max_steps=3, max_retries=1),
            ),
            lambda result: (
                result["status"] == AgentStatus.FAILED
                and result["errors"] == ["empty plan"]
                and [event["node"] for event in result["events"]] == ["planner"]
            ),
        ),
    ]
