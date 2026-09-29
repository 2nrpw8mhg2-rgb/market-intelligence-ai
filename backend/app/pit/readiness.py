from collections import Counter
from datetime import date

import pandas as pd

from app.features import FeatureEngine
from app.market_data.calendar import NYSETradingCalendar
from app.schemas.market_data import MarketBar
from app.schemas.universe import MembershipImportRecord


def merge_provider_bars(primary: list[MarketBar], supplemental: list[MarketBar]) -> list[MarketBar]:
    """Fill absent dates from a proven secondary provider without overwriting observations."""
    by_date = {bar.timestamp.date(): bar for bar in primary}
    for bar in supplemental:
        by_date.setdefault(bar.timestamp.date(), bar)
    return [by_date[key] for key in sorted(by_date)]


def assess_alias_readiness(
    membership: MembershipImportRecord, bars: list[MarketBar], sessions: list[date],
    *, natural_unavailable_sessions: set[date] | None = None,
) -> dict:
    natural_unavailable_sessions = natural_unavailable_sessions or set()
    if membership.eligibility_status != "ELIGIBLE":
        return {"status": "NON_TRADABLE", "evaluable_sessions": 0, "missing_membership_sessions": 0}
    active = [session for session in sessions if membership.valid_from <= session and
              (membership.valid_to is None or session < membership.valid_to)]
    if not bars:
        return {"status": "BLOCKED", "evaluable_sessions": 0,
                "missing_membership_sessions": len(active), "reason": "NO_PRICE_SERIES"}
    frame = FeatureEngine().calculate(pd.DataFrame([bar.model_dump() for bar in bars]))
    by_date = {row["timestamp"].date(): row for _, row in frame.iterrows()}
    required = ("SMA_200", "PREVIOUS_HIGH_20D", "RELATIVE_VOLUME",
                "MOMENTUM_20D", "AVG_DOLLAR_VOLUME_20D")
    evaluable = sum(
        session in by_date and all(not pd.isna(by_date[session].get(key)) for key in required)
        for session in active if session not in natural_unavailable_sessions
    )
    natural = sum(session in natural_unavailable_sessions for session in active)
    missing = sum(session not in by_date and session not in natural_unavailable_sessions for session in active)
    warmup = len(active) - evaluable - missing - natural
    status = "READY" if evaluable == len(active) else "READY_WITH_DOCUMENTED_LIMITATION"
    return {
        "status": status, "active_sessions": len(active),
        "evaluable_sessions": evaluable, "missing_membership_sessions": missing,
        "feature_warmup_sessions": warmup,
        "natural_lifecycle_sessions": natural,
        "first_price": bars[0].timestamp.date().isoformat(),
        "last_price": bars[-1].timestamp.date().isoformat(),
    }


def readiness_summary(rows: list[dict]) -> dict:
    return dict(Counter(row["status"] for row in rows))
