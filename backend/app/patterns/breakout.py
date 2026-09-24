from dataclasses import dataclass


@dataclass(frozen=True)
class BreakoutPatternResult:
    detected: bool
    breakout_pct: float


class BreakoutPattern:
    name = "BREAKOUT_20D_VOLUME"

    def detect(self, *, close: float, previous_high: float) -> BreakoutPatternResult:
        strength = close / previous_high - 1 if previous_high > 0 else 0.0
        return BreakoutPatternResult(detected=close > previous_high, breakout_pct=strength)
