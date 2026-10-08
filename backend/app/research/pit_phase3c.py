import hashlib
import json
import statistics
from collections import Counter, defaultdict
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.schemas.backtesting import BacktestEventResult
from app.schemas.market_data import MarketBar
from app.schemas.research import PortfolioSimulationResult


BUCKETS = ((0, 20), (20, 40), (40, 60), (60, 80), (80, 100))
NON_EXECUTABLE = "NON_EXECUTABLE_LIFECYCLE_TERMINATION"


def key(row) -> tuple[str, date]:
    security_id = str(row.security_id if hasattr(row, "security_id") else row.ticker)
    return security_id, row.signal_date


def bucket(score: float) -> str:
    for low, high in BUCKETS:
        if low <= score < high or (high == 100 and score == 100):
            return f"{low}-{high}"
    raise ValueError(f"score outside approved buckets: {score}")


def rejection_label(reason: str) -> str:
    return {
        "SIGNAL_SKIPPED_MAX_POSITIONS": "REJECTED_PORTFOLIO_FULL",
        "SIGNAL_SKIPPED_NO_CAPITAL": "REJECTED_INSUFFICIENT_CASH",
        "SIGNAL_SKIPPED_ALREADY_HELD": "REJECTED_DUPLICATE_POSITION",
    }.get(reason, "REJECTED_OTHER")


def accepted_map(result: PortfolioSimulationResult):
    return {key(row): row for row in result.entries}


def rejection_map(result: PortfolioSimulationResult):
    return {key(row): row for row in result.skipped_signals if row.reason != NON_EXECUTABLE}


def provenance_diagnostics(
    fixed: PortfolioSimulationResult, pit: PortfolioSimulationResult,
    fixed_keys: set[tuple[str, date]], pit_keys: set[tuple[str, date]],
) -> dict[str, Any]:
    f_acc, p_acc = accepted_map(fixed), accepted_map(pit)
    f_rej, p_rej = rejection_map(fixed), rejection_map(pit)
    groups = {
        "BOTH": fixed_keys & pit_keys,
        "FIXED_ONLY": fixed_keys - pit_keys,
        "PIT_ONLY": pit_keys - fixed_keys,
    }
    output = {}
    for name, keys in groups.items():
        row = {"available_signals": len(keys)}
        for arm, eligible, accepted, rejected in (
            ("fixed", name != "PIT_ONLY", f_acc, f_rej),
            ("pit", name != "FIXED_ONLY", p_acc, p_rej),
        ):
            if not eligible:
                row[arm] = {"eligibility": "NOT_APPLICABLE", "accepted": 0,
                            "rejected": 0, "acceptance_rate": None, "reasons": {}}
                continue
            reasons = Counter(rejection_label(rejected[item].reason)
                              for item in keys if item in rejected)
            accepted_n = sum(item in accepted for item in keys)
            rejected_n = sum(item in rejected for item in keys)
            row[arm] = {
                "eligibility": "ELIGIBLE", "accepted": accepted_n,
                "rejected": rejected_n,
                "acceptance_rate": accepted_n / len(keys) if keys else None,
                "reasons": dict(sorted(reasons.items())),
            }
        output[name] = row
    return output


