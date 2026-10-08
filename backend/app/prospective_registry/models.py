from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


REGISTRY_SCHEMA_VERSION = "1.0"


class RegistryStatus(StrEnum):
    TIMELY = "TIMELY"
    LATE = "LATE"
    FAILED = "FAILED"


class SignalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    security_id: str
    ticker: str
    score: float = Field(ge=0, le=100)
    rank: int = Field(ge=1)


class PendingMembershipChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["ADD", "REMOVE", "TICKER_CHANGE"]
    security_id: str
    announcement_at: datetime
    effective_at: datetime
    old_ticker: str | None = None
    new_ticker: str | None = None
    source_reference: str

    @field_validator("announcement_at", "effective_at")
    @classmethod
    def timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("membership timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def chronology_and_identity(self) -> "PendingMembershipChange":
        if self.announcement_at > self.effective_at:
            raise ValueError("announcement must not follow effective time")
        if self.action == "TICKER_CHANGE":
            if not self.old_ticker or not self.new_ticker:
                raise ValueError("ticker changes require old_ticker and new_ticker")
            if self.old_ticker == self.new_ticker:
                raise ValueError("ticker change must preserve identity across distinct aliases")
        return self


class UniverseConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_date: date
    source_name: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    source_publication_at: datetime | None = None
    operator_confirmed_at: datetime
    universe_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    pending_changes: tuple[PendingMembershipChange, ...] = ()
    effective_changes_checked: bool
    no_intervening_changes_confirmed: bool

    @field_validator("source_publication_at", "operator_confirmed_at")
    @classmethod
    def confirmation_timestamps_are_aware(
        cls, value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("confirmation timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def fail_closed_when_freshness_is_uncertain(self) -> "UniverseConfirmation":
        if not self.effective_changes_checked or not self.no_intervening_changes_confirmed:
            raise ValueError("PIT universe freshness is not explicitly confirmed")
        if (
            self.source_publication_at is not None
            and self.source_publication_at > self.operator_confirmed_at
        ):
            raise ValueError("source publication cannot follow operator confirmation")
        return self


class CanonicalSignalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_type: Literal["SIGNAL"] = "SIGNAL"
    registry_schema_version: Literal["1.0"] = REGISTRY_SCHEMA_VERSION
    sequence: int = Field(ge=1)
    session_date: date
    data_ready_at: datetime
    data_ready_evidence: str = Field(min_length=1)
    created_at: datetime
    next_open_at: datetime
    status: RegistryStatus
    observation_classification: Literal["PROSPECTIVE_CANDIDATE", "RETROACTIVE"]
    strategy_id: Literal["BREAKOUT_20D_VOLUME"] = "BREAKOUT_20D_VOLUME"
    signals: tuple[SignalPayload, ...]
    input_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    pit_universe_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameter_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    previous_record_hash: str | None
    current_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("data_ready_at", "created_at", "next_open_at")
    @classmethod
    def record_timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("registry timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ordered_signals_and_timing(self) -> "CanonicalSignalRecord":
        expected = sorted(self.signals, key=lambda row: (-row.score, row.security_id))
        if list(self.signals) != expected:
            raise ValueError("signals must use frozen deterministic ordering")
        if [row.rank for row in self.signals] != list(range(1, len(self.signals) + 1)):
            raise ValueError("signal ranks must be contiguous")
        if self.data_ready_at > self.created_at:
            raise ValueError("record cannot precede data readiness")
        expected_status = (
            RegistryStatus.TIMELY
            if self.created_at < self.next_open_at
            else RegistryStatus.LATE
        )
        if self.status is not RegistryStatus.FAILED and self.status is not expected_status:
            raise ValueError("TIMELY/LATE classification disagrees with NEXT_OPEN")
        return self


class AnchorReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    remote_commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    remote_name: str
    remote_visibility: Literal["PRIVATE", "UNKNOWN"]
    attempted_at: datetime
    verified_at: datetime | None = None
    next_open_at: datetime
    status: RegistryStatus
    timing_evidence: Literal["REMOTE_SHA_OBSERVED_LOCAL_CLOCK_WEAK"]
    independent_timing_verified: Literal[False] = False
    error: str | None = None

    @field_validator("attempted_at", "verified_at", "next_open_at")
    @classmethod
    def receipt_timestamps_are_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("anchor timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def successful_receipt_has_remote_proof(self) -> "AnchorReceipt":
        if self.status is RegistryStatus.TIMELY:
            if not self.remote_commit_sha or not self.verified_at:
                raise ValueError("TIMELY anchor requires a verified remote commit")
            if self.verified_at >= self.next_open_at:
                raise ValueError("anchor verified at/after NEXT_OPEN is not TIMELY")
        if self.status is RegistryStatus.FAILED and not self.error:
            raise ValueError("FAILED anchor requires a sanitized error")
        return self


class InputSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = REGISTRY_SCHEMA_VERSION
    session_date: date
    captured_at: datetime
    data_ready_at: datetime
    data_ready_evidence: str
    provider: str
    provider_metadata: dict[str, Any]
    universe_confirmation: UniverseConfirmation
    memberships: tuple[dict[str, Any], ...]
    bars_by_security: dict[str, tuple[dict[str, Any], ...]]

    @field_validator("captured_at", "data_ready_at")
    @classmethod
    def snapshot_timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("snapshot timestamps must be timezone-aware")
        return value.astimezone(UTC)
