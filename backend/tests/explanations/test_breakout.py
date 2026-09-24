from app.explanations import explain_breakout


def test_breakout_explanation_is_deterministic_and_auditable() -> None:
    arguments = dict(
        ticker="ABC", price=105.0, previous_high=100.0, breakout_pct=5.0,
        current_volume=2_000_000, average_volume=1_000_000,
        relative_volume=2.0, sma_50=90.0, sma_200=80.0,
        average_dollar_volume=50_000_000, score=55.0,
        score_components={"volume": 25.0, "breakout": 30.0},
        min_relative_volume=1.5, min_average_dollar_volume=10_000_000,
    )
    first = explain_breakout(**arguments)
    second = explain_breakout(**arguments)
    assert first == second
    assert first.breakout.breakout_pct == 5.0
    assert first.breakout.condition_passed
    assert first.volume.relative_volume == 2.0
    assert first.trend.above_sma_50 and first.trend.sma_50_above_sma_200
    assert sum(first.score_explanation.values()) == 55.0