def both_four_way(
    fixed: PortfolioSimulationResult, pit: PortfolioSimulationResult,
    both_keys: set[tuple[str, date]],
) -> dict[str, Any]:
    f_acc, p_acc = accepted_map(fixed), accepted_map(pit)
    f_rej, p_rej = rejection_map(fixed), rejection_map(pit)
    categories = {name: [] for name in (
        "ACCEPTED_IN_BOTH", "ACCEPTED_FIXED_ONLY", "ACCEPTED_PIT_ONLY", "REJECTED_IN_BOTH"
    )}
    paired_reasons = Counter()
    for item in sorted(both_keys, key=lambda value: (value[1], value[0])):
        in_fixed, in_pit = item in f_acc, item in p_acc
        if in_fixed and in_pit:
            category = "ACCEPTED_IN_BOTH"
        elif in_fixed:
            category = "ACCEPTED_FIXED_ONLY"
        elif in_pit:
            category = "ACCEPTED_PIT_ONLY"
        else:
            category = "REJECTED_IN_BOTH"
            paired_reasons[(f_rej[item].reason, p_rej[item].reason)] += 1
        row = {"security_id": item[0], "signal_date": item[1].isoformat()}
        if category == "ACCEPTED_FIXED_ONLY":
            row["opposite_rejection"] = p_rej[item].reason
        elif category == "ACCEPTED_PIT_ONLY":
            row["opposite_rejection"] = f_rej[item].reason
        categories[category].append(row)
    counts = {name: len(rows) for name, rows in categories.items()}
    return {
        "counts": counts, "reconciliation": sum(counts.values()),
        "paired_rejection_reasons": {
            f"{left} | {right}": count
            for (left, right), count in sorted(paired_reasons.items())
        },
        "fixed_only_acceptances": categories["ACCEPTED_FIXED_ONLY"],
        "pit_only_acceptances": categories["ACCEPTED_PIT_ONLY"],
        "status": "PASS" if sum(counts.values()) == len(both_keys) else "FAIL",
    }


def holdings_by_session(result: PortfolioSimulationResult) -> dict[date, set[str]]:
    held: set[str] = set()
    output = {}
    for row in result.daily_equity:
        held.update(row.entries)
        held.difference_update(row.exits)
        output[row.session_date] = set(held)
    return output


def first_divergence(
    fixed: PortfolioSimulationResult, pit: PortfolioSimulationResult,
    fixed_events: list[BacktestEventResult], pit_events: list[BacktestEventResult],
) -> dict[str, Any]:
    f_keys = {key(row) for row in fixed_events if row.entry_date is not None}
    p_keys = {key(row) for row in pit_events if row.entry_date is not None}
    signal_diff = min(f_keys ^ p_keys, key=lambda value: (value[1], value[0]))
    signal_ledger_row = next(
        row for row in (
            fixed.entries + fixed.skipped_signals + pit.entries + pit.skipped_signals
        ) if key(row) == signal_diff
    )
    f_acc, p_acc = accepted_map(fixed), accepted_map(pit)
    accepted_diff = min(set(f_acc) ^ set(p_acc), key=lambda value: (
        (f_acc.get(value) or p_acc[value]).entry_date, value[0]
    ))
    divergence_entry = f_acc.get(accepted_diff) or p_acc[accepted_diff]
    divergence_date = divergence_entry.entry_date
    f_daily = {row.session_date: row for row in fixed.daily_equity}
    p_daily = {row.session_date: row for row in pit.daily_equity}
    f_hold, p_hold = holdings_by_session(fixed), holdings_by_session(pit)
    first_hold = next(day for day in sorted(f_daily) if f_hold[day] != p_hold[day])
    first_cash = next(day for day in sorted(f_daily)
                      if abs(f_daily[day].cash - p_daily[day].cash) > 1e-9)
    first_equity = next(day for day in sorted(f_daily)
                        if abs(f_daily[day].total_equity - p_daily[day].total_equity) > 1e-9)
    all_events = defaultdict(list)
    for event in fixed_events:
        if event.entry_date:
            all_events[("FIXED", event.entry_date)].append(event)
    for event in pit_events:
        if event.entry_date:
            all_events[("PIT", event.entry_date)].append(event)
    ranks = {}
    for arm in ("FIXED", "PIT"):
        ordered = sorted(all_events[(arm, divergence_date)],
                         key=lambda row: (-row.score, str(row.ticker)))
        ranks[arm] = next((index + 1 for index, row in enumerate(ordered)
                           if key(row) == accepted_diff), None)
    f_index = sorted(f_daily).index(divergence_date)
    previous = sorted(f_daily)[max(0, f_index - 1)]
    f_rej, p_rej = rejection_map(fixed), rejection_map(pit)
    def action(accepted, rejected):
        if accepted_diff in accepted:
            return "ACCEPTED"
        return rejected[accepted_diff].reason if accepted_diff in rejected else "NOT_ELIGIBLE"
    return {
        "first_signal_set_difference": {
            "security_id": signal_diff[0], "signal_date": signal_diff[1].isoformat(),
            "ticker": signal_ledger_row.ticker,
            "provenance": "FIXED_ONLY" if signal_diff in f_keys else "PIT_ONLY",
        },
        "first_accepted_trade_difference": {
            "security_id": accepted_diff[0],
            "ticker": divergence_entry.ticker,
            "signal_date": accepted_diff[1].isoformat(),
            "entry_date": divergence_date.isoformat(),
            "fixed_action": action(f_acc, f_rej), "pit_action": action(p_acc, p_rej),
            "score": divergence_entry.score,
            "candidate_rank_fixed": ranks["FIXED"], "candidate_rank_pit": ranks["PIT"],
            "fixed_available_slots": 10 - f_daily[previous].open_positions,
            "pit_available_slots": 10 - p_daily[previous].open_positions,
            "fixed_available_cash": f_daily[previous].cash,
            "pit_available_cash": p_daily[previous].cash,
            "fixed_existing_positions": sorted(f_hold[previous]),
            "pit_existing_positions": sorted(p_hold[previous]),
            "mechanical_reason": (
                "different eligible signal sets created different prior holdings, cash and slot state"
            ),
        },
        "first_holdings_difference": first_hold.isoformat(),
        "first_cash_difference": first_cash.isoformat(),
        "first_equity_difference": first_equity.isoformat(),
        "timeline": [{
            "session": day.isoformat(),
            "fixed_cash": f_daily[day].cash, "pit_cash": p_daily[day].cash,
            "fixed_positions": len(f_hold[day]), "pit_positions": len(p_hold[day]),
            "fixed_entries": f_daily[day].entries, "pit_entries": p_daily[day].entries,
            "fixed_exits": f_daily[day].exits, "pit_exits": p_daily[day].exits,
        } for day in sorted(f_daily)[max(0, f_index - 2):f_index + 3]],
    }


