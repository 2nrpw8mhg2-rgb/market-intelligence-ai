import csv
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.pit.universe_validation import PITMembership, validate_universe
from app.schemas.universe import MembershipImportRecord
from app.eodhd.client import EODHDClient
from app.eodhd.models import EODBar


@dataclass(frozen=True)
class AliasLedgerEntry:
    historical_ticker: str
    security_id: str
    valid_from: str
    valid_to: str
    company_security_name: str
    figi: str
    isin: str
    cik: str
    provider_symbol: str
    source: str
    source_confidence: str
    provenance: str
    resolution_status: str
    resolution_reason: str


def build_materialization_records(
    audit: dict[str, Any], exceptions: dict[str, Any],
    start: date, end: date, identity_evidence: dict[str, Any] | None = None,
) -> tuple[list[MembershipImportRecord], list[AliasLedgerEntry]]:
    identity_evidence = identity_evidence or {}
    records: list[MembershipImportRecord] = []
    ledger: list[AliasLedgerEntry] = []
    for row in audit["security_master"]:
        membership = row["membership"]
        valid_from = date.fromisoformat(str(
            membership.get("start") or membership.get("first_assertable_membership")
        ))
        valid_to = date.fromisoformat(str(membership["end"])) if membership.get("end") else None
        if valid_from > end or (valid_to is not None and valid_to <= start):
            continue
        source_security_id = str(row["security_id"])
        correction = identity_evidence.get(source_security_id, {}).get("replacement_identity")
        identity = row["identity"]
        if correction:
            security_id = str(correction["security_id"])
            ticker = str(correction["ticker"])
            security_name = str(correction["name"])
            identity = {
                "confidence": correction["confidence"],
                "provider_symbol": correction["provider_symbol"],
                "identifiers": correction["identifiers"],
                "evidence": identity_evidence[source_security_id]["evidence"],
                "symbol_changes": [],
            }
        else:
            security_id = source_security_id
            ticker = str(membership["ticker"])
            security_name = str(row.get("canonical_name") or "")
        identifiers = {str(key): str(value) for key, value in identity.get("identifiers", {}).items() if value}
        exception = exceptions.get(security_id)
        confidence = str(identity.get("confidence") or "UNRESOLVED")
        if exception and exception.get("classification") == "EXPLICITLY_NON_TRADABLE_OR_INVALID":
            eligibility = "EXPLICITLY_NON_TRADABLE_OR_INVALID"
            resolution = "NON_TRADABLE"
            reason = str(exception["evidence"])
        elif confidence in {"HIGH", "MEDIUM"} and identifiers and identity.get("provider_symbol"):
            eligibility = "ELIGIBLE"
            resolution = "RESOLVED"
            reason = "stable identifiers and provider identity preserved by validated POC3 security master"
        else:
            eligibility = "UNRESOLVED"
            resolution = "UNRESOLVED"
            reason = "stable identity or provider symbol is insufficient"
        provenance = {
            "dataset": "EODHD POC3 validated security master",
            "membership_source": "HistoricalTickerComponents",
            "provider_symbol": identity.get("provider_symbol"),
            "identifiers": identifiers,
            "identity_evidence": identity.get("evidence", []),
            "symbol_changes": identity.get("symbol_changes", []),
            "exception": exception,
            "source_security_id": source_security_id,
            "identity_correction": identity_evidence.get(source_security_id) if correction else None,
        }
        records.append(MembershipImportRecord(
            security_id=security_id, ticker=ticker,
            security_name=security_name or None,
            valid_from=valid_from, valid_to=valid_to,
            source="EODHD HistoricalTickerComponents / POC3 validated",
            source_confidence=confidence if confidence in {"HIGH", "MEDIUM", "LOW"} else "UNRESOLVED",
            provenance=provenance, eligibility_status=eligibility,
        ))
        ledger.append(AliasLedgerEntry(
            historical_ticker=ticker, security_id=security_id,
            valid_from=valid_from.isoformat(), valid_to=valid_to.isoformat() if valid_to else "",
            company_security_name=security_name,
            figi=identifiers.get("OpenFigi", ""), isin=identifiers.get("ISIN", ""),
            cik=identifiers.get("CIK", ""), provider_symbol=str(identity.get("provider_symbol") or ""),
            source="EODHD HistoricalTickerComponents / POC3 validated",
            source_confidence=confidence, provenance=json.dumps(provenance, sort_keys=True),
            resolution_status=resolution, resolution_reason=reason,
        ))
        if correction:
            original_identity = row["identity"]
            original_identifiers = {
                str(key): str(value) for key, value in original_identity.get("identifiers", {}).items()
                if value
            }
            audit_provenance = {
                "dataset": "EODHD POC3 validated security master",
                "membership_source": "HistoricalTickerComponents provider misidentification",
                "provider_symbol": original_identity.get("provider_symbol"),
                "identifiers": original_identifiers,
                "identity_evidence": original_identity.get("evidence", []),
                "superseded_identity_evidence": identity_evidence[source_security_id]["evidence"],
                "replacement_security_id": security_id,
            }
            records.append(MembershipImportRecord(
                security_id=source_security_id,
                ticker=str(membership["ticker"]),
                security_name=str(row.get("canonical_name") or "") or None,
                valid_from=valid_from,
                valid_to=valid_to,
                source="EODHD HistoricalTickerComponents / POC3 validated",
                source_confidence=str(original_identity.get("confidence") or "UNRESOLVED"),
                provenance=audit_provenance,
                eligibility_status="EXPLICITLY_NON_TRADABLE_OR_INVALID",
            ))
            ledger.append(AliasLedgerEntry(
                historical_ticker=str(membership["ticker"]),
                security_id=source_security_id,
                valid_from=valid_from.isoformat(),
                valid_to=valid_to.isoformat() if valid_to else "",
                company_security_name=str(row.get("canonical_name") or ""),
                figi=original_identifiers.get("OpenFigi", ""),
                isin=original_identifiers.get("ISIN", ""),
                cik=original_identifiers.get("CIK", ""),
                provider_symbol=str(original_identity.get("provider_symbol") or ""),
                source="EODHD HistoricalTickerComponents / POC3 validated",
                source_confidence=str(original_identity.get("confidence") or "UNRESOLVED"),
                provenance=json.dumps(audit_provenance, sort_keys=True),
                resolution_status="NON_TRADABLE",
                resolution_reason="provider identity superseded; retained for audit only",
            ))
    return records, sorted(ledger, key=lambda item: (item.historical_ticker, item.valid_from, item.security_id))


