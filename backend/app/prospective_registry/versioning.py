import subprocess
from pathlib import Path


class CodeVersionError(RuntimeError):
    pass


class CodeVersionVerifier:
    def __init__(self, repository: Path) -> None:
        self.repository = repository

    def verify_release(self, release_tag: str) -> str:
        status = self._git("status", "--porcelain")
        if status.strip():
            raise CodeVersionError("canonical registration requires a clean working tree")
        commit = self._git("rev-parse", "HEAD").strip()
        tag_commit = self._git("rev-list", "-n", "1", release_tag).strip()
        if tag_commit != commit:
            raise CodeVersionError("registry release tag does not point to HEAD")
        origin_main = self._git("rev-parse", "origin/main").strip()
        if origin_main != commit:
            raise CodeVersionError("registry code checkpoint is not synchronized with origin/main")
        return commit

    def current_commit(self) -> str:
        return self._git("rev-parse", "HEAD").strip()

    def _git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(self.repository), *args],
            check=True, capture_output=True, text=True,
        )
        return completed.stdout