def capacity_and_cash(
    result: PortfolioSimulationResult, events: list[BacktestEventResult],
) -> dict[str, Any]:
    event_map = {key(row): row for row in events}
    daily = {row.session_date: row for row in result.daily_equity}
    sessions = sorted(daily)
    index = {day: position for position, day in enumerate(sessions)}
    constrained = []
    for entry in result.entries:
        position = index[entry.entry_date]
        prior_equity = (result.configuration["initial_capital"] if position == 0
                        else daily[sessions[position - 1]].total_equity)
        target = prior_equity * result.configuration["target_allocation"]
        shortfall = max(0.0, target - entry.position_size)
        if shortfall > 1e-8:
            constrained.append({
                "security_id": entry.security_id, "ticker": entry.ticker,
                "signal_date": entry.signal_date.isoformat(),
                "entry_date": entry.entry_date.isoformat(),
                "target_notional": target, "actual_notional": entry.position_size,
                "shortfall": shortfall,
            })
    constrained.sort(key=lambda row: (-row["shortfall"], row["entry_date"]))
    reasons = Counter(row.reason for row in result.skipped_signals
                      if row.reason != NON_EXECUTABLE)
    return {
        "sessions_at_10_positions": sum(row.open_positions == 10
                                         for row in result.daily_equity),
        "rejected_full": reasons["SIGNAL_SKIPPED_MAX_POSITIONS"],
        "rejected_duplicate": reasons["SIGNAL_SKIPPED_ALREADY_HELD"],
        "rejected_insufficient_cash": reasons["SIGNAL_SKIPPED_NO_CAPITAL"],
        "cash_constrained_entries": {
            "count": len(constrained),
            "aggregate_target_notional": sum(row["target_notional"] for row in constrained),
            "aggregate_actual_notional": sum(row["actual_notional"] for row in constrained),
            "aggregate_shortfall": sum(row["shortfall"] for row in constrained),
            "largest_shortfall": constrained[0]["shortfall"] if constrained else 0,
            "entries": constrained,
        },
    }