def database_validation(records: list[MembershipImportRecord], sessions: list[date]):
    pit = [PITMembership(
        security_id=str(item.security_id), ticker=item.ticker,
        name=item.security_name or "", valid_from=item.valid_from, valid_to=item.valid_to,
        identifiers=tuple(sorted((str(k), str(v)) for k, v in item.provenance.get("identifiers", {}).items())),
        identity_confidence=item.source_confidence,
        reuse_status="NO_REUSE_EVIDENCE",
        symbol_changes=tuple(), provenance=json.dumps(item.provenance, sort_keys=True),
        eligibility_status=item.eligibility_status,
        exclusion_evidence=(item.provenance.get("exception") or {}).get("evidence"),
    ) for item in records]
    return validate_universe(pit, sessions)


def write_ledger(path: Path, rows: list[AliasLedgerEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(asdict(rows[0]).keys()), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)


def cached_eodhd_bars(cache_dir: Path, provider_symbol: str) -> list[EODBar]:
    path = "eod/" + f"{provider_symbol}.US".upper()
    key = EODHDClient._cache_key(path, {"period": "d", "order": "a", "fmt": "json"})
    cache_file = cache_dir / f"{key}.json"
    if not cache_file.exists():
        raise FileNotFoundError(f"validated EODHD cache missing for provider symbol {provider_symbol}")
    return [EODBar.model_validate(item) for item in json.loads(cache_file.read_text())]
