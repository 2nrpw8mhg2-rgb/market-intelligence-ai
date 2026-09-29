import json
from datetime import date

from app.pit.materialization import build_materialization_records, database_validation
from app.database.repositories import PITIdentityResolutionError


def row(*, security_id="00000000-0000-0000-0000-000000000001", ticker="ABC",
        start="2020-01-01", end=None, confidence="HIGH", identifiers=None,
        provider_symbol="ABC"):
    return {
        "security_id": security_id, "canonical_name": "Example Inc",
        "membership": {"ticker": ticker, "start": start, "end": end},
        "identity": {"confidence": confidence, "provider_symbol": provider_symbol,
                     "identifiers": identifiers if identifiers is not None else {"OpenFigi": "FIGI1"},
                     "evidence": ["fixture"], "symbol_changes": []},
    }


def test_materialization_preserves_security_identity_and_hash_is_deterministic() -> None:
    records, ledger = build_materialization_records(
        {"security_master": [row()]}, {}, date(2021, 1, 1), date(2022, 1, 1)
    )
    assert str(records[0].security_id) == ledger[0].security_id
    assert records[0].provenance["identifiers"]["OpenFigi"] == "FIGI1"
    sessions = [date(2021, 1, 4), date(2021, 1, 5)]
    assert database_validation(records, sessions).deterministic_hash == database_validation(records, sessions).deterministic_hash


def test_unresolved_identity_fails_closed() -> None:
    records, ledger = build_materialization_records(
        {"security_master": [row(confidence="LOW", identifiers={})]}, {},
        date(2021, 1, 1), date(2022, 1, 1),
    )
    assert records[0].eligibility_status == "UNRESOLVED"
    assert ledger[0].resolution_status == "UNRESOLVED"


def test_explicit_non_tradable_is_preserved_and_excluded() -> None:
    security_id = "00000000-0000-0000-0000-000000000001"
    records, ledger = build_materialization_records(
        {"security_master": [row(security_id=security_id)]},
        {security_id: {"classification": "EXPLICITLY_NON_TRADABLE_OR_INVALID", "evidence": "official evidence"}},
        date(2021, 1, 1), date(2022, 1, 1),
    )
    assert records[0].eligibility_status == "EXPLICITLY_NON_TRADABLE_OR_INVALID"
    assert ledger[0].resolution_status == "NON_TRADABLE"
    validation = database_validation(records, [date(2021, 1, 4)])
    assert validation.snapshots[0].members == ()
    assert not validation.anomalies[0]["blocking"]


def test_corrected_identity_is_distinct_and_source_identity_is_audit_only() -> None:
    old_id = "00000000-0000-0000-0000-000000000001"
    new_id = "00000000-0000-0000-0000-000000000002"
    evidence = {old_id: {
        "evidence": "authoritative correction",
        "replacement_identity": {
            "security_id": new_id, "ticker": "NEW", "name": "New Security",
            "provider_symbol": "NEW", "confidence": "HIGH",
            "identifiers": {"ISIN": "US0000000002"},
        },
    }}
    records, ledger = build_materialization_records(
        {"security_master": [row(security_id=old_id, ticker="OLD")]}, {},
        date(2021, 1, 1), date(2022, 1, 1), evidence,
    )
    by_id = {str(item.security_id): item for item in records}
    assert by_id[new_id].ticker == "NEW"
    assert by_id[new_id].eligibility_status == "ELIGIBLE"
    assert by_id[old_id].ticker == "OLD"
    assert by_id[old_id].eligibility_status == "EXPLICITLY_NON_TRADABLE_OR_INVALID"
    assert {item.resolution_status for item in ledger} == {"RESOLVED", "NON_TRADABLE"}