def open_positions(result: PortfolioSimulationResult, bars: dict[str, list[MarketBar]]):
    closed = {key(row) for row in result.trades}
    output = []
    for entry in result.entries:
        if key(entry) in closed:
            continue
        available = [bar for bar in bars[entry.security_id]
                     if bar.timestamp.date() <= result.end_date]
        mark = max(available, key=lambda row: row.timestamp)
        output.append({
            "security_id": entry.security_id, "ticker": entry.ticker,
            "signal_date": entry.signal_date, "entry_date": entry.entry_date,
            "provenance": entry.provenance, "score": entry.score,
            "position_size": entry.position_size, "quantity": entry.quantity,
            "mark_date": mark.timestamp.date(), "mark": mark.close,
            "market_value": entry.quantity * mark.close,
            "unrealized_pnl": entry.quantity * mark.close - entry.position_size,
        })
    return output


def pnl_reconciliation(result: PortfolioSimulationResult, bars: dict[str, list[MarketBar]]):
    realized = sum(row.pnl for row in result.trades)
    opened = open_positions(result, bars)
    unrealized = sum(row["unrealized_pnl"] for row in opened)
    final = result.daily_equity[-1]
    error_one = final.total_equity - (
        result.configuration["initial_capital"] + realized + unrealized
    )
    error_two = final.total_equity - final.cash - final.positions_market_value
    groups = {name: {"realized_pnl": 0.0, "unrealized_pnl": 0.0}
              for name in ("BOTH", "FIXED_ONLY", "PIT_ONLY")}
    for trade in result.trades:
        groups[trade.provenance]["realized_pnl"] += trade.pnl
    for row in opened:
        groups[row["provenance"]]["unrealized_pnl"] += row["unrealized_pnl"]
    for row in groups.values():
        row["total_pnl"] = row["realized_pnl"] + row["unrealized_pnl"]
    return {
        "initial_capital": result.configuration["initial_capital"],
        "realized_pnl": realized, "unrealized_pnl": unrealized,
        "final_equity": final.total_equity, "cash": final.cash,
        "open_market_value": final.positions_market_value,
        "capital_pnl_error": error_one, "cash_market_value_error": error_two,
        "by_provenance": groups,
        "status": "PASS" if abs(error_one) <= 1e-8 and abs(error_two) <= 1e-8 else "FAIL",
    }


def trade_row(row) -> dict[str, Any]:
    return {
        "security_id": row.security_id, "ticker": row.ticker,
        "signal_date": row.signal_date.isoformat(), "entry_date": row.entry_date.isoformat(),
        "exit_date": row.exit_date.isoformat(), "provenance": row.provenance,
        "return_pct": row.net_return * 100, "realized_pnl": row.pnl,
        "entry_notional": row.quantity * row.entry_price, "quantity": row.quantity,
    }


def concentration(result: PortfolioSimulationResult) -> dict[str, Any]:
    ranked = sorted(result.trades, key=lambda row: row.pnl, reverse=True)
    total = sum(row.pnl for row in ranked)
    initial = result.configuration["initial_capital"]
    sums = {
        "top_1": sum(row.pnl for row in ranked[:1]),
        "top_5": sum(row.pnl for row in ranked[:5]),
        "top_10": sum(row.pnl for row in ranked[:10]),
        "bottom_10": sum(row.pnl for row in sorted(ranked, key=lambda row: row.pnl)[:10]),
    }
    return {
        "total_realized_pnl": total,
        "dollars": sums,
        "pct_of_realized_pnl": {name: value / total for name, value in sums.items()},
        "pct_of_initial_capital": {name: value / initial for name, value in sums.items()},
        "top_10": [trade_row(row) for row in ranked[:10]],
        "bottom_10": [trade_row(row) for row in sorted(ranked, key=lambda row: row.pnl)[:10]],
    }


