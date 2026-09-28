from collections import Counter, defaultdict
from datetime import date
from typing import Any

import numpy as np

from app.eodhd.models import EODBar, HistoricalConstituent, build_membership_snapshot
from app.market_data.calendar import NYSETradingCalendar
from app.schemas.market_data import MarketBar


def snapshot_diagnostics(records: list[HistoricalConstituent], as_of: date) -> dict[str, Any]:
    members = build_membership_snapshot(records, as_of)
    counts = Counter(item.code for item in members)
    return {
        "date": as_of.isoformat(), "constituents": len(members),
        "unique_symbols": len(counts),
        "duplicates": sorted(code for code, count in counts.items() if count > 1),
        "missing_start_date": sum(item.start_date is None for item in members),
        "delisted_today": sorted(item.code for item in members if item.is_delisted),
    }


def duplicate_memberships(records: list[HistoricalConstituent]) -> list[dict[str, Any]]:
    grouped: dict[str, list[HistoricalConstituent]] = defaultdict(list)
    for item in records:
        grouped[item.code].append(item)
    return [{"code": code, "records": len(items)} for code, items in sorted(grouped.items()) if len(items) > 1]


def coverage_diagnostics(
    records: list[HistoricalConstituent], prices: dict[str, list[EODBar]],
    start: date, end: date, calendar: NYSETradingCalendar | None = None,
    *, end_date_inclusive: bool = True,
) -> dict[str, Any]:
    calendar = calendar or NYSETradingCalendar()
    sessions = calendar.trading_days_between(start, end)
    missing_by_year: Counter[int] = Counter()
    details = []
    total = present = 0
    for item in records:
        expected = [session for session in sessions if item.is_member_on(
            session, end_date_inclusive=end_date_inclusive,
        )]
        available = {bar.date for bar in prices.get(item.code, [])}
        missing = [session for session in expected if session not in available]
        total += len(expected)
        present += len(expected) - len(missing)
        missing_by_year.update(session.year for session in missing)
        details.append({
            "code": item.code, "expected_security_days": len(expected),
            "with_price": len(expected) - len(missing), "missing": len(missing),
            "coverage_pct": ((len(expected) - len(missing)) / len(expected) * 100) if expected else None,
            "is_delisted": item.is_delisted,
        })
    return {
        "sample_securities": len(records), "membership_security_days": total,
        "end_date_policy": "inclusive" if end_date_inclusive else "exclusive",
        "security_days_with_price": present, "security_days_missing": total - present,
        "coverage_pct": present / total * 100 if total else None,
        "securities_without_complete_coverage": sum(item["missing"] > 0 for item in details),
        "missing_by_year": dict(sorted(missing_by_year.items())), "securities": details,
    }


def compare_provider_bars(eodhd: list[EODBar], massive: list[MarketBar]) -> dict[str, Any]:
    left = {bar.date: bar for bar in eodhd}
    right = {bar.timestamp.date(): bar for bar in massive}
    dates = sorted(left.keys() & right.keys())
    fields = ("open", "high", "low", "close", "volume")
    differences = {}
    for field in fields:
        pairs = [(float(getattr(left[day], field)), float(getattr(right[day], field))) for day in dates]
        pct = [abs(a - b) / abs(b) for a, b in pairs if b]
        differences[field] = {
            "mean_absolute_pct_difference": float(np.mean(pct)) if pct else None,
            "max_absolute_pct_difference": float(np.max(pct)) if pct else None,
            "exact_matches": sum(abs(a - b) < 1e-8 for a, b in pairs),
        }
    close_rows = sorted(({
        "date": day.isoformat(), "eodhd_raw_close": left[day].close,
        "eodhd_adjusted_close": left[day].adjusted_close, "massive_close": right[day].close,
        "raw_to_massive_ratio": left[day].close / right[day].close if right[day].close else None,
    } for day in dates), key=lambda row: abs((row["raw_to_massive_ratio"] or 1) - 1), reverse=True)
    ratios_by_year = {}
    for year in sorted({day.year for day in dates}):
        ratios = [left[day].close / right[day].close for day in dates if day.year == year and right[day].close]
        ratios_by_year[str(year)] = float(np.median(ratios)) if ratios else None
    return {
        "overlap_sessions": len(dates), "first_overlap": dates[0].isoformat() if dates else None,
        "last_overlap": dates[-1].isoformat() if dates else None, "differences": differences,
        "largest_close_differences": close_rows[:5],
        "median_raw_close_to_massive_ratio_by_year": ratios_by_year,
    }
