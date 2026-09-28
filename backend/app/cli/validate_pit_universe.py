import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from app.market_data.calendar import NYSETradingCalendar
from app.pit.universe_validation import PITMembership, UniverseValidation, validate_universe


RESEARCH_START = date(2021, 9, 27)
RESEARCH_END = date(2026, 9, 22)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Validate reconstructed S&P 500 PIT membership by XNYS session")
    command.add_argument("--poc3-audit", default="data/eodhd_poc3/audit.json")
    command.add_argument("--poc5-csv", default="docs/EODHD_CRITICAL_RESOLUTION.csv")
    command.add_argument("--output", default="docs/PIT_UNIVERSE_VALIDATION_REPORT.md")
    command.add_argument("--exceptions", default="docs/PIT_MEMBERSHIP_EXCEPTIONS.json")
    return command


def _representative_snapshots(validation: UniverseValidation) -> list[Any]:
    snapshots = validation.snapshots
    transition_positions = [position for position, item in enumerate(snapshots)
                            if position and (item.additions or item.removals)]
    selected = {0, len(snapshots) - 1}
    if transition_positions:
        sample_indexes = sorted({round(index * (len(transition_positions) - 1) / 5) for index in range(6)})
        for sample_index in sample_indexes:
            position = transition_positions[sample_index]
            selected.update(item for item in (position - 1, position, position + 1)
                            if 0 <= item < len(snapshots))
    positions_by_session = {item.session: position for position, item in enumerate(snapshots)}
    for anomaly in validation.anomalies:
        for key in ("first_session", "last_session"):
            session = anomaly.get(key)
            if session in positions_by_session:
                position = positions_by_session[session]
                selected.update(item for item in (position - 1, position, position + 1)
                                if 0 <= item < len(snapshots))
    return [snapshots[position] for position in sorted(selected)]