def cross_arm_matching(
    source: PortfolioSimulationResult, other: PortfolioSimulationResult,
    selected: list[dict[str, Any]], eligible_other: set[tuple[str, date]],
) -> list[dict[str, Any]]:
    other_entries = accepted_map(other)
    other_trades = {key(row): row for row in other.trades}
    other_rejections = rejection_map(other)
    output = []
    for row in selected:
        item = (row["security_id"], date.fromisoformat(row["signal_date"]))
        if item in other_entries:
            classification = "EXECUTED_IN_BOTH"
        elif item in other_rejections:
            classification = "REJECTED_IN_OTHER_ARM"
        elif item not in eligible_other:
            classification = "NOT_ELIGIBLE_IN_OTHER_ARM"
        else:
            classification = "OTHER"
        opposite = other_entries.get(item)
        opposite_trade = other_trades.get(item)
        output.append({
            **row, "classification": classification,
            "opposite_rejection": other_rejections[item].reason if item in other_rejections else None,
            "opposite_entry_notional": opposite.position_size if opposite else None,
            "opposite_quantity": opposite.quantity if opposite else None,
            "opposite_return_pct": opposite_trade.net_return * 100 if opposite_trade else None,
            "opposite_realized_pnl": opposite_trade.pnl if opposite_trade else None,
        })
    return output


def returns_by_provenance(result: PortfolioSimulationResult, bars):
    opened = open_positions(result, bars)
    output = {}
    for name in ("BOTH", "FIXED_ONLY", "PIT_ONLY"):
        trades = [row for row in result.trades if row.provenance == name]
        returns = [row.net_return for row in trades]
        output[name] = {
            "closed_trades": len(trades),
            "mean_return": statistics.fmean(returns) if returns else None,
            "median_return": statistics.median(returns) if returns else None,
            "positive_rate": sum(value > 0 for value in returns) / len(returns) if returns else None,
            "realized_pnl": sum(row.pnl for row in trades),
            "mean_holding_sessions": statistics.fmean(row.holding_sessions for row in trades)
                if trades else None,
            "ordinary_exits": sum(row.lifecycle_treatment is None for row in trades),
            "lifecycle_exits": sum(row.lifecycle_treatment is not None for row in trades),
            "open_positions": sum(row["provenance"] == name for row in opened),
        }
    return output


def common_trade_effect(
    fixed: PortfolioSimulationResult, pit: PortfolioSimulationResult,
) -> dict[str, Any]:
    fixed_entries, pit_entries = accepted_map(fixed), accepted_map(pit)
    fixed_trades = {key(row): row for row in fixed.trades}
    pit_trades = {key(row): row for row in pit.trades}
    common = sorted(set(fixed_entries) & set(pit_entries), key=lambda item: (item[1], item[0]))
    rows = []
    invariant_failures = []
    for item in common:
        left, right = fixed_entries[item], pit_entries[item]
        left_trade, right_trade = fixed_trades.get(item), pit_trades.get(item)
        same_execution = bool(left_trade and right_trade and (
            left_trade.entry_date, left_trade.exit_date, left_trade.entry_price,
            left_trade.exit_price, left_trade.lifecycle_treatment,
        ) == (
            right_trade.entry_date, right_trade.exit_date, right_trade.entry_price,
            right_trade.exit_price, right_trade.lifecycle_treatment,
        ))
        same_return = bool(
            left_trade and right_trade
            and abs(left_trade.net_return - right_trade.net_return) <= 1e-12
        )
        if same_execution and not same_return:
            invariant_failures.append(item)
        rows.append({
            "security_id": item[0], "ticker": left.ticker,
            "signal_date": item[1].isoformat(),
            "entry_date_fixed": left.entry_date.isoformat(),
            "entry_date_pit": right.entry_date.isoformat(),
            "entry_price_fixed": left.entry_price, "entry_price_pit": right.entry_price,
            "entry_notional_fixed": left.position_size,
            "entry_notional_pit": right.position_size,
            "quantity_fixed": left.quantity, "quantity_pit": right.quantity,
            "notional_difference": right.position_size - left.position_size,
            "exit_date_fixed": left_trade.exit_date.isoformat() if left_trade else None,
            "exit_date_pit": right_trade.exit_date.isoformat() if right_trade else None,
            "exit_price_fixed": left_trade.exit_price if left_trade else None,
            "exit_price_pit": right_trade.exit_price if right_trade else None,
            "return_pct_fixed": left_trade.net_return * 100 if left_trade else None,
            "return_pct_pit": right_trade.net_return * 100 if right_trade else None,
            "pnl_fixed": left_trade.pnl if left_trade else None,
            "pnl_pit": right_trade.pnl if right_trade else None,
            "same_execution": same_execution, "same_return": same_return,
        })
    rows.sort(key=lambda row: (-abs(row["notional_difference"]), row["signal_date"]))
    case_studies = {
        ticker: [row for row in rows if row["ticker"] == ticker]
        for ticker in ("INTC", "WDC")
    }
    return {
        "common_executed_positions": len(common),
        "common_closed_trades": len(set(fixed_trades) & set(pit_trades)),
        "different_position_sizes": sum(
            abs(row["notional_difference"]) > 1e-8 for row in rows
        ),
        "total_absolute_notional_difference": sum(
            abs(row["notional_difference"]) for row in rows
        ),
        "identical_execution_return_failures": [
            {"security_id": item[0], "signal_date": item[1].isoformat()}
            for item in invariant_failures
        ],
        "largest_notional_differences": rows[:20],
        "case_studies": case_studies,
        "status": "PASS" if not invariant_failures else "FAIL",
        "interpretation": (
            "Observed notional differences arise from prior-equity and available-cash "
            "path differences; they are not additive CAGR contributions."
        ),
    }


