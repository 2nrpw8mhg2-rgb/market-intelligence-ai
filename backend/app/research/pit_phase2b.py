import hashlib
import json
from collections import Counter
from datetime import date
from typing import Any, Callable, Iterable


STRATEGY_TOTAL_OBSERVATIONS = 200
STRATEGY_PRIOR_OBSERVATIONS = STRATEGY_TOTAL_OBSERVATIONS - 1
PREHISTORY_CLASSES = (
    "SUFFICIENT_PRE_MEMBERSHIP_HISTORY",
    "NATURAL_SHORT_PREHISTORY_EVIDENCED",
    "INSUFFICIENT_PRE_MEMBERSHIP_HISTORY",
    "UNKNOWN_PREHISTORY",
)
NATURAL_LISTING_EVENTS = {
    "IPO", "DIRECT_LISTING", "SPINOFF", "NEW_SECURITY", "NEW_SHARE_CLASS",
    "OTHER_EVIDENCED_LISTING_EVENT",
}


def parse_date(value: str | date | None) -> date | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def validate_boundary_evidence(payload: dict[str, Any]) -> None:
    """Reject unsupported listing, lifecycle, and documentation assertions."""
    for security_id, item in payload.get("listing_events", {}).items():
        if item.get("event_type") not in NATURAL_LISTING_EVENTS:
            raise ValueError(f"unsupported listing event for {security_id}")
        first = parse_date(item.get("first_legitimate_trading_date"))
        if first is None or item.get("confidence") != "HIGH" or not item.get("sources"):
            raise ValueError(f"listing evidence is not auditable for {security_id}")
    for security_id, item in payload.get("lifecycle_events", {}).items():
        last = parse_date(item.get("last_regular_trading_date"))
        closing = parse_date(item.get("closing_date"))
        if last is None or closing is None or last > closing:
            raise ValueError(f"invalid lifecycle chronology for {security_id}")
        if item.get("confidence") != "HIGH" or not item.get("sources"):
            raise ValueError(f"lifecycle evidence is not auditable for {security_id}")
    for security_id, item in payload.get("documentation_gaps", {}).items():
        required = {
            "unresolved_fact", "authoritative_evidence_unavailable_reason",
            "research_invariance_reason",
        }
        if not required <= set(item):
            raise ValueError(f"documentation gap is incomplete for {security_id}")


def exact_strategy_warmup() -> dict[str, Any]:
    """Binding warm-up derived from FeatureEngine, not a calendar-day estimate."""
    return {
        "total_observations_through_evaluation_session": STRATEGY_TOTAL_OBSERVATIONS,
        "strictly_prior_observations": STRATEGY_PRIOR_OBSERVATIONS,
        "binding_feature": "SMA_200",
        "other_inputs": {
            "PREVIOUS_HIGH_20D": 20,
            "AVG_VOLUME_20D": 20,
            "AVG_DOLLAR_VOLUME_20D": 20,
            "SMA_50": 50,
            "MOMENTUM_20D": 20,
        },
        "interpretation": (
            "The evaluation session supplies observation 200 for SMA_200; "
            "therefore 199 legitimate prior observations are required."
        ),
    }


def classify_pre_membership_history(
    *, security_id: str, valid_from: date, logical_bar_dates: Iterable[date],
    listing_evidence: dict[str, dict[str, Any]],
    logical_history_identity_valid: bool = True,
) -> dict[str, Any]:
    dates = sorted(set(logical_bar_dates)) if logical_history_identity_valid else []
    prior = [item for item in dates if item < valid_from]
    earliest = dates[STRATEGY_TOTAL_OBSERVATIONS - 1] if len(dates) >= STRATEGY_TOTAL_OBSERVATIONS else None
    evidence = listing_evidence.get(security_id)
    first_legitimate = parse_date(evidence.get("first_legitimate_trading_date")) if evidence else None

    if len(prior) >= STRATEGY_PRIOR_OBSERVATIONS:
        classification = "SUFFICIENT_PRE_MEMBERSHIP_HISTORY"
    elif evidence is not None:
        if evidence.get("event_type") not in NATURAL_LISTING_EVENTS or first_legitimate is None:
            classification = "UNKNOWN_PREHISTORY"
        elif first_legitimate > valid_from:
            classification = "UNKNOWN_PREHISTORY"
        else:
            classification = "NATURAL_SHORT_PREHISTORY_EVIDENCED"
    elif dates:
        classification = "INSUFFICIENT_PRE_MEMBERSHIP_HISTORY"
    else:
        classification = "UNKNOWN_PREHISTORY"

    return {
        "classification": classification,
        "first_legitimate_trading_date": first_legitimate.isoformat() if first_legitimate else None,
        "first_logical_bar_currently_available": dates[0].isoformat() if dates else None,
        "legitimate_observations_before_valid_from": len(prior),
        "exact_strategy_warmup_prior_observations": STRATEGY_PRIOR_OBSERVATIONS,
        "earliest_all_indicators_causally_computable": earliest.isoformat() if earliest else None,
        "full_warmup_at_valid_from": len(prior) >= STRATEGY_PRIOR_OBSERVATIONS,
        "event_type": evidence.get("event_type") if evidence else None,
        "evidence": evidence.get("sources", []) if evidence else [],
        "logical_history_identity_valid": logical_history_identity_valid,
    }


def membership_allows_signal(when: date, valid_from: date, valid_to: date | None) -> bool:
    """Membership is half-open and controls signal eligibility only."""
    return valid_from <= when and (valid_to is None or when < valid_to)


def split_symmetric_history(
    bar_dates: Iterable[date], *, valid_from: date, valid_to: date | None,
) -> dict[str, list[date]]:
    """Preserve price history on both sides; only eligibility is interval-bound."""
    before, during, after = [], [], []
    for when in sorted(set(bar_dates)):
        if when < valid_from:
            before.append(when)
        elif valid_to is None or when < valid_to:
            during.append(when)
        else:
            after.append(when)
    return {
        "PRE_MEMBERSHIP_HISTORY": before,
        "MEMBERSHIP_ELIGIBILITY": during,
        "POST_MEMBERSHIP_FORWARD_HISTORY": after,
    }


def prove_non_blocking_documentation_gap(
    *, security_id: str, signal_dates: Iterable[date], feature_history_complete: bool,
    next_open_invariant: bool, forward_horizons_invariant: bool,
    evidence: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    item = evidence.get(security_id)
    dates = sorted(set(signal_dates))
    proven = bool(
        item and feature_history_complete and next_open_invariant
        and forward_horizons_invariant and not dates
    )
    return {
        "security_id": security_id,
        "classification": (
            "NON_BLOCKING_DOCUMENTATION_GAP" if proven else "BLOCKING_RESEARCH_GAP"
        ),
        "unresolved_fact": item.get("unresolved_fact") if item else None,
        "why_authoritative_evidence_remains_unavailable": (
            item.get("authoritative_evidence_unavailable_reason") if item else None
        ),
        "pit_signal_count": len(dates),
        "affected_signal_dates": [item.isoformat() for item in dates],
        "any_feature_could_change": not feature_history_complete,
        "any_next_open_could_change": not next_open_invariant,
        "any_forward_horizon_could_change": not forward_horizons_invariant,
        "financial_results_invariance": (
            item.get("research_invariance_reason") if proven else None
        ),
    }


def summarize_prehistory(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(row["classification"]) for row in rows)
    return {key: counts[key] for key in PREHISTORY_CLASSES}


def deterministic_audit_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
