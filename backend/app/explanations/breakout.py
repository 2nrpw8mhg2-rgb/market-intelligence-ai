from app.schemas.scanner import (
    BreakoutEvidence, LiquidityEvidence, OpportunityExplanation,
    TrendEvidence, VolumeEvidence,
)


def explain_breakout(*, ticker: str, price: float, previous_high: float,
                     breakout_pct: float, current_volume: float, average_volume: float,
                     relative_volume: float, sma_50: float, sma_200: float,
                     average_dollar_volume: float, score: float,
                     score_components: dict[str, float], min_relative_volume: float,
                     min_average_dollar_volume: float) -> OpportunityExplanation:
    """Build a deterministic, reproducible explanation from persisted inputs."""
    rounded_components = dict(score_components)
    if abs(sum(rounded_components.values()) - score) > 0.0001:
        raise ValueError("score components do not sum to the final score")
    return OpportunityExplanation(
        summary=(f"{ticker} fechou {breakout_pct:.2f}% acima do máximo das 20 sessões "
                 f"anteriores. O volume foi {relative_volume:.2f} vezes a média anterior; "
                 "o preço ficou acima da SMA50 e a SMA50 acima da SMA200."),
        breakout=BreakoutEvidence(
            previous_high=previous_high, current_close=price,
            breakout_pct=breakout_pct, condition_passed=price > previous_high,
        ),
        volume=VolumeEvidence(
            relative_volume=relative_volume, average_volume_20d=average_volume,
            current_volume=current_volume, minimum_relative_volume=min_relative_volume,
            condition_passed=relative_volume >= min_relative_volume,
        ),
        trend=TrendEvidence(
            close=price, sma_50=sma_50, sma_200=sma_200,
            above_sma_50=price > sma_50, sma_50_above_sma_200=sma_50 > sma_200,
        ),
        liquidity=LiquidityEvidence(
            avg_dollar_volume_20d=average_dollar_volume,
            minimum_required=min_average_dollar_volume,
            condition_passed=average_dollar_volume >= min_average_dollar_volume,
        ),
        score_explanation=rounded_components,
    )
