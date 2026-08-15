"""API key generation and hashing.

Raw keys never persist. SHA-256 is deterministic so we can look up a client
with one indexed SELECT. Do not switch to bcrypt: unique salts cannot be queried.
"""

from __future__ import annotations

import hashlib
import secrets

_API_KEY_PREFIX = "ne_"
_TOKEN_BYTES = 32


def generate_api_key() -> str:
    """Return a high-entropy key. Show it once; store only hash_api_key(raw)."""
    return f"{_API_KEY_PREFIX}{secrets.token_urlsafe(_TOKEN_BYTES)}"


def hash_api_key(raw_api_key: str) -> str:
    """Return the hex SHA-256 of the raw key (64 chars). Never log raw_api_key."""
    return hashlib.sha256(raw_api_key.encode("utf-8")).hexdigest()