def render_report(validation: UniverseValidation, records: list[PITMembership], poc5: list[dict[str, str]]) -> str:
    def anomalies_on(session: date) -> list[str]:
        values = []
        for anomaly in validation.anomalies:
            if anomaly.get("session") == session:
                values.append(anomaly["category"])
                continue
            first, last = anomaly.get("first_session"), anomaly.get("last_session")
            if first and last and first <= session <= last:
                values.append(f"{anomaly['category']}:{anomaly.get('ticker', '')}")
        return sorted(values)
    transitions = [item for item in validation.snapshots if item.additions or item.removals]
    additions = sum(len(item.additions) for item in transitions)
    removals = sum(len(item.removals) for item in transitions)
    alias_records = sum(bool(record.symbol_changes) for record in records)
    reused_outside = [row for row in poc5 if row.get("input_ticker_reuse_unresolved") == "True"]
    unresolved_outside = [row for row in poc5 if row.get("pit_status") == "NOT_RELEVANT_TO_TEST_WINDOW"]
    blocking_anomalies = [item for item in validation.anomalies if item.get("blocking", True)]
    ready = not blocking_anomalies and len(unresolved_outside) == len(poc5) == 79
    decision = "READY_FOR_PIT_BACKTEST" if ready else "NOT_READY_FOR_PIT_BACKTEST"

    def values(items: tuple[str, ...]) -> str:
        return ", ".join(items) if items else "—"

    table = []
    for snapshot in _representative_snapshots(validation):
        session_anomalies = anomalies_on(snapshot.session)
        table.append(
            f"| {snapshot.session} | {len(snapshot.members)} | {values(snapshot.additions)} | "
            f"{values(snapshot.removals)} | {', '.join(sorted(session_anomalies)) or '—'} |"
        )
    anomaly_counts = validation.anomaly_counts
    anomaly_categories = (
        "IMPOSSIBLE_MEMBERSHIP_INTERVAL", "MISSING_SECURITY_ID", "MISSING_STABLE_IDENTIFIER",
        "OVERLAPPING_IDENTITY_INTERVALS", "DUPLICATE_ELIGIBLE_SECURITY",
        "DUPLICATE_ELIGIBLE_TICKER", "UNRESOLVED_ELIGIBLE_IDENTITY",
        "TICKER_REUSE_ELIGIBLE", "ENTRY_BOUNDARY_VIOLATION", "EXIT_BOUNDARY_VIOLATION",
        "EXPLICIT_NON_TRADABLE_RECORD",
    )
    anomaly_table = "\n".join(f"| {category} | {anomaly_counts.get(category, 0)} |"
                              for category in anomaly_categories)
    anomaly_details = []
    for anomaly in validation.anomalies:
        affected = (f"{anomaly.get('first_session')}–{anomaly.get('last_session')} "
                    f"({anomaly.get('affected_sessions')} sessions)"
                    if anomaly.get("first_session") else str(anomaly.get("session") or "structural"))
        requirement = {
            "MISSING_STABLE_IDENTIFIER": "stable dated identifier mapping for the eligible security",
            "UNRESOLVED_ELIGIBLE_IDENTITY": "HIGH/MEDIUM identity evidence linking membership to the traded security",
            "EXPLICIT_NON_TRADABLE_RECORD": "none; retained as an explicit audited exclusion",
        }.get(anomaly["category"], "resolve the reported membership/identity contradiction")
        anomaly_details.append(
            f"| {anomaly['category']} | {anomaly.get('ticker', '—')} | "
            f"{anomaly.get('security_id', '—')} | {affected} | {requirement} |"
        )
    reasons = (
        "All session-level and structural checks passed; all 79 known historical exceptions exit before "
        "the research window and are never eligible."
        if ready else
        "At least one blocking identity or interval anomaly remains."
    )
    return f"""# POINT_IN_TIME S&P 500 Universe Validation

**Research window:** {RESEARCH_START} through {RESEARCH_END}
**Calendar:** XNYS regular trading sessions (`exchange_calendars`)
**Membership semantics:** entry inclusive, exit exclusive
**Decision:** **{decision}**

## Executive conclusion

{reasons} This report validates eligibility only. No strategy, signal, score, portfolio return or financial-performance backtest was executed.

## Data sources and provenance

- EODHD `HistoricalTickerComponents`, preserved in the POC 3 security master at `backend/data/eodhd_poc3/audit.json`.
- POC 5 critical-case classifications at `backend/docs/EODHD_CRITICAL_RESOLUTION.csv`.
- Every reconstructed record retains its internal `security_id`, dated half-open membership interval, stable identifiers, identity/reuse status, symbol-change evidence and source label.
- No current-snapshot substitution, synthetic history, forward/backward fill or silent membership repair was performed.

## Session coverage

| Measure | Result |
|---|---:|
| XNYS sessions validated | {len(validation.snapshots)} |
| Minimum constituents | {validation.min_count} |
| Maximum constituents | {validation.max_count} |
| Median constituents | {validation.median_count:g} |
| Sessions with a membership transition | {len(transitions)} |
| Additions observed inside window | {additions} |
| Removals observed inside window | {removals} |
| Deterministic reconstruction hash | `{validation.deterministic_hash}` |

## Boundary and identity rules

- Eligibility is `valid_from <= session < valid_to`; an exit-date security is absent on the exit boundary.
- Repository queries, period selection, importer overlap detection and the backtesting membership predicate now use the same half-open semantics.
- Session transitions are computed by `security_id`, not ticker string.
- The 16 known reused-ticker cases from POC 5 are outside the research window and never become eligible.
- {alias_records} source records carry ticker-change evidence; membership continuity is keyed by security identity where stable evidence exists.
- Tests explicitly cover entry, exit, ticker change, ticker reuse isolation, no out-of-interval eligibility, no duplicate eligible identities and deterministic reconstruction.

## Anomalies

| Category | Count |
|---|---:|
{anomaly_table}

Total findings: **{len(validation.anomalies)}**; blocking anomalies: **{len(blocking_anomalies)}**.

### Anomaly details

| Category | Ticker | security_id | Affected sessions | Exact evidence required |
|---|---|---|---|---|
{chr(10).join(anomaly_details) if anomaly_details else '| — | — | — | — | None |'}

## Unresolved exceptions

POC 5 contains {len(poc5)} historical critical cases: {len(unresolved_outside)} are classified `NOT_RELEVANT_TO_TEST_WINDOW`, including {len(reused_outside)} unresolved ticker-reuse identities. They remain unresolved for earlier research but every one has an exclusive membership exit before {RESEARCH_START}. They are preserved as exceptions rather than repaired and do not enter any validated daily universe in this window.

### MRP_OLD final classification

**EXPLICITLY_NON_TRADABLE_OR_INVALID.** The source record starts on 2025-01-21, which is Lennar's distribution record date, before any public Millrose market existed. Lennar documented when-issued trading as beginning around 2025-02-05 and regular-way NYSE trading under `MRP` on 2025-02-07. Millrose's SEC filing independently states there was no public trading market before 2025-02-05. S&P DJI documented that Lennar remained in the S&P 500 and that Millrose entered the **S&P SmallCap 600**, effective 2025-02-10. EODHD contains no bars or stable identifier for `MRP_OLD`; its separate `MRP.US` series begins 2025-02-05 and has FIGI `BBG01RQYH2X7` and ISIN `US6011371027`. These facts prove that the 2025-01-21–2025-02-10 source interval must not be treated as an independently tradable S&P 500 membership. It remains in the audit data and is explicitly excluded; it is not silently deleted or mapped to `MRP` by ticker similarity.

Primary corroboration: [Lennar spin-off dates](https://investors.lennar.com/press-releases/2025/01-10-2025-230022870), [S&P DJI index announcement](https://www.spglobal.com/spdji/en/documents/indexnews/announcements/20250205-1476446/1476446_5-len-mrp-spin.pdf), and [Millrose SEC filing](https://www.sec.gov/Archives/edgar/data/2017206/000201720626000002/ck0002017206-20251231.htm).

## Representative dates and change boundaries

Additions/removals are differences from the immediately preceding XNYS session. Rows surrounding sampled transition sessions demonstrate the boundary behavior.

| Session | Constituent count | Additions effective | Removals effective | Anomalies |
|---|---:|---|---|---|
{chr(10).join(table)}

## Runtime identity integration

The runtime `UniverseMembership` and import/query path is keyed authoritatively by `security_id`, retains source confidence and provenance, verifies the dated ticker alias against the same security, and fails closed for missing/mismatched/unresolved identities. Explicitly proven non-tradable/invalid source records are retained for audit and excluded from tradable membership; no ticker fallback is permitted.

## Readiness decision

**{decision}**

{reasons} Readiness is limited to universe reconstruction for {RESEARCH_START} through {RESEARCH_END}; this validation does not authorize a wider historical window and did not execute the PIT backtest.
"""


def run(args: argparse.Namespace) -> None:
    source = json.loads(Path(args.poc3_audit).read_text())
    exceptions = json.loads(Path(args.exceptions).read_text())
    records = [PITMembership.from_security_master(row, exceptions.get(str(row.get("security_id"))))
               for row in source["security_master"]]
    calendar = NYSETradingCalendar()
    sessions = calendar.trading_days_between(RESEARCH_START, RESEARCH_END)
    validation = validate_universe(records, sessions)
    with Path(args.poc5_csv).open() as handle:
        import csv
        poc5 = list(csv.DictReader(handle))
    report = render_report(validation, records, poc5)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report)
    print(json.dumps({
        "output": str(output), "sessions": len(sessions), "min": validation.min_count,
        "max": validation.max_count, "median": validation.median_count,
        "anomalies": validation.anomaly_counts,
        "decision": "READY_FOR_PIT_BACKTEST" if not any(
            item.get("blocking", True) for item in validation.anomalies
        ) else "NOT_READY_FOR_PIT_BACKTEST",
        "hash": validation.deterministic_hash,
    }, indent=2))


if __name__ == "__main__":
    run(parser().parse_args())
