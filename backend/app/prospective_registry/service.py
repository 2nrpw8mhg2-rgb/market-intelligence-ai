from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from app.prospective_registry.anchor import GitHubAnchor
from app.prospective_registry.generator import FrozenProspectiveSignalGenerator
from app.prospective_registry.ledger import AppendOnlyLedger
from app.prospective_registry.models import CanonicalSignalRecord, UniverseConfirmation
from app.prospective_registry.timing import ProspectiveTiming


class ProspectiveRegistryService:
    def __init__(
        self, *, generator: FrozenProspectiveSignalGenerator,
        ledger: AppendOnlyLedger | None, anchor: GitHubAnchor | None,
        code_commit: str, activation_session: date | None,
        enabled: bool, now: Callable[[], datetime] | None = None,
    ) -> None:
        self._generator = generator
        self._ledger = ledger
        self._anchor = anchor
        self._code_commit = code_commit
        self._activation_session = activation_session
        self._enabled = enabled
        self._now = now or (lambda: datetime.now(UTC))
        self._timing = ProspectiveTiming()

    async def dry_run(
        self, *, session_date: date, confirmation: UniverseConfirmation,
        data_ready_at: datetime, data_ready_evidence: str,
    ) -> dict[str, Any]:
        captured_at = self._now().astimezone(UTC)
        prepared = await self._generator.prepare(
            session_date=session_date,
            confirmation=confirmation,
            data_ready_at=data_ready_at,
            data_ready_evidence=data_ready_evidence,
            captured_at=captured_at,
        )
        status, next_open = self._timing.classify(
            session=session_date, data_ready_at=data_ready_at,
            registered_at=captured_at,
        )
        classification = (
            "RETROACTIVE"
            if self._activation_session is None or session_date < self._activation_session
            else "PROSPECTIVE_CANDIDATE"
        )
        return {
            "operation": "DRY_RUN",
            "canonical_record_created": False,
            "session_date": session_date.isoformat(),
            "status": status.value,
            "observation_classification": classification,
            "data_ready_at": data_ready_at.astimezone(UTC).isoformat(),
            "registration_timestamp": captured_at.isoformat(),
            "next_open_at": next_open.isoformat(),
            "signals": [item.model_dump(mode="json") for item in prepared.signals],
            "signal_count": len(prepared.signals),
            "input_snapshot_hash": prepared.input_snapshot_hash,
            "pit_universe_hash": prepared.pit_universe_hash,
            "parameter_hash": prepared.parameter_hash,
            "code_commit": self._code_commit,
            "scanner_summary": prepared.scanner_summary,
        }

    async def register_session(
        self, *, session_date: date, confirmation: UniverseConfirmation,
        data_ready_at: datetime, data_ready_evidence: str,
    ) -> dict[str, Any]:
        if not self._enabled:
            raise RuntimeError("canonical prospective registration is disabled")
        if self._activation_session is None or session_date < self._activation_session:
            raise RuntimeError("RETROACTIVE sessions cannot be canonically registered")
        if self._ledger is None or self._anchor is None:
            raise RuntimeError("canonical ledger and independent anchor are required")

        captured_at = self._now().astimezone(UTC)
        next_open = self._timing.next_open(session_date)
        try:
            prepared = await self._generator.prepare(
                session_date=session_date,
                confirmation=confirmation,
                data_ready_at=data_ready_at,
                data_ready_evidence=data_ready_evidence,
                captured_at=captured_at,
            )
            created_at = self._now().astimezone(UTC)
            status, next_open = self._timing.classify(
                session=session_date, data_ready_at=data_ready_at,
                registered_at=created_at,
            )
        except Exception as exc:
            failed_at = self._now().astimezone(UTC)
            failure = self._ledger.append_failure(
                session_date=session_date,
                created_at=failed_at.isoformat(),
                data_ready_at=data_ready_at.astimezone(UTC).isoformat(),
                next_open_at=next_open.isoformat(),
                code_commit=self._code_commit,
                failure_stage="PREPARE_OR_READINESS",
                error=str(exc) or type(exc).__name__,
            )
            receipt = self._anchor.anchor(failure, next_open_at=next_open)
            self._ledger.append_anchor_receipt(receipt.model_dump(mode="json"))
            raise RuntimeError("prospective registration failed closed; failure was recorded") from exc
        payload = {
            "record_type": "SIGNAL",
            "registry_schema_version": "1.0",
            "session_date": session_date.isoformat(),
            "data_ready_at": data_ready_at.astimezone(UTC).isoformat(),
            "data_ready_evidence": data_ready_evidence,
            "created_at": created_at.isoformat(),
            "next_open_at": next_open.isoformat(),
            "status": status.value,
            "observation_classification": "PROSPECTIVE_CANDIDATE",
            "strategy_id": "BREAKOUT_20D_VOLUME",
            "signals": [item.model_dump(mode="json") for item in prepared.signals],
            "input_snapshot_hash": prepared.input_snapshot_hash,
            "pit_universe_hash": prepared.pit_universe_hash,
            "parameter_hash": prepared.parameter_hash,
            "code_commit": self._code_commit,
        }
        entry = self._ledger.append(payload, session_date=session_date)
        CanonicalSignalRecord.model_validate(entry)
        receipt = self._anchor.anchor(entry, next_open_at=next_open)
        self._ledger.append_anchor_receipt(receipt.model_dump(mode="json"))
        independently_timely = (
            entry["status"] == "TIMELY"
            and receipt.status.value == "TIMELY"
            and receipt.independent_timing_verified
        )
        return {
            "session_date": session_date.isoformat(),
            "status": entry["status"],
            "independently_anchored_timely": independently_timely,
            "holdout_qualification": (
                "QUALIFIED" if independently_timely else "NOT_INDEPENDENTLY_TIMESTAMPED"
            ),
            "record_hash": entry["current_record_hash"],
            "anchor": receipt.model_dump(mode="json"),
            "signal_count": len(prepared.signals),
        }

    def append_correction(
        self, *, supersedes_record_hash: str, reason: str,
        corrected_payload: dict[str, Any], created_at: datetime,
    ) -> dict[str, Any]:
        if not self._enabled or self._ledger is None or self._anchor is None:
            raise RuntimeError("canonical prospective registration is disabled")
        if created_at.tzinfo is None:
            raise ValueError("correction timestamp must be timezone-aware")
        target = next(
            (
                row for row in self._ledger.entries()
                if row.get("current_record_hash") == supersedes_record_hash
            ),
            None,
        )
        if target is None or "next_open_at" not in target:
            raise ValueError("correction target lacks canonical timing context")
        entry = self._ledger.append_correction(
            supersedes_record_hash=supersedes_record_hash,
            reason=reason,
            corrected_payload=corrected_payload,
            created_at=created_at.astimezone(UTC).isoformat(),
        )
        next_open = datetime.fromisoformat(target["next_open_at"])
        receipt = self._anchor.anchor(entry, next_open_at=next_open)
        self._ledger.append_anchor_receipt(receipt.model_dump(mode="json"))
        return {
            "status": "CORRECTION_RECORDED",
            "record_hash": entry["current_record_hash"],
            "supersedes_record_hash": supersedes_record_hash,
            "anchor": receipt.model_dump(mode="json"),
        }
