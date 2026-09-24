from app.ranking import BreakoutRanker
from app.schemas.scanner import BreakoutStrategyParameters


def test_score_is_bounded_and_components_sum() -> None:
    result = BreakoutRanker().score(
        breakout_pct=99, relative_volume=999, momentum_20d=99, close=999,
        sma_50=1, avg_dollar_volume=10**15,
        parameters=BreakoutStrategyParameters(),
    )
    assert result.score == 100
    assert sum(result.components.values()) == result.score
    assert set(result.components) == {"breakout", "relative_volume", "momentum", "trend", "liquidity"}


def test_score_is_deterministic() -> None:
    kwargs = dict(
        breakout_pct=.03, relative_volume=2, momentum_20d=.1, close=110,
        sma_50=100, avg_dollar_volume=30_000_000,
        parameters=BreakoutStrategyParameters(),
    )
    assert BreakoutRanker().score(**kwargs) == BreakoutRanker().score(**kwargs)
