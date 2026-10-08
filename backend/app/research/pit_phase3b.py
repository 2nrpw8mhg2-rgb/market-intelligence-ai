import hashlib
import json
import statistics
from collections import Counter
from datetime import date
from typing import Any

from app.schemas.market_data import MarketBar
from app.schemas.research import PortfolioSimulationResult


REJECTION_LABELS = {
    "SIGNAL_SKIPPED_MAX_POSITIONS": "REJECTED_PORTFOLIO_FULL",
    "SIGNAL_SKIPPED_NO_CAPITAL": "REJECTED_INSUFFICIENT_CASH",
    "SIGNAL_SKIPPED_ALREADY_HELD": "REJECTED_DUPLICATE_POSITION",
}
NON_EXECUTABLE_REASON = "NON_EXECUTABLE_LIFECYCLE_TERMINATION"


def _event_key(security_id: str | None, signal_date: date) -> tuple[str, date]:
    if security_id is None:
        raise ValueError("Phase 3B ledger row lacks security_id")
    return security_id, signal_date


def classify_signal_outcomes(
    result: PortfolioSimulationResult, *, expected_executable: int,
) -> dict[str, Any]:
    counts = Counter({
        "ACCEPTED": len(result.entries),
        "REJECTED_PORTFOLIO_FULL": 0,
        "REJECTED_INSUFFICIENT_CASH": 0,
        "REJECTED_DUPLICATE_POSITION": 0,
        "REJECTED_OTHER": 0,
    })
    other_reasons: Counter[str] = Counter()
    non_executable = 0
    for row in result.skipped_signals:
        if row.reason == NON_EXECUTABLE_REASON:
            non_executable += 1
            continue
        label = REJECTION_LABELS.get(row.reason, "REJECTED_OTHER")
        counts[label] += 1
        if label == "REJECTED_OTHER":
            other_reasons[row.reason] += 1
    reconciled = sum(counts.values())
    return {
        **dict(counts),
        "considered": expected_executable,
        "reconciled": reconciled,
        "non_executable_skipped": non_executable,
        "reconciliation_error": reconciled - expected_executable,
        "other_reasons": dict(sorted(other_reasons.items())),
        "status": "PASS" if reconciled == expected_executable else "FAIL",
    }


def accounting_reconciliation(
    result: PortfolioSimulationResult, *, maximum_positions: int,
) -> dict[str, Any]:
    errors = [
        abs(row.total_equity - row.cash - row.positions_market_value)
        for row in result.daily_equity
    ]
    accepted = len(result.entries)
    closed = len(result.trades)
    open_count = int(result.metrics["open_positions_at_research_end"])
    silent_losses = accepted - closed - open_count
    negative_cash = sum(row.cash < -1e-8 for row in result.daily_equity)
    position_violations = sum(
        row.open_positions > maximum_positions for row in result.daily_equity
    )
    maximum_error = max(errors, default=0.0)
    return {
        "maximum_reconciliation_error": maximum_error,
        "minimum_cash": min((row.cash for row in result.daily_equity), default=None),
        "maximum_concurrent_positions": max(
            (row.open_positions for row in result.daily_equity), default=0
        ),
        "position_limit_violations": position_violations,
        "negative_cash_violations": negative_cash,
        "silent_position_losses": silent_losses,
        "status": "PASS" if (
            maximum_error <= 1e-8 and negative_cash == 0
            and position_violations == 0 and silent_losses == 0
        ) else "FAIL",
    }


