from datetime import UTC, date, datetime, timedelta
import uuid

from app.pit.readiness import assess_alias_readiness, merge_provider_bars
from app.schemas.market_data import MarketBar
from app.schemas.universe import MembershipImportRecord


def membership():
    return MembershipImportRecord(
        security_id=uuid.UUID(int=1), ticker="ABC", valid_from=date(2024, 1, 2),
        valid_to=None, source="fixture", source_confidence="HIGH",
        provenance={"source": "fixture"},
    )


def bars(count=220):
    start = datetime(2023, 1, 1, tzinfo=UTC)
    return [MarketBar(ticker="ABC", timestamp=start + timedelta(days=index),
                      open=10, high=11, low=9, close=10, volume=1_000_000)
            for index in range(count)]


def test_missing_prices_fail_closed() -> None:
    result = assess_alias_readiness(membership(), [], [date(2024, 1, 2)])
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "NO_PRICE_SERIES"


def test_causal_feature_dry_run_does_not_calculate_returns() -> None:
    session = bars()[-1].timestamp.date()
    item = membership().model_copy(update={"valid_from": session})
    result = assess_alias_readiness(item, bars(), [session])
    assert result["status"] == "READY"
    assert result["evaluable_sessions"] == 1
    assert "return" not in result


def test_proven_halt_is_natural_lifecycle_not_material_gap() -> None:
    session = bars()[-1].timestamp.date()
    halted = session + timedelta(days=1)
    item = membership().model_copy(update={"valid_from": session})
    result = assess_alias_readiness(
        item, bars(), [session, halted], natural_unavailable_sessions={halted}
    )
    assert result["missing_membership_sessions"] == 0
    assert result["natural_lifecycle_sessions"] == 1
    assert result["status"] == "READY_WITH_DOCUMENTED_LIMITATION"


def test_supplemental_provider_only_fills_missing_dates() -> None:
    primary = bars(2)
    replacement = primary[0].model_copy(update={"close": 99})
    extra = primary[-1].model_copy(update={"timestamp": primary[-1].timestamp + timedelta(days=1)})
    merged = merge_provider_bars(primary, [replacement, extra])
    assert len(merged) == 3
    assert merged[0].close == primary[0].close
    assert merged[-1].timestamp == extra.timestamp
