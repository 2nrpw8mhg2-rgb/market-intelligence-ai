from app.database.base import Base
from app.models import (  # noqa: F401
    BacktestRun,
    BacktestTrade,
    Feature,
    MarketBarRecord,
    Opportunity,
    Strategy,
    Symbol,
    Universe,
    UniverseMembership,
)


def test_initial_schema_contains_expected_tables() -> None:
    assert set(Base.metadata.tables) == {
        "symbols",
        "market_bars",
        "features",
        "opportunities",
        "strategies",
        "backtest_runs",
        "backtest_trades",
        "universes",
        "universe_memberships",
    }


def test_time_series_tables_have_composite_indexes() -> None:
    market_bar_indexes = {index.name for index in Base.metadata.tables["market_bars"].indexes}
    feature_indexes = {index.name for index in Base.metadata.tables["features"].indexes}

    assert "ix_market_bars_symbol_timestamp" in market_bar_indexes
    assert "ix_features_symbol_timestamp" in feature_indexes


def test_market_bar_identity_includes_provider() -> None:
    constraints = Base.metadata.tables["market_bars"].constraints
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in constraints
        if hasattr(constraint, "columns") and constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert ("symbol_id", "timestamp", "timeframe", "provider") in unique_columns
