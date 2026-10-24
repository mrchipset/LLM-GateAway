from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime
from uuid import UUID

from pydantic import SecretStr

from llm_gateway.storage.repositories import ApiKeyRecord

API_KEY_PREFIX = "sk-gw-"
API_KEY_DISPLAY_LENGTH = len(API_KEY_PREFIX) + 6


def hash_api_key(secret: str) -> str:
    """Return the lowercase SHA-256 hex digest of the key secret."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def generate_api_key(
    *,
    key_id: UUID,
    name: str,
    now: datetime,
    expires_at: datetime | None = None,
) -> tuple[str, ApiKeyRecord]:
    """Create a plaintext secret plus the record that persists only its hash."""
    if not name.strip():
        raise ValueError("name must not be blank")

    secret = API_KEY_PREFIX + secrets.token_urlsafe(32)
    record = ApiKeyRecord(
        id=key_id,
        name=name,
        key_hash=hash_api_key(secret),
        key_prefix=secret[:API_KEY_DISPLAY_LENGTH],
        created_at=now,
        expires_at=expires_at,
    )
    return secret, record


def is_key_active(record: ApiKeyRecord, now: datetime) -> bool:
    """Return True when the key is neither revoked nor expired at ``now``."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if record.revoked_at is not None:
        return False
    if record.expires_at is None:
        return True
    if record.expires_at.tzinfo is None or record.expires_at.utcoffset() is None:
        raise ValueError("expires_at must be timezone-aware")
    return record.expires_at > now


def verify_master_key(candidate: str, expected: SecretStr) -> bool:
    """Compare a candidate master key to the configured one in constant time."""
    return hmac.compare_digest(
        candidate.encode("utf-8"),
        expected.get_secret_value().encode("utf-8"),
    )
