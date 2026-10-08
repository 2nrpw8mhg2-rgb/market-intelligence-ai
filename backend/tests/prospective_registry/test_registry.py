import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.prospective_registry.anchor import GitHubAnchor
from app.prospective_registry.config import RegistryConfig
from app.prospective_registry.generator import (
    FrozenProspectiveSignalGenerator,
    PreparedRegistration,
)
from app.prospective_registry.ledger import (
    AppendOnlyLedger,
    DuplicateRegistrationError,
    LedgerVerificationError,
)
from app.prospective_registry.models import (
    AnchorReceipt,
    PendingMembershipChange,
    RegistryStatus,
    UniverseConfirmation,
)
from app.prospective_registry.service import ProspectiveRegistryService
from app.prospective_registry.snapshots import ContentAddressedSnapshotStore
from app.prospective_registry.timing import ProspectiveTiming
from app.prospective_registry.universe import (
    apply_membership_changes,
    universe_snapshot_hash,
    validate_universe_confirmation,
)
from app.prospective_registry.versioning import CodeVersionError, CodeVersionVerifier
from app.schemas.market_data import MarketBar


SESSION = date(2024, 7, 5)
SECURITY_ID = "11111111-1111-1111-1111-111111111111"


def aware(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def membership(ticker: str = "TEST") -> dict:
    return {
        "security_id": SECURITY_ID,
        "ticker": ticker,
        "security_name": "Test Security",
        "valid_from": "2020-01-01",
        "valid_to": None,
        "source": "synthetic",
        "source_confidence": "HIGH",
        "provenance": {"fixture": True},
        "eligibility_status": "TRADABLE",
    }


def confirmation(memberships: list[dict] | None = None) -> UniverseConfirmation:
    values = memberships or [membership()]
    return UniverseConfirmation(
        session_date=SESSION,
        source_name="S&P Dow Jones Indices announcement review",
        source_reference="synthetic://fixture",
        source_publication_at=aware("2024-07-05T18:00:00Z"),
        operator_confirmed_at=aware("2024-07-05T21:00:00Z"),
        universe_snapshot_hash=universe_snapshot_hash(values),
        effective_changes_checked=True,
        no_intervening_changes_confirmed=True,
    )


def test_timing_classifies_before_and_at_next_open() -> None:
    timing = ProspectiveTiming()
    ready = aware("2024-07-05T20:30:00Z")
    next_open = timing.next_open(SESSION)
    status, _ = timing.classify(
        session=SESSION, data_ready_at=ready, registered_at=next_open - timedelta(seconds=1),
    )
    late, _ = timing.classify(
        session=SESSION, data_ready_at=ready, registered_at=next_open,
    )
    assert status is RegistryStatus.TIMELY
    assert late is RegistryStatus.LATE


def test_next_open_handles_us_eu_dst_mismatch() -> None:
    # Portugal has changed to UTC; New York remains on daylight time.
    assert ProspectiveTiming().next_open(date(2023, 10, 27)) == aware(
        "2023-10-30T13:30:00Z"
    )


def test_data_readiness_before_close_fails_closed() -> None:
    with pytest.raises(ValueError, match="before the session close"):
        ProspectiveTiming().classify(
            session=SESSION,
            data_ready_at=aware("2024-07-05T19:59:00Z"),
            registered_at=aware("2024-07-05T20:01:00Z"),
        )


def test_announced_change_is_not_effective_early() -> None:
    change = PendingMembershipChange(
        action="ADD",
        security_id="22222222-2222-2222-2222-222222222222",
        announcement_at=aware("2024-07-01T20:00:00Z"),
        effective_at=aware("2024-07-08T13:30:00Z"),
        new_ticker="NEW",
        source_reference="synthetic://announcement",
    )
    original = {SECURITY_ID: "TEST"}
    assert apply_membership_changes(
        original, [change], as_of=aware("2024-07-05T21:00:00Z")
    ) == original
    assert set(apply_membership_changes(
        original, [change], as_of=aware("2024-07-08T13:30:00Z")
    )) == {SECURITY_ID, change.security_id}


def test_ticker_change_preserves_security_identity() -> None:
    change = PendingMembershipChange(
        action="TICKER_CHANGE",
        security_id=SECURITY_ID,
        announcement_at=aware("2024-07-01T20:00:00Z"),
        effective_at=aware("2024-07-05T13:30:00Z"),
        old_ticker="OLD",
        new_ticker="NEW",
        source_reference="synthetic://announcement",
    )
    assert apply_membership_changes(
        {SECURITY_ID: "OLD"}, [change], as_of=aware("2024-07-05T20:00:00Z")
    ) == {SECURITY_ID: "NEW"}


def test_stale_universe_confirmation_is_rejected() -> None:
    with pytest.raises(ValidationError, match="freshness"):
        UniverseConfirmation(
            session_date=SESSION,
            source_name="source",
            source_reference="synthetic://fixture",
            operator_confirmed_at=aware("2024-07-05T21:00:00Z"),
            universe_snapshot_hash="0" * 64,
            effective_changes_checked=True,
            no_intervening_changes_confirmed=False,
        )


def test_missing_universe_confirmation_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        UniverseConfirmation.model_validate({"session_date": SESSION.isoformat()})


def test_universe_hash_mismatch_is_rejected() -> None:
    changed = membership("OTHER")
    with pytest.raises(ValueError, match="does not match"):
        validate_universe_confirmation(
            confirmation(), session_memberships=[changed],
            now=aware("2024-07-05T21:01:00Z"),
        )


def test_pending_changes_cannot_be_applied_before_effective_time() -> None:
    added_id = "22222222-2222-2222-2222-222222222222"
    pending_add = PendingMembershipChange(
        action="ADD",
        security_id=added_id,
        announcement_at=aware("2024-07-01T20:00:00Z"),
        effective_at=aware("2024-07-08T13:30:00Z"),
        new_ticker="EARLY",
        source_reference="synthetic://announcement",
    )
    premature = [membership(), {**membership("EARLY"), "security_id": added_id}]
    conf = confirmation(premature).model_copy(update={"pending_changes": (pending_add,)})
    with pytest.raises(ValueError, match="ADD was applied before"):
        validate_universe_confirmation(
            conf, session_memberships=premature,
            now=aware("2024-07-05T21:01:00Z"),
        )


def test_snapshot_store_is_deterministic_and_detects_tampering(tmp_path: Path) -> None:
    store = ContentAddressedSnapshotStore(tmp_path)
    value = {"session": SESSION.isoformat(), "bars": [{"close": 1.0}]}
    first = store.put(value)
    assert store.put(value) == first
    assert store.get(first) == value
    path = tmp_path / first[:2] / f"{first}.json.gz"
    path.write_bytes(b"tampered")
    with pytest.raises(Exception):
        store.get(first)


def test_revised_price_history_creates_new_snapshot_without_rewriting_old(
    tmp_path: Path,
) -> None:
    store = ContentAddressedSnapshotStore(tmp_path)
    original = {"bars": [{"session": "2024-07-05", "close": 100.0}]}
    revised = {"bars": [{"session": "2024-07-05", "close": 50.0}]}
    original_hash = store.put(original)
    revised_hash = store.put(revised)
    assert original_hash != revised_hash
    assert store.get(original_hash) == original
    assert store.get(revised_hash) == revised


def signal_payload(session: date, marker: str = "a") -> dict:
    return {
        "record_type": "SIGNAL",
        "session_date": session.isoformat(),
        "marker": marker,
    }


def test_ledger_duplicate_is_idempotent_but_conflict_fails(tmp_path: Path) -> None:
    ledger = AppendOnlyLedger(tmp_path)
    first = ledger.append(signal_payload(SESSION), session_date=SESSION)
    assert ledger.append(signal_payload(SESSION), session_date=SESSION) == first
    with pytest.raises(DuplicateRegistrationError):
        ledger.append(signal_payload(SESSION, "different"), session_date=SESSION)
    assert ledger.verify()["status"] == "PASS"


def test_interrupted_head_can_be_recovered(tmp_path: Path) -> None:
    ledger = AppendOnlyLedger(tmp_path)
    first = ledger.append(signal_payload(SESSION), session_date=SESSION)
    ledger.head_path.unlink()
    with pytest.raises(LedgerVerificationError, match="head is missing"):
        ledger.verify()
    assert ledger.recover_head()["current_record_hash"] == first["current_record_hash"]
    assert ledger.verify()["status"] == "PASS"


def test_hash_chain_tampering_is_detected(tmp_path: Path) -> None:
    ledger = AppendOnlyLedger(tmp_path)
    ledger.append(signal_payload(SESSION), session_date=SESSION)
    path = ledger._paths()[0]
    value = json.loads(path.read_text())
    value["marker"] = "tampered"
    path.write_text(json.dumps(value))
    with pytest.raises(LedgerVerificationError, match="hash"):
        ledger.verify()


def test_missing_session_is_detected(tmp_path: Path) -> None:
    ledger = AppendOnlyLedger(tmp_path)
    ledger.append(signal_payload(date(2024, 7, 1)), session_date=date(2024, 7, 1))
    ledger.append(signal_payload(date(2024, 7, 3)), session_date=date(2024, 7, 3))
    calendar = SimpleNamespace(
        trading_days_between=lambda start, end: [
            date(2024, 7, 1), date(2024, 7, 2), date(2024, 7, 3),
        ]
    )
    assert ledger.missing_signal_sessions(calendar) == [date(2024, 7, 2)]


def test_failed_session_is_append_only_idempotent_and_preserves_continuity(tmp_path: Path) -> None:
    ledger = AppendOnlyLedger(tmp_path)
    failure = ledger.append_failure(
        session_date=date(2024, 7, 2),
        created_at="2024-07-02T21:00:00+00:00",
        data_ready_at="2024-07-02T20:30:00+00:00",
        next_open_at="2024-07-03T13:30:00+00:00",
        code_commit="a" * 40,
        failure_stage="PREPARE_OR_READINESS",
        error="missing daily bar",
    )
    repeated = ledger.append_failure(
        session_date=date(2024, 7, 2),
        created_at="2024-07-02T21:01:00+00:00",
        data_ready_at="2024-07-02T20:30:00+00:00",
        next_open_at="2024-07-03T13:30:00+00:00",
        code_commit="a" * 40,
        failure_stage="PREPARE_OR_READINESS",
        error="missing daily bar",
    )
    assert repeated == failure
    assert ledger.verify()["signal_sessions"] == 1


def test_correction_must_link_to_an_earlier_canonical_record(tmp_path: Path) -> None:
    ledger = AppendOnlyLedger(tmp_path)
    signal = ledger.append(signal_payload(SESSION), session_date=SESSION)
    correction = ledger.append_correction(
        supersedes_record_hash=signal["current_record_hash"],
        reason="provider correction received",
        corrected_payload={"signals": []},
        created_at="2024-07-06T10:00:00+00:00",
    )
    assert correction["supersedes_record_hash"] == signal["current_record_hash"]
    assert ledger.verify()["status"] == "PASS"
    with pytest.raises(ValueError, match="not an earlier"):
        ledger.append_correction(
            supersedes_record_hash="f" * 64,
            reason="invalid target",
            corrected_payload={},
            created_at="2024-07-06T11:00:00+00:00",
        )


def test_registry_is_disabled_by_default(monkeypatch) -> None:
    for name in list(__import__("os").environ):
        if name.startswith("PROSPECTIVE_REGISTRY_"):
            monkeypatch.delenv(name, raising=False)
    config = RegistryConfig.from_env()
    assert not config.enabled
    with pytest.raises(RuntimeError, match="disabled"):
        config.validate_for_registration()


def test_failed_and_delayed_github_push_are_explicit(tmp_path: Path) -> None:
    sha = "a" * 40
    commands: list[list[str]] = []

    def runner(command: list[str], cwd: Path) -> str:
        commands.append(command)
        if command[:3] == ["git", "remote", "get-url"]:
            return "git@github.com:owner/private-registry.git"
        if command[:3] == ["gh", "repo", "view"]:
            return "PRIVATE"
        if command[:3] == ["git", "diff", "--cached"]:
            return "records/value.json"
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return sha
        if command[:2] == ["git", "push"]:
            raise RuntimeError("simulated push failure")
        return ""

    record = {
        "session_date": SESSION.isoformat(),
        "current_record_hash": "b" * 64,
    }
    failed = GitHubAnchor(
        tmp_path, runner=runner, now=lambda: aware("2024-07-05T21:00:00Z"),
    ).anchor(record, next_open_at=aware("2024-07-08T13:30:00Z"))
    assert failed.status is RegistryStatus.FAILED
    assert "simulated push failure" in failed.error

    times = iter([
        aware("2024-07-05T21:00:00Z"), aware("2024-07-08T13:30:00Z"),
    ])

    def delayed_runner(command: list[str], cwd: Path) -> str:
        if command[:3] == ["git", "remote", "get-url"]:
            return "git@github.com:owner/private-registry.git"
        if command[:3] == ["gh", "repo", "view"]:
            return "PRIVATE"
        if command[:3] == ["git", "diff", "--cached"]:
            return "records/value.json"
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return sha
        if command[:3] == ["git", "ls-remote", "origin"]:
            return f"{sha}\tHEAD"
        return ""

    late = GitHubAnchor(tmp_path, runner=delayed_runner, now=lambda: next(times)).anchor(
        record, next_open_at=aware("2024-07-08T13:30:00Z"),
    )
    assert late.status is RegistryStatus.LATE


def test_remote_inventory_is_server_queried_and_suffix_visible(tmp_path: Path) -> None:
    first = "a" * 64
    second = "b" * 64

    def runner(command: list[str], cwd: Path) -> str:
        if command[:3] == ["git", "remote", "get-url"]:
            return "git@github.com:owner/private-registry.git"
        if command[:3] == ["gh", "repo", "view"]:
            return "PRIVATE"
        if command[:2] == ["gh", "api"] and "/contents/records" in command[2]:
            return f"2024-07-05-{first}.json\n2024-07-08-{second}.json"
        raise AssertionError(command)

    assert GitHubAnchor(tmp_path, runner=runner).remote_record_hashes() == {first, second}


def test_code_version_rejects_dirty_tree_and_wrong_release_tag(tmp_path: Path) -> None:
    class Verifier(CodeVersionVerifier):
        def __init__(self, responses):
            super().__init__(tmp_path)
            self.responses = responses

        def _git(self, *args: str) -> str:
            return self.responses[args]

    with pytest.raises(CodeVersionError, match="clean working tree"):
        Verifier({("status", "--porcelain"): "?? untracked"}).verify_release("v1")

    responses = {
        ("status", "--porcelain"): "",
        ("rev-parse", "HEAD"): "a" * 40,
        ("rev-list", "-n", "1", "v1"): "b" * 40,
    }
    with pytest.raises(CodeVersionError, match="does not point"):
        Verifier(responses).verify_release("v1")


class FakeMembership:
    def __init__(self, value: dict) -> None:
        self.value = value

    def model_dump(self, mode: str) -> dict:
        return self.value


class FakeUniverseRepository:
    async def list_period_memberships(self, name, start, end):
        return [FakeMembership(membership())]


class FakeBarsRepository:
    def __init__(self, *, breakout: bool = False, missing_session: bool = False) -> None:
        self.end_dates: list[date | None] = []
        self.breakout = breakout
        self.missing_session = missing_session

    async def list_daily_bars(self, ticker, start_date=None, end_date=None, provider=None):
        self.end_dates.append(end_date)
        bars = []
        start = SESSION - timedelta(days=219)
        for offset in range(220):
            stamp = start + timedelta(days=offset)
            close = 100 + offset * 0.5
            volume = 100_000
            if offset == 219 and self.breakout:
                close += 20
                volume = 300_000
            bars.append(MarketBar(
                ticker=ticker,
                timestamp=datetime.combine(stamp, datetime.min.time(), tzinfo=UTC),
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=volume,
            ))
        if self.missing_session:
            bars = bars[:-1]
        return [bar for bar in bars if end_date is None or bar.timestamp.date() <= end_date]


@pytest.mark.asyncio
async def test_generator_registers_zero_signal_session_and_never_reads_future(tmp_path: Path) -> None:
    bars = FakeBarsRepository()
    generator = FrozenProspectiveSignalGenerator(
        universe_repository=FakeUniverseRepository(),
        market_bars=bars,
        snapshot_store=ContentAddressedSnapshotStore(tmp_path),
    )
    prepared = await generator.prepare(
        session_date=SESSION,
        confirmation=confirmation(),
        data_ready_at=aware("2024-07-05T20:30:00Z"),
        data_ready_evidence="synthetic ingestion completion",
        captured_at=aware("2024-07-05T21:00:00Z"),
    )
    assert prepared.signals == ()
    assert bars.end_dates == [SESSION]
    assert ContentAddressedSnapshotStore(tmp_path).verify(prepared.input_snapshot_hash)


@pytest.mark.asyncio
async def test_generator_preserves_identity_and_frozen_score(tmp_path: Path) -> None:
    generator = FrozenProspectiveSignalGenerator(
        universe_repository=FakeUniverseRepository(),
        market_bars=FakeBarsRepository(breakout=True),
        snapshot_store=ContentAddressedSnapshotStore(tmp_path),
    )
    prepared = await generator.prepare(
        session_date=SESSION,
        confirmation=confirmation(),
        data_ready_at=aware("2024-07-05T20:30:00Z"),
        data_ready_evidence="synthetic ingestion completion",
        captured_at=aware("2024-07-05T21:00:00Z"),
    )
    assert len(prepared.signals) == 1
    assert prepared.signals[0].security_id == SECURITY_ID
    assert prepared.signals[0].ticker == "TEST"
    assert prepared.signals[0].rank == 1


@pytest.mark.asyncio
async def test_missing_daily_bar_fails_closed(tmp_path: Path) -> None:
    generator = FrozenProspectiveSignalGenerator(
        universe_repository=FakeUniverseRepository(),
        market_bars=FakeBarsRepository(missing_session=True),
        snapshot_store=ContentAddressedSnapshotStore(tmp_path),
    )
    with pytest.raises(RuntimeError, match="MISSING_MARKET_DATA"):
        await generator.prepare(
            session_date=SESSION,
            confirmation=confirmation(),
            data_ready_at=aware("2024-07-05T20:30:00Z"),
            data_ready_evidence="synthetic ingestion completion",
            captured_at=aware("2024-07-05T21:00:00Z"),
        )


@pytest.mark.asyncio
async def test_retroactive_and_disabled_registration_fail_before_generation() -> None:
    class NeverGenerator:
        async def prepare(self, **kwargs):
            raise AssertionError("generator must not be called")

    service = ProspectiveRegistryService(
        generator=NeverGenerator(), ledger=None, anchor=None,
        code_commit="a" * 40, activation_session=date(2024, 7, 8), enabled=True,
    )
    with pytest.raises(RuntimeError, match="RETROACTIVE"):
        await service.register_session(
            session_date=SESSION,
            confirmation=confirmation(),
            data_ready_at=aware("2024-07-05T20:30:00Z"),
            data_ready_evidence="synthetic",
        )

    disabled = ProspectiveRegistryService(
        generator=NeverGenerator(), ledger=None, anchor=None,
        code_commit="a" * 40, activation_session=SESSION, enabled=False,
    )
    with pytest.raises(RuntimeError, match="disabled"):
        await disabled.register_session(
            session_date=SESSION,
            confirmation=confirmation(),
            data_ready_at=aware("2024-07-05T20:30:00Z"),
            data_ready_evidence="synthetic",
        )


@pytest.mark.asyncio
async def test_preparation_failure_is_recorded_and_anchored(tmp_path: Path) -> None:
    class FailingGenerator:
        async def prepare(self, **kwargs):
            raise RuntimeError("missing or incomplete daily bars")

    class FakeAnchor:
        def anchor(self, record, *, next_open_at):
            return AnchorReceipt(
                record_hash=record["current_record_hash"],
                remote_commit_sha="b" * 40,
                remote_name="origin",
                remote_visibility="PRIVATE",
                attempted_at=aware("2024-07-05T21:00:00Z"),
                verified_at=aware("2024-07-05T21:01:00Z"),
                next_open_at=next_open_at,
                status="TIMELY",
                timing_evidence="REMOTE_SHA_OBSERVED_LOCAL_CLOCK_WEAK",
            )

    ledger = AppendOnlyLedger(tmp_path)
    service = ProspectiveRegistryService(
        generator=FailingGenerator(), ledger=ledger, anchor=FakeAnchor(),
        code_commit="a" * 40, activation_session=SESSION, enabled=True,
        now=lambda: aware("2024-07-05T21:00:00Z"),
    )
    with pytest.raises(RuntimeError, match="failed closed"):
        await service.register_session(
            session_date=SESSION,
            confirmation=confirmation(),
            data_ready_at=aware("2024-07-05T20:30:00Z"),
            data_ready_evidence="synthetic",
        )
    assert [row["record_type"] for row in ledger.entries()] == [
        "FAILURE", "ANCHOR_RECEIPT",
    ]
    assert ledger.verify()["status"] == "PASS"


@pytest.mark.asyncio
async def test_successful_zero_signal_registration_is_canonical_and_retry_safe(
    tmp_path: Path,
) -> None:
    class Generator:
        async def prepare(self, **kwargs):
            return PreparedRegistration(
                session_date=SESSION,
                signals=(),
                input_snapshot_hash="1" * 64,
                pit_universe_hash="2" * 64,
                parameter_hash="3" * 64,
                scanner_summary={"opportunities_found": 0},
            )

    class FakeAnchor:
        def anchor(self, record, *, next_open_at):
            return AnchorReceipt(
                record_hash=record["current_record_hash"],
                remote_commit_sha="b" * 40,
                remote_name="origin",
                remote_visibility="PRIVATE",
                attempted_at=aware("2024-07-05T21:00:00Z"),
                verified_at=aware("2024-07-05T21:01:00Z"),
                next_open_at=next_open_at,
                status="TIMELY",
                timing_evidence="REMOTE_SHA_OBSERVED_LOCAL_CLOCK_WEAK",
            )

    moments = iter([
        aware("2024-07-05T21:00:00Z"), aware("2024-07-05T21:01:00Z"),
        aware("2024-07-05T21:05:00Z"), aware("2024-07-05T21:06:00Z"),
    ])
    ledger = AppendOnlyLedger(tmp_path)
    service = ProspectiveRegistryService(
        generator=Generator(), ledger=ledger, anchor=FakeAnchor(),
        code_commit="a" * 40, activation_session=SESSION, enabled=True,
        now=lambda: next(moments),
    )
    arguments = {
        "session_date": SESSION,
        "confirmation": confirmation(),
        "data_ready_at": aware("2024-07-05T20:30:00Z"),
        "data_ready_evidence": "synthetic",
    }
    first = await service.register_session(**arguments)
    repeated = await service.register_session(**arguments)
    assert first["status"] == "TIMELY"
    assert not first["independently_anchored_timely"]
    assert first["holdout_qualification"] == "NOT_INDEPENDENTLY_TIMESTAMPED"
    assert repeated["record_hash"] == first["record_hash"]
    assert [row["record_type"] for row in ledger.entries()] == [
        "SIGNAL", "ANCHOR_RECEIPT",
    ]