def slippage_reconciliation(result: PortfolioSimulationResult) -> dict[str, Any]:
    entry_slippage = sum(row.entry_slippage_cost for row in result.entries)
    exit_slippage = sum(row.exit_slippage_cost for row in result.trades)
    closed_entry_slippage = sum(row.entry_slippage_cost for row in result.trades)
    closed_trade_total = sum(row.slippage_cost for row in result.trades)
    open_keys = {
        _event_key(row.security_id, row.signal_date) for row in result.entries
    } - {
        _event_key(row.security_id, row.signal_date) for row in result.trades
    }
    open_entry_slippage = sum(
        row.entry_slippage_cost for row in result.entries
        if _event_key(row.security_id, row.signal_date) in open_keys
    )
    entry_error = abs(entry_slippage - closed_entry_slippage - open_entry_slippage)
    closed_error = abs(closed_trade_total - closed_entry_slippage - exit_slippage)
    return {
        "entries": len(result.entries),
        "ordinary_exits": sum(row.lifecycle_treatment is None for row in result.trades),
        "lifecycle_exits": sum(row.lifecycle_treatment is not None for row in result.trades),
        "entry_slippage_dollars": entry_slippage,
        "exit_slippage_dollars": exit_slippage,
        "total_slippage_dollars": entry_slippage + exit_slippage,
        "closed_trade_slippage_dollars": closed_trade_total,
        "open_position_entry_slippage_dollars": open_entry_slippage,
        "maximum_reconciliation_error": max(entry_error, closed_error),
        "status": "PASS" if max(entry_error, closed_error) <= 1e-8 else "FAIL",
    }


def exposure_summary(result: PortfolioSimulationResult) -> dict[str, Any]:
    positions = [row.open_positions for row in result.daily_equity]
    sessions = len(positions)
    full = sum(value == 10 for value in positions)
    return {
        "average_positions": statistics.fmean(positions) if positions else None,
        "median_positions": statistics.median(positions) if positions else None,
        "maximum_positions": max(positions, default=0),
        "sessions_0_positions": sum(value == 0 for value in positions),
        "sessions_1_4_positions": sum(1 <= value <= 4 for value in positions),
        "sessions_5_9_positions": sum(5 <= value <= 9 for value in positions),
        "sessions_10_positions": full,
        "sessions_at_full_capacity": full,
        "pct_sessions_at_full_capacity": full / sessions if sessions else None,
        "average_cash_percentage": statistics.fmean(
            row.cash / row.total_equity for row in result.daily_equity
            if row.total_equity
        ) if result.daily_equity else None,
        "portfolio_exposure": statistics.fmean(
            row.gross_exposure for row in result.daily_equity
        ) if result.daily_equity else None,
    }


def realized_pnl_concentration(result: PortfolioSimulationResult) -> dict[str, Any]:
    ranked = sorted(result.trades, key=lambda row: row.pnl, reverse=True)
    total = sum(row.pnl for row in ranked)
    best = ranked[:10]
    worst = sorted(ranked, key=lambda row: row.pnl)[:10]

    def trade_row(row) -> dict[str, Any]:
        return {
            "security_id": row.security_id, "ticker": row.ticker,
            "entry_date": row.entry_date.isoformat(),
            "exit_date": row.exit_date.isoformat(),
            "return": row.net_return, "realized_pnl": row.pnl,
        }

    meaningful = total > 0
    best_pnl = sum(row.pnl for row in best)
    worst_pnl = sum(row.pnl for row in worst)
    best_keys = {_event_key(row.security_id, row.signal_date) for row in best}
    worst_keys = {_event_key(row.security_id, row.signal_date) for row in worst}
    return {
        "total_realized_trade_pnl": total,
        "best_10_pnl": best_pnl,
        "best_10_pct_of_total": best_pnl / total if meaningful else "NOT_MEANINGFUL",
        "worst_10_pnl": worst_pnl,
        "worst_10_pct_of_total": worst_pnl / total if meaningful else "NOT_MEANINGFUL",
        "best_trade": trade_row(ranked[0]) if ranked else None,
        "worst_trade": trade_row(ranked[-1]) if ranked else None,
        "top_bottom_overlap": len(best_keys & worst_keys),
        "status": "PASS" if not (best_keys & worst_keys) else "FAIL",
    }


