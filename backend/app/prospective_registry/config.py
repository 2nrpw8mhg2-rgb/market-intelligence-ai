import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path


def _enabled(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class RegistryConfig:
    enabled: bool
    ledger_dir: Path | None
    snapshot_dir: Path | None
    anchor_repo: Path | None
    release_tag: str | None
    activation_session: date | None
    anchor_remote: str = "origin"

    @classmethod
    def from_env(cls) -> "RegistryConfig":
        return cls(
            enabled=_enabled(os.getenv("PROSPECTIVE_REGISTRY_ENABLED")),
            ledger_dir=_path_env("PROSPECTIVE_REGISTRY_LEDGER_DIR"),
            snapshot_dir=_path_env("PROSPECTIVE_REGISTRY_SNAPSHOT_DIR"),
            anchor_repo=_path_env("PROSPECTIVE_REGISTRY_ANCHOR_REPO"),
            release_tag=os.getenv("PROSPECTIVE_REGISTRY_RELEASE_TAG"),
            activation_session=(
                date.fromisoformat(os.environ["PROSPECTIVE_REGISTRY_ACTIVATION_SESSION"])
                if os.getenv("PROSPECTIVE_REGISTRY_ACTIVATION_SESSION") else None
            ),
            anchor_remote=os.getenv("PROSPECTIVE_REGISTRY_ANCHOR_REMOTE", "origin"),
        )

    def validate_for_registration(self) -> None:
        if not self.enabled:
            raise RuntimeError("prospective registry is disabled by default")
        missing = [
            name for name, value in (
                ("PROSPECTIVE_REGISTRY_LEDGER_DIR", self.ledger_dir),
                ("PROSPECTIVE_REGISTRY_SNAPSHOT_DIR", self.snapshot_dir),
                ("PROSPECTIVE_REGISTRY_ANCHOR_REPO", self.anchor_repo),
                ("PROSPECTIVE_REGISTRY_RELEASE_TAG", self.release_tag),
                ("PROSPECTIVE_REGISTRY_ACTIVATION_SESSION", self.activation_session),
            ) if value is None
        ]
        if missing:
            raise RuntimeError("missing registry activation configuration: " + ", ".join(missing))


def _path_env(name: str) -> Path | None:
    value = os.getenv(name)
    return Path(value).expanduser().resolve() if value else None