def _period_summaries(result: PortfolioSimulationResult, frequency: str) -> list[dict[str, Any]]:
    rows = result.daily_equity
    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        label = str(row.session_date.year) if frequency == "year" else row.session_date.strftime("%Y-%m")
        groups[label].append(row)
    output = []
    prior_equity = result.configuration["initial_capital"]
    ordered_groups = sorted(groups.items())
    for group_index, (label, values) in enumerate(ordered_groups):
        start = prior_equity
        end = values[-1].total_equity
        peak = start
        maximum_drawdown = 0.0
        for row in values:
            peak = max(peak, row.total_equity)
            maximum_drawdown = min(maximum_drawdown, row.total_equity / peak - 1)
        output.append({
            "period": label, "start_date": values[0].session_date.isoformat(),
            "end_date": values[-1].session_date.isoformat(),
            "partial_period": group_index in {0, len(ordered_groups) - 1},
            "starting_equity": start, "ending_equity": end,
            "return": end / start - 1, "maximum_drawdown": maximum_drawdown,
            "average_exposure": statistics.fmean(row.gross_exposure for row in values),
            "sessions": len(values),
        })
        prior_equity = end
    return output


def equity_path(fixed: PortfolioSimulationResult, pit: PortfolioSimulationResult) -> dict[str, Any]:
    fixed_daily = {row.session_date: row for row in fixed.daily_equity}
    pit_daily = {row.session_date: row for row in pit.daily_equity}
    sessions = sorted(set(fixed_daily) & set(pit_daily))
    differences = [{
        "session": day, "dollar_gap_pit_minus_fixed": (
            pit_daily[day].total_equity - fixed_daily[day].total_equity
        ),
        "relative_ratio_pit_to_fixed": (
            pit_daily[day].total_equity / fixed_daily[day].total_equity - 1
        ),
    } for day in sessions]
    first = next(row for row in differences if abs(row["dollar_gap_pit_minus_fixed"]) > 1e-9)
    largest_dollar = max(differences, key=lambda row: abs(row["dollar_gap_pit_minus_fixed"]))
    largest_ratio = max(differences, key=lambda row: abs(row["relative_ratio_pit_to_fixed"]))
    def serialize(row):
        return {**row, "session": row["session"].isoformat()}
    return {
        "first_equity_divergence": serialize(first),
        "largest_absolute_dollar_gap": serialize(largest_dollar),
        "largest_relative_ratio_divergence": serialize(largest_ratio),
        "final_dollar_gap_pit_minus_fixed": differences[-1]["dollar_gap_pit_minus_fixed"],
        "annual": {
            "FIXED_REBUILT": _period_summaries(fixed, "year"),
            "PIT": _period_summaries(pit, "year"),
        },
        "monthly": {
            "FIXED_REBUILT": _period_summaries(fixed, "month"),
            "PIT": _period_summaries(pit, "month"),
        },
    }