def open_position_ledger(
    result: PortfolioSimulationResult,
    bars_by_security: dict[str, list[MarketBar]],
) -> dict[str, Any]:
    closed_keys = {
        _event_key(row.security_id, row.signal_date) for row in result.trades
    }
    rows = []
    for entry in result.entries:
        key = _event_key(entry.security_id, entry.signal_date)
        if key in closed_keys:
            continue
        eligible = [
            bar for bar in bars_by_security.get(entry.security_id, [])
            if bar.timestamp.date() <= result.end_date
        ]
        if not eligible:
            raise ValueError(f"open position lacks legitimate mark: {entry.security_id}")
        last = max(eligible, key=lambda bar: bar.timestamp)
        market_value = entry.quantity * last.close
        pnl = market_value - entry.position_size
        rows.append({
            "security_id": entry.security_id, "ticker": entry.ticker,
            "entry_date": entry.entry_date.isoformat(),
            "entry_price": entry.entry_price, "quantity": entry.quantity,
            "position_size": entry.position_size,
            "last_legitimate_mark_date": last.timestamp.date().isoformat(),
            "last_legitimate_mark_price": last.close,
            "market_value": market_value,
            "unrealized_return": last.close / entry.entry_price - 1,
            "unrealized_pnl": pnl,
            "scheduled_exit_date": entry.scheduled_exit_date.isoformat(),
        })
    rows.sort(key=lambda row: (row["security_id"], row["entry_date"]))
    final = result.daily_equity[-1]
    marked_value = sum(row["market_value"] for row in rows)
    return {
        "count": len(rows), "positions": rows,
        "cash": final.cash, "marked_market_value": marked_value,
        "reported_market_value": final.positions_market_value,
        "final_equity": final.total_equity,
        "market_value_reconciliation_error": abs(
            marked_value - final.positions_market_value
        ),
        "final_equity_reconciliation_error": abs(
            final.total_equity - final.cash - marked_value
        ),
        "status": "PASS" if (
            len(rows) == result.metrics["open_positions_at_research_end"]
            and abs(marked_value - final.positions_market_value) <= 1e-8
            and abs(final.total_equity - final.cash - marked_value) <= 1e-8
        ) else "FAIL",
    }


