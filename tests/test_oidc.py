from __future__ import annotations

import json
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from llm_gateway.api.admin.oidc import NONCE_COOKIE, STATE_COOKIE, VERIFIER_COOKIE
from llm_gateway.config import Environment, Settings
from llm_gateway.container import Container
from llm_gateway.services.oidc import OIDCError, OIDCIdentity, OIDCService
from llm_gateway.storage.repositories import AdminRole
from support import FrozenClock

ISSUER = "https://idp.test"
CLIENT_ID = "gateway-console"
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "environment": Environment.TEST,
        "master_key": "test-master-key-0123456789abcdef",
        "oidc_enabled": True,
        "oidc_issuer": ISSUER,
        "oidc_client_id": CLIENT_ID,
        "oidc_client_secret": "client-secret",
        "oidc_redirect_uri": "https://gateway.test/api/v1/auth/oidc/callback",
        "oidc_role_claim": "groups",
        "oidc_role_map": '{"gateway-owners":"owner","gateway-ops":"operator"}',
    }
    values.update(overrides)
    return Settings(**values)


def _key_material() -> tuple[rsa.RSAPrivateKey, dict[str, object]]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": "key-1", "alg": "RS256", "use": "sig"})
    return key, jwk


def _id_token(
    key: rsa.RSAPrivateKey,
    *,
    nonce: str,
    groups: list[str] | None = None,
    username: str = "alice",
) -> str:
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "subject-1",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "nonce": nonce,
        "preferred_username": username,
        "name": "Alice Example",
        "groups": ["gateway-ops"] if groups is None else groups,
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "key-1"})


def _client(id_token: str, jwk: dict[str, object]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks",
                },
            )
        if request.url.path == "/token":
            return httpx.Response(200, json={"id_token": id_token, "access_token": "a"})
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [jwk]})
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_authorize_url_contains_pkce_state_and_nonce() -> None:
    key, jwk = _key_material()
    token = _id_token(key, nonce="nonce")
    service = OIDCService(settings=_settings(), client=_client(token, jwk))
    try:
        url = await service.authorize_url(
            state="state-1",
            nonce="nonce",
            code_challenge="challenge",
        )
    finally:
        await service.aclose()

    assert url.startswith(f"{ISSUER}/authorize?")
    assert "state=state-1" in url
    assert "nonce=nonce" in url
    assert "code_challenge=challenge" in url
    assert "code_challenge_method=S256" in url
    assert f"client_id={CLIENT_ID}" in url


async def test_exchange_validates_token_and_maps_the_highest_role() -> None:
    key, jwk = _key_material()
    token = _id_token(key, nonce="nonce", groups=["gateway-ops", "gateway-owners"])
    service = OIDCService(settings=_settings(), client=_client(token, jwk))
    try:
        identity = await service.exchange(
            code="code",
            code_verifier="verifier",
            nonce="nonce",
        )
    finally:
        await service.aclose()

    assert identity.subject == "subject-1"
    assert identity.username == "alice"
    assert identity.display_name == "Alice Example"
    assert identity.role.value == "owner"


async def test_exchange_rejects_a_nonce_mismatch() -> None:
    key, jwk = _key_material()
    token = _id_token(key, nonce="other")
    service = OIDCService(settings=_settings(), client=_client(token, jwk))
    try:
        with pytest.raises(OIDCError) as info:
            await service.exchange(code="code", code_verifier="verifier", nonce="nonce")
    finally:
        await service.aclose()

    assert info.value.code == "nonce_mismatch"


async def test_exchange_rejects_an_unmapped_role() -> None:
    key, jwk = _key_material()
    token = _id_token(key, nonce="nonce", groups=["some-other-group"])
    service = OIDCService(settings=_settings(), client=_client(token, jwk))
    try:
        with pytest.raises(OIDCError) as info:
            await service.exchange(code="code", code_verifier="verifier", nonce="nonce")
    finally:
        await service.aclose()

    assert info.value.code == "role_not_mapped"