def score_bucket_diagnostics(result: PortfolioSimulationResult) -> dict[str, Any]:
    trades = {key(row): row for row in result.trades}
    output = {}
    for label in (f"{low}-{high}" for low, high in BUCKETS):
        entries = [row for row in result.entries if bucket(row.score) == label]
        closed = [trades[key(row)] for row in entries if key(row) in trades]
        values = [row.net_return for row in closed]
        output[label] = {
            "accepted": len(entries), "closed_trades": len(closed),
            "mean_closed_return": statistics.fmean(values) if values else None,
            "median_closed_return": statistics.median(values) if values else None,
            "positive_rate": sum(value > 0 for value in values) / len(values) if values else None,
            "realized_pnl": sum(row.pnl for row in closed),
            "open_positions": len(entries) - len(closed),
        }
    return output


def market_regime_labels(benchmark: list[MarketBar]) -> dict[date, dict[str, str]]:
    frame = pd.DataFrame([bar.model_dump() for bar in benchmark]).sort_values("timestamp")
    if frame.empty:
        return {}
    frame["session"] = pd.to_datetime(frame["timestamp"], utc=True).dt.date
    close = frame["close"].astype(float)
    frame["sma50"] = close.rolling(50, min_periods=50).mean()
    frame["sma200"] = close.rolling(200, min_periods=200).mean()
    frame["realized_vol"] = (
        close.pct_change(fill_method=None).rolling(20, min_periods=20).std(ddof=1)
        * np.sqrt(252)
    )
    prior_vols: list[float] = []
    output = {}
    for _, row in frame.iterrows():
        vol = None if pd.isna(row["realized_vol"]) else float(row["realized_vol"])
        volatility = "REGIME_UNAVAILABLE"
        if vol is not None and len(prior_vols) >= 60:
            low, high = np.quantile(prior_vols, [1 / 3, 2 / 3])
            volatility = "VOL_LOW" if vol <= low else ("VOL_HIGH" if vol > high else "VOL_MID")
        if pd.isna(row["sma200"]):
            sma200 = sma50 = "REGIME_UNAVAILABLE"
            volatility = "REGIME_UNAVAILABLE"
        else:
            sma200 = "SPY_ABOVE_SMA200" if row["close"] > row["sma200"] else "SPY_BELOW_SMA200"
            sma50 = "SPY_ABOVE_SMA50" if row["close"] > row["sma50"] else "SPY_BELOW_SMA50"
        output[row["session"]] = {"sma200": sma200, "sma50": sma50, "volatility": volatility}
        if vol is not None:
            prior_vols.append(vol)
    return output


def market_regime_diagnostics(
    result: PortfolioSimulationResult, benchmark: list[MarketBar],
) -> dict[str, Any]:
    labels = market_regime_labels(benchmark)
    entries = defaultdict(list)
    trades = defaultdict(list)
    for row in result.entries:
        regime = labels.get(row.signal_date, {})
        for dimension, label in regime.items():
            entries[(dimension, label)].append(row)
    for row in result.trades:
        regime = labels.get(row.signal_date, {})
        for dimension, label in regime.items():
            trades[(dimension, label)].append(row)
    output = {}
    for dimension in ("sma200", "sma50", "volatility"):
        dimension_rows = {}
        names = sorted({label.get(dimension, "REGIME_UNAVAILABLE") for label in labels.values()})
        for name in names:
            holding = [row for row in result.daily_equity
                       if labels.get(row.session_date, {}).get(dimension) == name]
            closed = trades[(dimension, name)]
            dimension_rows[name] = {
                "holding_session_count": len(holding),
                "holding_session_compounded_return": (
                    float(np.prod([1 + row.daily_return for row in holding]) - 1)
                    if holding else None
                ),
                "holding_session_average_exposure": (
                    statistics.fmean(row.gross_exposure for row in holding) if holding else None
                ),
                "accepted_entries_by_signal_date_regime": len(entries[(dimension, name)]),
                "closed_trades_by_signal_date_regime": len(closed),
                "mean_closed_trade_return_by_signal_date_regime": (
                    statistics.fmean(row.net_return for row in closed) if closed else None
                ),
            }
        output[dimension] = dimension_rows
    return {
        "status": "PASS",
        "definitions": {
            "sma50": "SPY close versus trailing 50-session simple moving average",
            "sma200": "SPY close versus trailing 200-session simple moving average",
            "volatility": (
                "20-session annualized close-return sample volatility; expanding terciles "
                "from at least 60 prior volatility observations only"
            ),
            "session_alignment": "classification uses information through each session close",
            "holding_return_aggregation": (
                "product of portfolio daily returns on sessions bearing the label; descriptive "
                "and non-contiguous when regimes recur"
            ),
            "distinction": (
                "accepted entries and closed trades use the signal-date regime; portfolio return "
                "and exposure use the holding-session regime"
            ),
        },
        "regimes": output,
    }


