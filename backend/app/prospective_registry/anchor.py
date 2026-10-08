import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from app.prospective_registry.canonical import canonical_json
from app.prospective_registry.models import AnchorReceipt, RegistryStatus


Runner = Callable[[list[str], Path], str]


def _default_runner(command: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        command, cwd=cwd, check=True, capture_output=True, text=True,
    )
    return completed.stdout.strip()


class GitHubAnchor:
    """Anchors metadata only; licensed snapshots never enter this repository."""

    def __init__(
        self, repository: Path, *, remote: str = "origin", runner: Runner | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.remote = remote
        self._run = runner or _default_runner
        self._now = now or (lambda: datetime.now(UTC))

    def anchor(self, record: dict, *, next_open_at: datetime) -> AnchorReceipt:
        attempted = self._now().astimezone(UTC)
        try:
            remote_url = self._run(
                ["git", "remote", "get-url", self.remote], self.repository,
            )
            self._reject_embedded_credentials(remote_url)
            visibility = self._run(
                ["gh", "repo", "view", remote_url, "--json", "visibility", "--jq", ".visibility"],
                self.repository,
            )
            if visibility.strip().upper() != "PRIVATE":
                raise RuntimeError("anchor repository is not verified PRIVATE")

            record_hash = record["current_record_hash"]
            relative = Path("records") / f"{record['session_date']}-{record_hash}.json"
            destination = self.repository / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            payload = canonical_json(record)
            if destination.exists() and destination.read_bytes() != payload:
                raise RuntimeError("remote anchor path already contains different content")
            if not destination.exists():
                destination.write_bytes(payload)
            self._run(["git", "add", "--", str(relative)], self.repository)
            staged = self._run(["git", "diff", "--cached", "--name-only"], self.repository)
            if staged.strip():
                self._run(
                    ["git", "commit", "-m", f"Register signal {record['session_date']}"],
                    self.repository,
                )
            commit = self._run(["git", "rev-parse", "HEAD"], self.repository)
            self._run(["git", "push", self.remote, "HEAD"], self.repository)
            observed = self._run(
                ["git", "ls-remote", self.remote, "HEAD"], self.repository,
            ).split()[0]
            verified = self._now().astimezone(UTC)
            if observed != commit:
                raise RuntimeError("remote HEAD does not match the pushed anchor commit")
            status = RegistryStatus.TIMELY if verified < next_open_at else RegistryStatus.LATE
            return AnchorReceipt(
                record_hash=record_hash,
                remote_commit_sha=commit,
                remote_name=self.remote,
                remote_visibility="UNKNOWN",
                attempted_at=attempted,
                verified_at=verified,
                next_open_at=next_open_at,
                status=status,
                timing_evidence="REMOTE_SHA_OBSERVED_LOCAL_CLOCK_WEAK",
            )
        except Exception as exc:
            message = str(exc).replace("\n", " ")[:300]
            return AnchorReceipt(
                record_hash=record.get("current_record_hash", "0" * 64),
                remote_name=self.remote,
                remote_visibility="PRIVATE",
                attempted_at=attempted,
                next_open_at=next_open_at,
                status=RegistryStatus.FAILED,
                timing_evidence="REMOTE_SHA_OBSERVED_LOCAL_CLOCK_WEAK",
                error=message or type(exc).__name__,
            )

    def verify_receipt(self, receipt: AnchorReceipt) -> bool:
        if receipt.remote_commit_sha is None:
            return False
        remote_url = self._run(
            ["git", "remote", "get-url", self.remote], self.repository,
        )
        self._reject_embedded_credentials(remote_url)
        visibility = self._run(
            ["gh", "repo", "view", remote_url, "--json", "visibility", "--jq", ".visibility"],
            self.repository,
        )
        if visibility.strip().upper() != "PRIVATE":
            return False
        observed = self._run(
            ["gh", "api", f"repos/{self._github_slug(remote_url)}/commits/{receipt.remote_commit_sha}", "--jq", ".sha"],
            self.repository,
        )
        return observed == receipt.remote_commit_sha

    def remote_record_hashes(self) -> set[str]:
        """Read the server-visible record inventory to detect local suffix rollback."""
        remote_url = self._run(
            ["git", "remote", "get-url", self.remote], self.repository,
        )
        self._reject_embedded_credentials(remote_url)
        visibility = self._run(
            ["gh", "repo", "view", remote_url, "--json", "visibility", "--jq", ".visibility"],
            self.repository,
        )
        if visibility.strip().upper() != "PRIVATE":
            raise RuntimeError("anchor repository is not verified PRIVATE")
        names = self._run(
            ["gh", "api", f"repos/{self._github_slug(remote_url)}/contents/records", "--jq", ".[].name"],
            self.repository,
        )
        hashes: set[str] = set()
        for name in names.splitlines():
            stem = name.removesuffix(".json")
            candidate = stem.rsplit("-", 1)[-1]
            if len(candidate) != 64 or any(char not in "0123456789abcdef" for char in candidate):
                raise RuntimeError("remote registry contains an invalid record filename")
            hashes.add(candidate)
        return hashes

    @staticmethod
    def _github_slug(remote_url: str) -> str:
        value = remote_url.removesuffix(".git")
        if value.startswith("git@github.com:"):
            return value.split(":", 1)[1]
        parsed = urlparse(value)
        if parsed.hostname != "github.com":
            raise RuntimeError("independent anchor must use GitHub")
        return parsed.path.strip("/")

    @staticmethod
    def _reject_embedded_credentials(remote_url: str) -> None:
        parsed = urlparse(remote_url)
        if parsed.scheme in {"http", "https"} and (parsed.username or parsed.password):
            raise RuntimeError("anchor remote URL must not embed credentials")