def lifecycle_ledger(
    result: PortfolioSimulationResult,
    lifecycle_by_security: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    entries = {
        _event_key(row.security_id, row.signal_date): row for row in result.entries
    }
    rows = []
    for trade in result.trades:
        if trade.lifecycle_treatment is None:
            continue
        policy = lifecycle_by_security[trade.security_id]
        entry = entries[_event_key(trade.security_id, trade.signal_date)]
        rows.append({
            "security_id": trade.security_id, "ticker": trade.ticker,
            "entry_date": trade.entry_date.isoformat(),
            "scheduled_exit_date": entry.scheduled_exit_date.isoformat(),
            "lifecycle_date": policy["lifecycle_date"],
            "category": policy["category"],
            "last_legitimate_close": trade.reference_exit_price,
            "actual_exit_date": trade.exit_date.isoformat(),
            "actual_exit_value": trade.exit_value,
            "slippage": trade.exit_slippage_cost,
            "realized_return": trade.net_return,
            "realized_pnl": trade.pnl,
            "slot_release_date": trade.slot_release_date.isoformat()
            if trade.slot_release_date else None,
        })
    return sorted(rows, key=lambda row: (row["actual_exit_date"], row["security_id"]))


def benchmark_summary(result: PortfolioSimulationResult) -> dict[str, Any]:
    total = result.benchmark_metrics.get("total_return")
    years = result.metrics.get("observation_years")
    cagr = ((1 + total) ** (1 / years) - 1
            if total is not None and years is not None and years >= 1 and 1 + total > 0
            else None)
    return {
        **result.benchmark_metrics,
        "cagr": cagr,
        "price_basis": "split-adjusted price only",
        "dividends": "excluded",
    }


def portfolio_digest(result: PortfolioSimulationResult) -> str:
    payload = result.model_dump(mode="json", exclude={"created_at"})
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def baseline_engine_equivalence(
    baseline: PortfolioSimulationResult,
    current: PortfolioSimulationResult,
    *, baseline_ordered_candidates: list[tuple[Any, ...]],
    current_ordered_candidates: list[tuple[Any, ...]],
) -> dict[str, Any]:
    """Compare canonical economics while excluding Phase 3B-only diagnostics."""
    diagnostic_reason = "SIGNAL_SKIPPED_ENTRY_OUTSIDE_RESEARCH_WINDOW"

    def selected_entries(result: PortfolioSimulationResult) -> list[dict[str, Any]]:
        return [{
            "security_id": row.security_id, "signal_date": row.signal_date.isoformat(),
            "entry_date": row.entry_date.isoformat(), "entry_price": row.entry_price,
            "position_size": row.position_size, "quantity": row.quantity,
        } for row in result.entries]

    def selected_rejections(result: PortfolioSimulationResult) -> list[dict[str, Any]]:
        return [{
            "security_id": row.security_id, "signal_date": row.signal_date.isoformat(),
            "entry_date": row.entry_date.isoformat() if row.entry_date else None,
            "reason": row.reason,
        } for row in result.skipped_signals if row.reason != diagnostic_reason]

    def selected_trades(result: PortfolioSimulationResult) -> list[dict[str, Any]]:
        return [{
            "security_id": row.security_id, "signal_date": row.signal_date.isoformat(),
            "entry_date": row.entry_date.isoformat(), "entry_price": row.entry_price,
            "position_size": row.quantity * row.entry_price,
            "exit_date": row.exit_date.isoformat(), "exit_price": row.exit_price,
            "lifecycle_treatment": row.lifecycle_treatment,
            "net_return": row.net_return, "pnl": row.pnl,
        } for row in result.trades]

    def selected_daily(result: PortfolioSimulationResult) -> list[dict[str, Any]]:
        return [{
            "session_date": row.session_date.isoformat(), "cash": row.cash,
            "market_value": row.positions_market_value, "equity": row.total_equity,
        } for row in result.daily_equity]

    checks = {
        "ordered_candidate_signals": baseline_ordered_candidates == current_ordered_candidates,
        "accepted_signals_and_entries": selected_entries(baseline) == selected_entries(current),
        "rejected_signals_and_reasons": selected_rejections(baseline) == selected_rejections(current),
        "exits_lifecycle_returns_and_pnl": selected_trades(baseline) == selected_trades(current),
        "daily_cash_market_value_and_equity": selected_daily(baseline) == selected_daily(current),
        "final_equity": (
            baseline.daily_equity[-1].total_equity == current.daily_equity[-1].total_equity
        ),
    }
    canonical = {
        "ordered_candidates": current_ordered_candidates,
        "entries": selected_entries(current), "rejections": selected_rejections(current),
        "trades": selected_trades(current), "daily": selected_daily(current),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "canonical_economic_digest": hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "phase3b_only_diagnostic_rows": sum(
            row.reason == diagnostic_reason for row in current.skipped_signals
        ),
        "baseline_final_equity": baseline.daily_equity[-1].total_equity,
        "current_final_equity": current.daily_equity[-1].total_equity,
    }


def portfolio_summary(
    result: PortfolioSimulationResult,
    *, expected_executable: int,
    bars_by_security: dict[str, list[MarketBar]],
    lifecycle_by_security: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    outcomes = classify_signal_outcomes(
        result, expected_executable=expected_executable
    )
    accounting = accounting_reconciliation(
        result, maximum_positions=int(result.configuration["maximum_positions"])
    )
    slippage = slippage_reconciliation(result)
    exposure = exposure_summary(result)
    open_positions = open_position_ledger(result, bars_by_security)
    final = result.daily_equity[-1]
    metrics = {
        **result.metrics,
        "initial_capital": result.configuration["initial_capital"],
        "final_equity": final.total_equity,
        "cash_at_end": final.cash,
        "open_position_market_value": final.positions_market_value,
        "open_positions_at_end": final.open_positions,
        "median_concurrent_positions": exposure["median_positions"],
        "maximum_concurrent_positions": exposure["maximum_positions"],
        "portfolio_exposure": exposure["portfolio_exposure"],
        "average_cash_percentage": exposure["average_cash_percentage"],
        "entry_slippage_dollars": slippage["entry_slippage_dollars"],
        "exit_slippage_dollars": slippage["exit_slippage_dollars"],
        "total_slippage_dollars": slippage["total_slippage_dollars"],
    }
    return {
        "run_id": result.run_id, "config_hash": result.config_hash,
        "digest": portfolio_digest(result), "metrics": metrics,
        "signal_outcomes": outcomes, "open_positions": open_positions,
        "lifecycle_positions": lifecycle_ledger(result, lifecycle_by_security),
        "accounting_reconciliation": accounting,
        "slippage_reconciliation": slippage,
        "exposure": exposure,
        "realized_pnl_concentration": realized_pnl_concentration(result),
        "benchmark": benchmark_summary(result),
    }