def lifecycle_diagnostics(
    result: PortfolioSimulationResult, lifecycle_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    entries = accepted_map(result)
    rows = []
    for trade in result.trades:
        if trade.lifecycle_treatment is None:
            continue
        entry = entries[key(trade)]
        rows.append({
            "security_id": trade.security_id, "ticker": trade.ticker,
            "signal_date": trade.signal_date.isoformat(),
            "entry_date": trade.entry_date.isoformat(),
            "scheduled_exit": entry.scheduled_exit_date.isoformat(),
            "actual_exit": trade.exit_date.isoformat(),
            "lifecycle_type": lifecycle_metadata[trade.security_id]["category"],
            "treatment": trade.lifecycle_treatment,
            "last_legitimate_close": trade.reference_exit_price,
            "realized_return": trade.net_return, "realized_pnl": trade.pnl,
        })
    return {
        "coverage_qualification": "KNOWN_LIFECYCLE_LOWER_BOUND",
        "positions": sorted(rows, key=lambda row: (row["actual_exit"], row["security_id"])),
        "status": "PASS",
    }


def rejection_diagnostics(result: PortfolioSimulationResult) -> dict[str, Any]:
    rows = [row for row in result.skipped_signals if row.reason != NON_EXECUTABLE]
    def table(labeler):
        grouped: dict[str, Counter] = defaultdict(Counter)
        for row in rows:
            grouped[str(labeler(row))][rejection_label(row.reason)] += 1
        return {name: dict(sorted(counts.items())) for name, counts in sorted(grouped.items())}
    outside = [row for row in rows if row.reason == "SIGNAL_SKIPPED_ENTRY_OUTSIDE_RESEARCH_WINDOW"]
    return {
        "by_provenance": table(lambda row: row.provenance),
        "by_calendar_year": table(lambda row: row.signal_date.year),
        "by_score_bucket": table(lambda row: bucket(row.score)),
        "out_of_window_next_open": [{
            "security_id": row.security_id, "ticker": row.ticker,
            "signal_date": row.signal_date.isoformat(), "reason": row.reason,
        } for row in outside],
    }


def sequential_step_summary(result: PortfolioSimulationResult) -> dict[str, Any]:
    metrics = result.metrics
    final = result.daily_equity[-1]
    return {
        "initial_capital": result.configuration["initial_capital"],
        "final_equity": final.total_equity, "total_return": metrics["total_return"],
        "cagr": metrics["annualized_return_cagr"],
        "annualized_volatility": metrics["annualized_volatility"],
        "maximum_drawdown": metrics["maximum_drawdown"],
        "sharpe": metrics["sharpe_ratio"], "sortino": metrics["sortino_ratio"],
        "calmar": metrics["calmar_ratio"], "accepted_signals": len(result.entries),
        "closed_trades": len(result.trades),
        "open_positions": final.open_positions,
        "average_exposure": statistics.fmean(row.gross_exposure for row in result.daily_equity),
        "total_slippage": (
            sum(row.entry_slippage_cost for row in result.entries)
            + sum(row.exit_slippage_cost for row in result.trades)
        ),
    }


def diagnostic_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
