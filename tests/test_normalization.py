from self_correcting_langgraph_agent.core.normalization import normalize_goal, plan_goal


def test_plan_goal_preserves_quoted_text_and_splits_outside_quotes():
    assert plan_goal(
        " Uppercase Text in 'Agent Then Loop' then multiply 2 * 3 "
    ) == [
        "uppercase text in 'Agent Then Loop'",
        "multiply 2 * 3",
    ]


def test_normalize_goal_collapses_outer_spacing_without_touching_quotes():
    assert (
        normalize_goal("Reverse   Text in 'Agent   Loop'")
        == "reverse text in 'Agent   Loop'"
    )
