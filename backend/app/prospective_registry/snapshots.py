import gzip
import os
import tempfile
from pathlib import Path
from typing import Any

from app.prospective_registry.canonical import canonical_hash, canonical_json


class ContentAddressedSnapshotStore:
    """Private, deterministic, content-addressed storage for licensed inputs."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, snapshot: dict[str, Any]) -> str:
        payload = canonical_json(snapshot)
        digest = canonical_hash(snapshot)
        destination = self.root / digest[:2] / f"{digest}.json.gz"
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if destination.exists():
            if self.get(digest) != snapshot:
                raise RuntimeError("snapshot hash collision or existing-file corruption")
            return digest
        compressed = gzip.compress(payload, compresslevel=9, mtime=0)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent, prefix=f".{digest}.", suffix=".tmp",
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(compressed)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
            directory_fd = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return digest

    def get(self, digest: str) -> dict[str, Any]:
        path = self.root / digest[:2] / f"{digest}.json.gz"
        if not path.exists():
            raise FileNotFoundError(f"input snapshot not found: {digest}")
        import json

        value = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        if canonical_hash(value) != digest:
            raise RuntimeError(f"input snapshot failed hash verification: {digest}")
        return value

    def verify(self, digest: str) -> bool:
        self.get(digest)
        return True
