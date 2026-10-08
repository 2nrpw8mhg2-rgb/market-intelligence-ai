import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    """Serialize deterministically for hashing and cross-machine verification."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_hex(canonical_json(value))
