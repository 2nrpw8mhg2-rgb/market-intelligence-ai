import argparse
import asyncio
import json
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

from app.cli.common import emit_report
from app.database.repositories import MarketBarRepository, UniverseRepository
from app.database.session import SessionFactory
from app.prospective_registry.anchor import GitHubAnchor
from app.prospective_registry.config import RegistryConfig
from app.prospective_registry.generator import FrozenProspectiveSignalGenerator
from app.prospective_registry.ledger import AppendOnlyLedger
from app.prospective_registry.models import AnchorReceipt, UniverseConfirmation
from app.prospective_registry.service import ProspectiveRegistryService
from app.prospective_registry.snapshots import ContentAddressedSnapshotStore
from app.prospective_registry.versioning import CodeVersionVerifier
from app.market_data.calendar import NYSETradingCalendar


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="Outcome-blind prospective signal registry (disabled by default)",
    )
    subcommands = command.add_subparsers(dest="operation", required=True)
    for name in ("dry-run", "register-session"):
        child = subcommands.add_parser(name)
        child.add_argument("--session", type=date.fromisoformat, required=True)
        child.add_argument("--data-ready-at", type=_aware_datetime, required=True)
        child.add_argument("--data-ready-evidence", required=True)
        child.add_argument("--universe-confirmation", type=Path, required=True)
        child.add_argument("--output")
    verify = subcommands.add_parser("verify")
    verify.add_argument("--output")
    return command


def _confirmation(path: Path) -> UniverseConfirmation:
    return UniverseConfirmation.model_validate_json(path.read_text(encoding="utf-8"))


async def _signal_operation(args: argparse.Namespace, config: RegistryConfig) -> dict:
    confirmation = _confirmation(args.universe_confirmation)
    if confirmation.session_date != args.session:
        raise ValueError("universe confirmation is for a different session")

    if args.operation == "dry-run":
        with tempfile.TemporaryDirectory(prefix="prospective-registry-dry-run-") as directory:
            snapshot_store = ContentAddressedSnapshotStore(Path(directory) / "snapshots")
            async with SessionFactory() as session:
                service = ProspectiveRegistryService(
                    generator=FrozenProspectiveSignalGenerator(
                        universe_repository=UniverseRepository(session),
                        market_bars=MarketBarRepository(session),
                        snapshot_store=snapshot_store,
                    ),
                    ledger=None,
                    anchor=None,
                    code_commit=CodeVersionVerifier(REPOSITORY_ROOT).current_commit(),
                    activation_session=config.activation_session,
                    enabled=False,
                )
                return await service.dry_run(
                    session_date=args.session,
                    confirmation=confirmation,
                    data_ready_at=args.data_ready_at,
                    data_ready_evidence=args.data_ready_evidence,
                )

    config.validate_for_registration()
    assert config.snapshot_dir and config.ledger_dir and config.anchor_repo
    assert config.release_tag and config.activation_session
    commit = CodeVersionVerifier(REPOSITORY_ROOT).verify_release(config.release_tag)
    async with SessionFactory() as session:
        service = ProspectiveRegistryService(
            generator=FrozenProspectiveSignalGenerator(
                universe_repository=UniverseRepository(session),
                market_bars=MarketBarRepository(session),
                snapshot_store=ContentAddressedSnapshotStore(config.snapshot_dir),
            ),
            ledger=AppendOnlyLedger(config.ledger_dir),
            anchor=GitHubAnchor(config.anchor_repo, remote=config.anchor_remote),
            code_commit=commit,
            activation_session=config.activation_session,
            enabled=True,
        )
        return await service.register_session(
            session_date=args.session,
            confirmation=confirmation,
            data_ready_at=args.data_ready_at,
            data_ready_evidence=args.data_ready_evidence,
        )


def _verify(config: RegistryConfig) -> dict:
    config.validate_for_registration()
    assert config.ledger_dir and config.snapshot_dir and config.anchor_repo
    ledger = AppendOnlyLedger(config.ledger_dir)
    chain = ledger.verify()
    entries = ledger.entries()
    signals = [row for row in entries if row.get("record_type") == "SIGNAL"]
    canonical_records = [
        row for row in entries if row.get("record_type") in {"SIGNAL", "FAILURE"}
    ]
    receipts = {
        row["record_hash"]: AnchorReceipt.model_validate({
            key: value for key, value in row.items()
            if key not in {"record_type", "sequence", "previous_record_hash", "current_record_hash"}
        })
        for row in entries if row.get("record_type") == "ANCHOR_RECEIPT"
    }
    missing_receipts = [
        row["current_record_hash"] for row in canonical_records
        if row["current_record_hash"] not in receipts
    ]
    snapshot_store = ContentAddressedSnapshotStore(config.snapshot_dir)
    missing_snapshots = [
        row["input_snapshot_hash"] for row in signals
        if not _snapshot_ok(snapshot_store, row["input_snapshot_hash"])
    ]
    missing_sessions = [
        item.isoformat()
        for item in ledger.missing_signal_sessions(NYSETradingCalendar())
    ]
    anchor = GitHubAnchor(config.anchor_repo, remote=config.anchor_remote)
    remote_failures = [
        record_hash for record_hash, receipt in receipts.items()
        if not anchor.verify_receipt(receipt)
    ]
    local_canonical_hashes = {
        row["current_record_hash"] for row in canonical_records
    }
    remote_record_hashes = anchor.remote_record_hashes()
    remote_inventory_mismatch = sorted(
        local_canonical_hashes.symmetric_difference(remote_record_hashes)
    )
    passed = not (
        missing_receipts or missing_snapshots or missing_sessions
        or remote_failures or remote_inventory_mismatch
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "chain": chain,
        "missing_anchor_receipts": missing_receipts,
        "missing_input_snapshots": missing_snapshots,
        "missing_sessions": missing_sessions,
        "remote_anchor_failures": remote_failures,
        "remote_inventory_mismatch": remote_inventory_mismatch,
        "performance_metrics_calculated": False,
    }


def _snapshot_ok(store: ContentAddressedSnapshotStore, digest: str) -> bool:
    try:
        return store.verify(digest)
    except Exception:
        return False


async def run(args: argparse.Namespace) -> None:
    config = RegistryConfig.from_env()
    report = (
        _verify(config)
        if args.operation == "verify"
        else await _signal_operation(args, config)
    )
    emit_report(report, args.output)


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
