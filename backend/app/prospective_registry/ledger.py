import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from app.prospective_registry.canonical import canonical_hash, canonical_json


class DuplicateRegistrationError(RuntimeError):
    pass


class LedgerVerificationError(RuntimeError):
    pass


class AppendOnlyLedger:
    """One immutable file per record with a deterministic SHA-256 hash chain."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.records = root / "records"
        self.head_path = root / "head.json"

    def _paths(self) -> list[Path]:
        if not self.records.exists():
            return []
        return sorted(self.records.glob("*.json"))

    def entries(self) -> list[dict[str, Any]]:
        return [json.loads(path.read_text(encoding="utf-8")) for path in self._paths()]

    def append(self, payload: dict[str, Any], *, session_date: date) -> dict[str, Any]:
        self.records.mkdir(parents=True, exist_ok=True, mode=0o700)
        existing = self.entries()
        for entry in existing:
            if entry.get("record_type") != "SIGNAL":
                continue
            if entry.get("session_date") != session_date.isoformat():
                continue
            comparison = dict(entry)
            comparison.pop("sequence", None)
            comparison.pop("previous_record_hash", None)
            comparison.pop("current_record_hash", None)
            stable_comparison = dict(comparison)
            stable_payload = dict(payload)
            for key in ("created_at", "status"):
                stable_comparison.pop(key, None)
                stable_payload.pop(key, None)
            if stable_comparison == stable_payload:
                return entry
            raise DuplicateRegistrationError(
                f"session {session_date} already has a different canonical record"
            )

        previous_hash = existing[-1]["current_record_hash"] if existing else None
        entry = {
            **payload,
            "sequence": len(existing) + 1,
            "previous_record_hash": previous_hash,
        }
        entry["current_record_hash"] = canonical_hash(entry)
        filename = f"{entry['sequence']:08d}-{entry['current_record_hash']}.json"
        path = self.records / filename
        self._exclusive_write(path, canonical_json(entry))
        self._sync_directory(self.records)
        self._write_head(entry)
        return entry

    def append_anchor_receipt(self, receipt: dict[str, Any]) -> dict[str, Any]:
        self.records.mkdir(parents=True, exist_ok=True, mode=0o700)
        existing = self.entries()
        for entry in existing:
            if entry.get("record_type") != "ANCHOR_RECEIPT":
                continue
            if all(entry.get(key) == receipt.get(key) for key in (
                "record_hash", "remote_commit_sha", "remote_name", "status", "error",
            )):
                return entry
        previous_hash = existing[-1]["current_record_hash"] if existing else None
        entry = {
            "record_type": "ANCHOR_RECEIPT",
            **receipt,
            "sequence": len(existing) + 1,
            "previous_record_hash": previous_hash,
        }
        entry["current_record_hash"] = canonical_hash(entry)
        filename = f"{entry['sequence']:08d}-{entry['current_record_hash']}.json"
        self._exclusive_write(self.records / filename, canonical_json(entry))
        self._sync_directory(self.records)
        self._write_head(entry)
        return entry

    def append_failure(
        self, *, session_date: date, created_at: str, data_ready_at: str,
        next_open_at: str, code_commit: str, failure_stage: str, error: str,
    ) -> dict[str, Any]:
        existing = self.entries()
        for entry in existing:
            if (
                entry.get("record_type") == "FAILURE"
                and entry.get("session_date") == session_date.isoformat()
                and entry.get("failure_stage") == failure_stage
                and entry.get("error") == error.replace("\n", " ")[:300]
            ):
                return entry
        previous_hash = existing[-1]["current_record_hash"] if existing else None
        entry = {
            "record_type": "FAILURE",
            "registry_schema_version": "1.0",
            "sequence": len(existing) + 1,
            "session_date": session_date.isoformat(),
            "created_at": created_at,
            "data_ready_at": data_ready_at,
            "next_open_at": next_open_at,
            "status": "FAILED",
            "code_commit": code_commit,
            "failure_stage": failure_stage,
            "error": error.replace("\n", " ")[:300],
            "previous_record_hash": previous_hash,
        }
        entry["current_record_hash"] = canonical_hash(entry)
        self.records.mkdir(parents=True, exist_ok=True, mode=0o700)
        filename = f"{entry['sequence']:08d}-{entry['current_record_hash']}.json"
        self._exclusive_write(self.records / filename, canonical_json(entry))
        self._sync_directory(self.records)
        self._write_head(entry)
        return entry

    def append_correction(
        self, *, supersedes_record_hash: str, reason: str,
        corrected_payload: dict[str, Any], created_at: str,
    ) -> dict[str, Any]:
        existing = self.entries()
        targets = {
            entry["current_record_hash"]: entry for entry in existing
            if entry.get("record_type") in {"SIGNAL", "FAILURE", "CORRECTION"}
        }
        target = targets.get(supersedes_record_hash)
        if target is None:
            raise ValueError("correction target is not an earlier canonical record")
        if not reason.strip():
            raise ValueError("correction reason is required")
        previous_hash = existing[-1]["current_record_hash"] if existing else None
        entry = {
            "record_type": "CORRECTION",
            "registry_schema_version": "1.0",
            "sequence": len(existing) + 1,
            "session_date": target["session_date"],
            "created_at": created_at,
            "next_open_at": target.get("next_open_at"),
            "code_commit": target.get("code_commit"),
            "status": "CORRECTION",
            "supersedes_record_hash": supersedes_record_hash,
            "reason": reason.strip(),
            "corrected_payload": corrected_payload,
            "previous_record_hash": previous_hash,
        }
        entry["current_record_hash"] = canonical_hash(entry)
        self.records.mkdir(parents=True, exist_ok=True, mode=0o700)
        filename = f"{entry['sequence']:08d}-{entry['current_record_hash']}.json"
        self._exclusive_write(self.records / filename, canonical_json(entry))
        self._sync_directory(self.records)
        self._write_head(entry)
        return entry

    def verify(self) -> dict[str, Any]:
        entries = self.entries()
        previous_hash = None
        signal_dates: list[date] = []
        for expected_sequence, entry in enumerate(entries, start=1):
            if entry.get("sequence") != expected_sequence:
                raise LedgerVerificationError("ledger sequence is not contiguous")
            if entry.get("previous_record_hash") != previous_hash:
                raise LedgerVerificationError("ledger previous-record link is invalid")
            recorded_hash = entry.get("current_record_hash")
            unhashed = dict(entry)
            unhashed.pop("current_record_hash", None)
            if recorded_hash != canonical_hash(unhashed):
                raise LedgerVerificationError("ledger record hash is invalid")
            expected_name = f"{expected_sequence:08d}-{recorded_hash}.json"
            if self._paths()[expected_sequence - 1].name != expected_name:
                raise LedgerVerificationError("ledger filename/hash binding is invalid")
            if entry.get("record_type") == "CORRECTION":
                earlier_hashes = {
                    row["current_record_hash"] for row in entries[:expected_sequence - 1]
                    if row.get("record_type") in {"SIGNAL", "FAILURE", "CORRECTION"}
                }
                if entry.get("supersedes_record_hash") not in earlier_hashes:
                    raise LedgerVerificationError("correction does not link to an earlier record")
            previous_hash = recorded_hash
            if entry.get("record_type") in {"SIGNAL", "FAILURE"}:
                signal_dates.append(date.fromisoformat(entry["session_date"]))

        expected_head = {
            "sequence": len(entries),
            "current_record_hash": previous_hash,
        }
        if entries:
            if not self.head_path.exists():
                raise LedgerVerificationError("ledger head is missing")
            head = json.loads(self.head_path.read_text(encoding="utf-8"))
            if head != expected_head:
                raise LedgerVerificationError("ledger head does not match the chain")
        elif self.head_path.exists():
            raise LedgerVerificationError("empty ledger has an unexpected head")
        return {
            "status": "PASS",
            "records": len(entries),
            "signal_sessions": len(signal_dates),
            "head": previous_hash,
            "first_session": min(signal_dates).isoformat() if signal_dates else None,
            "last_session": max(signal_dates).isoformat() if signal_dates else None,
        }

    def recover_head(self) -> dict[str, Any]:
        entries = self.entries()
        if not entries:
            if self.head_path.exists():
                raise LedgerVerificationError("cannot recover a head for an empty ledger")
            return {"sequence": 0, "current_record_hash": None}
        previous_hash = None
        for expected_sequence, entry in enumerate(entries, start=1):
            unhashed = dict(entry)
            recorded = unhashed.pop("current_record_hash", None)
            if (
                entry.get("sequence") != expected_sequence
                or entry.get("previous_record_hash") != previous_hash
                or recorded != canonical_hash(unhashed)
            ):
                raise LedgerVerificationError("cannot recover head from an invalid chain")
            previous_hash = recorded
        head = {"sequence": len(entries), "current_record_hash": previous_hash}
        self._atomic_replace(self.head_path, canonical_json(head))
        return head

    def missing_signal_sessions(self, calendar: Any) -> list[date]:
        signal_dates = sorted(
            date.fromisoformat(entry["session_date"])
            for entry in self.entries() if entry.get("record_type") in {"SIGNAL", "FAILURE"}
        )
        if len(signal_dates) < 2:
            return []
        observed = set(signal_dates)
        return [
            session
            for session in calendar.trading_days_between(signal_dates[0], signal_dates[-1])
            if session not in observed
        ]

    def _write_head(self, entry: dict[str, Any]) -> None:
        self._atomic_replace(self.head_path, canonical_json({
            "sequence": entry["sequence"],
            "current_record_hash": entry["current_record_hash"],
        }))

    @staticmethod
    def _exclusive_write(path: Path, payload: bytes) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            if path.exists():
                path.unlink()
            raise

    @staticmethod
    def _atomic_replace(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".head.")
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    @staticmethod
    def _sync_directory(path: Path) -> None:
        directory_fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
