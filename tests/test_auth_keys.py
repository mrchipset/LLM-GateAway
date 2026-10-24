from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr

from llm_gateway.auth.dependencies import parse_bearer_token
from llm_gateway.auth.keys import (
    API_KEY_PREFIX,
    generate_api_key,
    hash_api_key,
    is_key_active,
    verify_master_key,
)
from llm_gateway.storage.repositories import ApiKeyRecord

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _record(*, expires_at: datetime | None = None) -> ApiKeyRecord:
    secret, record = generate_api_key(key_id=uuid4(), name="test", now=NOW, expires_at=expires_at)
    assert secret
    return record


def test_hash_api_key_is_deterministic_lowercase_hex() -> None:
    digest = hash_api_key("sk-gw-example-secret")

    assert digest == hash_api_key("sk-gw-example-secret")
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert digest != "sk-gw-example-secret"


def test_generate_api_key_produces_distinct_secrets_and_hashed_record() -> None:
    secret_one, record_one = generate_api_key(key_id=uuid4(), name="first", now=NOW)
    secret_two, record_two = generate_api_key(key_id=uuid4(), name="second", now=NOW)

    assert secret_one.startswith(API_KEY_PREFIX)
    assert secret_two.startswith(API_KEY_PREFIX)
    assert secret_one != secret_two
    assert record_one.key_hash == hash_api_key(secret_one)
    assert record_one.key_prefix == secret_one[: len(API_KEY_PREFIX) + 6]
    assert len(record_one.key_prefix) < len(secret_one)
    assert record_two.key_hash == hash_api_key(secret_two)


def test_generate_api_key_rejects_blank_name() -> None:
    with pytest.raises(ValueError, match="name must not be blank"):
        generate_api_key(key_id=uuid4(), name="   ", now=NOW)


def test_is_key_active_for_live_key() -> None:
    assert is_key_active(_record(), NOW)
    assert is_key_active(_record(expires_at=NOW + timedelta(seconds=1)), NOW)


def test_is_key_active_is_false_for_revoked_key() -> None:
    record = _record()
    revoked = ApiKeyRecord(
        id=record.id,
        name=record.name,
        key_hash=record.key_hash,
        key_prefix=record.key_prefix,
        created_at=record.created_at,
        revoked_at=NOW,
    )

    assert not is_key_active(revoked, NOW)


def test_is_key_active_is_false_when_expiry_equals_now() -> None:
    assert not is_key_active(_record(expires_at=NOW), NOW)


def test_is_key_active_rejects_naive_now() -> None:
    with pytest.raises(ValueError, match="now must be timezone-aware"):
        is_key_active(_record(), datetime.fromisoformat("2026-01-01T12:00:00"))


def test_verify_master_key_matches_only_equal_secret() -> None:
    expected = SecretStr("master-key-0123456789abcdef")

    assert verify_master_key("master-key-0123456789abcdef", expected)
    assert not verify_master_key("master-key-0123456789abcde", expected)
    assert not verify_master_key("", expected)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("Bearer abc", "abc"),
        ("bearer   abc", "abc"),
        ("Basic xyz", None),
        ("Bearer ", None),
    ],
)
def test_parse_bearer_token(header: str | None, expected: str | None) -> None:
    assert parse_bearer_token(header) == expected
