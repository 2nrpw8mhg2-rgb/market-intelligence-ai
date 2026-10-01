from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from app.features import FeatureEngine
from app.pit.alias_chain import build_linear_alias_chain, logical_security_history
from app.schemas.market_data import MarketBar


def source(changes):
    return {
        "security_id": "issuer-1", "membership": {"ticker": "NEW", "start": "2020-01-01", "end": None},
        "identity": {"confidence": "HIGH", "provider_symbol": "NEW",
                     "identifiers": {"OpenFigi": "FIGI"}, "symbol_changes": changes},
    }


def bars(count=230):
    start = datetime(2020, 1, 1, tzinfo=UTC)
    return [MarketBar(ticker="NEW", timestamp=start + timedelta(days=index),
                      open=10 + index / 100, high=11 + index / 100,
                      low=9 + index / 100, close=10 + index / 100, volume=1_000_000 + index)
            for index in range(count)]


def test_multi_alias_boundary_and_provenance_are_preserved() -> None:
    chain = build_linear_alias_chain(source([{
        "old_symbol": "OLD", "new_symbol": "NEW", "effective": "2020-04-01"
    }]))
    assert [(item.historical_ticker, item.valid_from, item.valid_to) for item in chain] == [
        ("OLD", date(2020, 1, 1), date(2020, 4, 1)),
        ("NEW", date(2020, 4, 1), None),
    ]
    logical = logical_security_history(chain, {"NEW": bars()})
    boundary = next(item for item in logical if item.bar.timestamp.date() == date(2020, 4, 1))
    assert boundary.historical_ticker == "NEW"
    assert boundary.provider_symbol == "NEW"


def test_features_do_not_reset_across_proven_same_security_ticker_change() -> None:
    chain = build_linear_alias_chain(source([{
        "old_symbol": "OLD", "new_symbol": "NEW", "effective": "2020-07-25"
    }]))
    logical = logical_security_history(chain, {"NEW": bars()})
    frame = FeatureEngine().calculate(pd.DataFrame([item.bar.model_dump() for item in logical]))
    boundary = frame[frame.timestamp.dt.date == date(2020, 7, 25)].iloc[0]
    assert not pd.isna(boundary["SMA_200"])
    assert not pd.isna(boundary["AVG_VOLUME_20D"])


def test_multi_predecessor_chain_fails_closed_and_prevents_successor_inheritance() -> None:
    with pytest.raises(ValueError, match="multi-predecessor"):
        build_linear_alias_chain(source([
            {"old_symbol": "OLD1", "new_symbol": "NEW", "effective": "2020-04-01"},
            {"old_symbol": "OLD2", "new_symbol": "NEW", "effective": "2020-04-01"},
        ]))


def test_stable_identifier_override_selects_only_proven_predecessor() -> None:
    chain = build_linear_alias_chain(source([
        {"old_symbol": "WRONG", "new_symbol": "NEW", "effective": "2020-04-01"},
        {"old_symbol": "PROVEN", "new_symbol": "NEW", "effective": "2020-04-01"},
    ]), predecessor_override="PROVEN")
    assert [item.historical_ticker for item in chain] == ["PROVEN", "NEW"]


def test_duplicate_logical_bars_are_rejected() -> None:
    chain = build_linear_alias_chain(source([]))
    duplicate = bars(1)[0]
    with pytest.raises(ValueError, match="duplicate logical bar"):
        logical_security_history(chain + chain, {"NEW": [duplicate]})


def test_replacement_identity_does_not_reuse_old_security_id() -> None:
    replacement = {
        "security_id": "issuer-2", "ticker": "REPLACEMENT", "provider_symbol": "REPLACEMENT",
        "confidence": "HIGH", "identifiers": {"ISIN": "US0000000002"},
    }
    chain = build_linear_alias_chain(source([]), replacement_identity=replacement)
    assert len(chain) == 1
    assert chain[0].security_id == "issuer-2"
    assert chain[0].historical_ticker == "REPLACEMENT"
    assert dict(chain[0].identifiers) == {"ISIN": "US0000000002"}


def test_ctra_documented_override_preserves_identity_across_cog_ticker_change() -> None:
    row = source([])
    row["security_id"] = "ctra-security"
    row["membership"] = {"ticker": "CTRA", "start": "2008-06-23", "end": "2026-05-07"}
    row["identity"]["provider_symbol"] = "CTRA"
    row["identity"]["identifiers"] = {"CIK": "0000858470"}
    chain = build_linear_alias_chain(row, symbol_changes_override=[{
        "old_symbol": "COG", "new_symbol": "CTRA", "effective": "2021-10-04",
    }])
    assert [(item.historical_ticker, item.valid_from, item.valid_to) for item in chain] == [
        ("COG", date(2008, 6, 23), date(2021, 10, 4)),
        ("CTRA", date(2021, 10, 4), date(2026, 5, 7)),
    ]
    assert {item.security_id for item in chain} == {"ctra-security"}
    assert {dict(item.identifiers)["CIK"] for item in chain} == {"0000858470"}
