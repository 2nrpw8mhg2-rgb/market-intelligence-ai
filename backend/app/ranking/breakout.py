import math

from app.schemas.scanner import BreakoutStrategyParameters, ScoreResult


class BreakoutRanker:
    def score(
        self,
        *,
        breakout_pct: float,
        relative_volume: float,
        momentum_20d: float,
        close: float,
        sma_50: float,
        avg_dollar_volume: float,
        parameters: BreakoutStrategyParameters,
    ) -> ScoreResult:
        components = {
            "breakout": 30 * self._clip(breakout_pct / 0.10),
            "relative_volume": 25 * self._clip(
                (relative_volume - parameters.min_relative_volume) / 2.5
            ),
            "momentum": 20 * self._clip(momentum_20d / 0.30),
            "trend": 15 * self._clip((close / sma_50 - 1) / 0.20),
            "liquidity": 10 * self._clip(
                math.log10(max(avg_dollar_volume / parameters.min_avg_dollar_volume, 1.0))
            ),
        }
        rounded = {key: round(value, 4) for key, value in components.items()}
        return ScoreResult(score=round(min(100.0, sum(rounded.values())), 4), components=rounded)

    @staticmethod
    def _clip(value: float) -> float:
        return min(1.0, max(0.0, value))