async def test_exchange_rejects_an_unsigned_algorithm() -> None:
    unsigned = jwt.encode(
        {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "subject-1",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "nonce": "nonce",
        },
        None,  # pyright: ignore[reportArgumentType] - unsigned token is the case under test
        algorithm="none",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks",
                },
            )
        if request.url.path == "/token":
            return httpx.Response(200, json={"id_token": unsigned})
        return httpx.Response(404)

    service = OIDCService(
        settings=_settings(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        with pytest.raises(OIDCError) as info:
            await service.exchange(code="code", code_verifier="verifier", nonce="nonce")
    finally:
        await service.aclose()

    assert info.value.code == "invalid_id_token"


class FakeOIDC:
    def __init__(self, identity: OIDCIdentity) -> None:
        self.identity = identity
        self.last_state: str | None = None

    async def authorize_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        self.last_state = state
        return f"{ISSUER}/authorize?state={state}&nonce={nonce}&code_challenge={code_challenge}"

    async def exchange(self, *, code: str, code_verifier: str, nonce: str) -> OIDCIdentity:
        return self.identity

    async def aclose(self) -> None:
        return None


def _identity(role: str = "operator", subject: str = "subject-1") -> OIDCIdentity:
    return OIDCIdentity(
        subject=subject,
        username="alice",
        fallback_username="oidc-1234567890ab",
        display_name="Alice Example",
        role=AdminRole(role),
    )


async def _client_with_oidc(
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
    *,
    identity: OIDCIdentity,
    jit: bool = True,
    settings: Settings | None = None,
) -> tuple[Any, FakeOIDC]:
    resolved = settings or _settings(oidc_jit_provisioning=jit)
    container = make_container(resolved, clock=FrozenClock(NOW))
    fake = FakeOIDC(identity)
    container.oidc = cast(Any, fake)
    return container, fake


async def test_oidc_status_and_start_set_flow_cookies(
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, _fake = await _client_with_oidc(make_container, make_client, identity=_identity())
    settings = container.settings

    async with make_client(settings, container) as client:
        status = await client.get("/api/v1/auth/oidc/status")
        started = await client.get("/api/v1/auth/oidc/start", follow_redirects=False)

    assert status.status_code == 200
    assert status.json() == {"enabled": True}
    assert started.status_code == 302
    assert started.headers["location"].startswith(f"{ISSUER}/authorize?")
    assert client.cookies.get(STATE_COOKIE) is not None
    assert client.cookies.get(NONCE_COOKIE) is not None
    assert client.cookies.get(VERIFIER_COOKIE) is not None


async def test_oidc_callback_creates_a_session_and_provisions_once(
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, fake = await _client_with_oidc(
        make_container, make_client, identity=_identity("operator")
    )
    settings = container.settings

    async with make_client(settings, container) as client:
        await client.get("/api/v1/auth/oidc/start", follow_redirects=False)
        state = fake.last_state
        assert state is not None
        callback = await client.get(
            f"/api/v1/auth/oidc/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        me = await client.get("/api/v1/auth/me")

    assert callback.status_code == 303
    assert callback.headers["location"] == "/"
    assert client.cookies.get("gw_admin_session") is not None
    assert me.status_code == 200
    assert me.json()["role"] == "operator"

    admin = await container.admins.get_admin_by_oidc_subject("subject-1")
    assert admin is not None
    assert admin.username == "alice"


async def test_oidc_callback_rejects_a_state_mismatch(
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, _fake = await _client_with_oidc(make_container, make_client, identity=_identity())
    settings = container.settings

    async with make_client(settings, container) as client:
        await client.get("/api/v1/auth/oidc/start", follow_redirects=False)
        callback = await client.get(
            "/api/v1/auth/oidc/callback?code=abc&state=wrong",
            follow_redirects=False,
        )

    assert callback.status_code == 400
    assert callback.json()["error"]["code"] == "oidc_state_invalid"


async def test_oidc_callback_without_jit_redirects_with_an_error(
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container, fake = await _client_with_oidc(
        make_container,
        make_client,
        identity=_identity(),
        jit=False,
    )
    settings = container.settings

    async with make_client(settings, container) as client:
        await client.get("/api/v1/auth/oidc/start", follow_redirects=False)
        state = fake.last_state
        assert state is not None
        callback = await client.get(
            f"/api/v1/auth/oidc/callback?code=abc&state={state}",
            follow_redirects=False,
        )

    assert callback.status_code == 303
    assert callback.headers["location"] == "/?sso_error=admin_not_provisioned"
