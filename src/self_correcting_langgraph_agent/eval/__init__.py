from __future__ import annotations

__all__ = ["evaluate_agent", "registered_evaluation_cases"]


def __getattr__(name: str):
    if name in __all__:
        from self_correcting_langgraph_agent.eval import evaluator

        return getattr(evaluator, name)
    raise AttributeError(name)
