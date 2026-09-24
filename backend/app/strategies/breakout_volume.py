from typing import Any

from app.patterns import BreakoutPattern
from app.schemas.scanner import BreakoutStrategyParameters


class BreakoutVolumeStrategy:
    name = "BREAKOUT_20D_VOLUME"
    version = "1.0.0"

    def __init__(self, parameters: BreakoutStrategyParameters) -> None:
        self.parameters = parameters
        self._pattern = BreakoutPattern()

    def evaluate(self, row: dict[str, Any]) -> tuple[bool, float]:
        required = (
            "close", "PREVIOUS_HIGH_20D", "RELATIVE_VOLUME", "SMA_50",
            "SMA_200", "AVG_DOLLAR_VOLUME_20D",
        )
        if any(row.get(key) is None for key in required):
            return False, 0.0
        pattern = self._pattern.detect(
            close=float(row["close"]), previous_high=float(row["PREVIOUS_HIGH_20D"])
        )
        accepted = all(
            (
                pattern.detected,
                float(row["RELATIVE_VOLUME"]) >= self.parameters.min_relative_volume,
                float(row["close"]) > float(row["SMA_50"]),
                float(row["SMA_50"]) > float(row["SMA_200"]),
                float(row["AVG_DOLLAR_VOLUME_20D"]) >= self.parameters.min_avg_dollar_volume,
                float(row["close"]) >= self.parameters.min_price,
            )
        )
        return accepted, pattern.breakout_pct
