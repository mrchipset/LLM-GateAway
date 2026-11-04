from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from llm_gateway.auth.passwords import hash_password
from llm_gateway.config import Settings
from llm_gateway.container import Container
from llm_gateway.storage.repositories import AdminRole, AdminUser
from support import FrozenClock

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
PASSWORD = "correct-horse-battery-staple"
CSRF_HEADER = "x-csrf-token"


def _master(settings: Settings) -> str:
    return settings.master_key.get_secret_value()


def _auth(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def _error(response: httpx.Response) -> dict[str, object]:
    body = response.json()
    error = body["error"]
    assert isinstance(error, dict)
    return error


async def make_admin(
    container: Container,
    *,
    username: str = "alice",
    password: str = PASSWORD,
    role: AdminRole = AdminRole.OWNER,
    active: bool = True,
) -> AdminUser:
    now = container.clock.now()
    return await container.admins.create_admin(
        AdminUser(
            id=uuid4(),
            username=username,
            display_name=username.title(),
            role=role,
            password_hash=hash_password(password),
            active=active,
            created_at=now,
            updated_at=now,
            password_changed_at=now,
        )
    )


async def login(
    client: httpx.AsyncClient, username: str, password: str = PASSWORD
) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )


def csrf(client: httpx.AsyncClient) -> dict[str, str]:
    token = client.cookies.get("gw_admin_csrf")
    assert token is not None
    return {CSRF_HEADER: token}


async def test_login_sets_cookies_and_me_returns_the_role(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container = make_container(settings, clock=FrozenClock(NOW))
    await make_admin(container, role=AdminRole.OPERATOR)

    async with make_client(settings, container) as client:
        response = await login(client, "alice")
        me = await client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["role"] == "operator"
    assert response.json()["actor_type"] == "admin"

    set_cookies = response.headers.get_list("set-cookie")
    session_cookie = next(item for item in set_cookies if item.startswith("gw_admin_session="))
    csrf_cookie = next(item for item in set_cookies if item.startswith("gw_admin_csrf="))
    assert "httponly" in session_cookie.lower()
    assert "httponly" not in csrf_cookie.lower()

    assert me.status_code == 200
    assert me.json()["name"] == "alice"
    assert me.json()["role"] == "operator"


async def test_wrong_password_is_indistinguishable_and_throttled(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container = make_container(settings, clock=FrozenClock(NOW))
    await make_admin(container, username="target")

    async with make_client(settings, container) as client:
        wrong = await login(client, "target", "not-the-password")
        unknown = await login(client, "nobody", "not-the-password")
        for _ in range(4):
            await login(client, "target", "not-the-password")
        throttled = await login(client, "target", "not-the-password")

    assert wrong.status_code == 401
    assert _error(wrong)["code"] == "invalid_credentials"
    assert unknown.status_code == 401
    assert _error(unknown)["code"] == "invalid_credentials"
    assert throttled.status_code == 429
    assert _error(throttled)["code"] == "login_throttled"


async def test_disabled_admin_cannot_log_in(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container = make_container(settings, clock=FrozenClock(NOW))
    await make_admin(container, username="gone", active=False)

    async with make_client(settings, container) as client:
        response = await login(client, "gone")

    assert response.status_code == 401
    assert _error(response)["code"] == "invalid_credentials"


async def test_cookie_writes_require_the_csrf_header(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container = make_container(settings, clock=FrozenClock(NOW))
    await make_admin(container)

    async with make_client(settings, container) as client:
        await login(client, "alice")
        without = await client.post("/api/v1/tenants", json={"name": "acme"})
        with_token = await client.post(
            "/api/v1/tenants",
            json={"name": "acme"},
            headers=csrf(client),
        )
        read = await client.get("/api/v1/tenants")

    assert without.status_code == 403
    assert _error(without)["code"] == "csrf_failed"
    assert with_token.status_code == 201
    assert read.status_code == 200


async def test_logout_revokes_the_session(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container = make_container(settings, clock=FrozenClock(NOW))
    await make_admin(container)

    async with make_client(settings, container) as client:
        await login(client, "alice")
        token = csrf(client)
        logged_out = await client.post("/api/v1/auth/logout", headers=token)
        me = await client.get("/api/v1/auth/me")

    assert logged_out.status_code == 204
    assert me.status_code == 401


async def test_master_key_remains_a_break_glass_owner_path(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container = make_container(settings, clock=FrozenClock(NOW))

    async with make_client(settings, container) as client:
        response = await client.get("/api/v1/admins", headers=_auth(_master(settings)))

    assert response.status_code == 200


async def test_master_key_can_be_disabled(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    locked = settings.model_copy(update={"master_key_enabled": False})
    container = make_container(locked, clock=FrozenClock(NOW))
    await make_admin(container)

    async with make_client(locked, container) as client:
        response = await client.get("/api/v1/admins", headers=_auth(_master(settings)))

    assert response.status_code == 401
    assert _error(response)["code"] == "admin_auth_required"


async def test_startup_fails_when_the_master_key_is_disabled_and_no_owner_exists(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    locked = settings.model_copy(update={"master_key_enabled": False})
    container = make_container(locked, clock=FrozenClock(NOW))

    with pytest.raises(RuntimeError, match="no active owner"):
        async with make_client(locked, container):
            pass


async def test_roles_gate_writes_and_the_audit_trail(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container = make_container(settings, clock=FrozenClock(NOW))
    await make_admin(container, username="owner", role=AdminRole.OWNER)
    await make_admin(container, username="operator", role=AdminRole.OPERATOR)
    await make_admin(container, username="auditor", role=AdminRole.AUDITOR)

    async with make_client(settings, container) as owner_client:
        await login(owner_client, "owner")
        created = await owner_client.post(
            "/api/v1/tenants",
            json={"name": "acme"},
            headers=csrf(owner_client),
        )
        assert created.status_code == 201

    async with make_client(settings, container) as operator_client:
        await login(operator_client, "operator")
        operator_tenant = await operator_client.post(
            "/api/v1/tenants",
            json={"name": "beta"},
            headers=csrf(operator_client),
        )
        operator_admin_create = await operator_client.post(
            "/api/v1/admins",
            json={
                "username": "sneaky",
                "display_name": "Sneaky",
                "role": "owner",
                "password": PASSWORD,
            },
            headers=csrf(operator_client),
        )
        operator_audit = await operator_client.get("/api/v1/admin-audit")

    async with make_client(settings, container) as auditor_client:
        await login(auditor_client, "auditor")
        auditor_tenant_patch = await auditor_client.patch(
            "/api/v1/tenants/00000000-0000-0000-0000-000000000000",
            json={"monthly_token_quota": 10},
            headers=csrf(auditor_client),
        )
        auditor_read = await auditor_client.get("/api/v1/admin-audit")

    assert operator_tenant.status_code == 201
    assert operator_admin_create.status_code == 403
    assert _error(operator_admin_create)["code"] == "admin_forbidden"
    assert operator_audit.status_code == 403
    assert auditor_tenant_patch.status_code == 403
    assert auditor_read.status_code == 200


async def test_the_last_owner_cannot_be_demoted(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container = make_container(settings, clock=FrozenClock(NOW))
    owner = await make_admin(container, username="owner", role=AdminRole.OWNER)

    async with make_client(settings, container) as client:
        await login(client, "owner")
        response = await client.patch(
            f"/api/v1/admins/{owner.id}",
            json={"role": "auditor"},
            headers=csrf(client),
        )

    assert response.status_code == 409
    assert _error(response)["code"] == "last_owner_required"


async def test_admin_actions_are_audited_with_actor_and_diff(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container = make_container(settings, clock=FrozenClock(NOW))
    await make_admin(container, username="owner")
    tenant = await container.tenants.create_tenant(
        __import__("support").seed_tenant.__globals__["Tenant"](
            id=uuid4(),
            name="acme",
            created_at=NOW,
        )
    )

    async with make_client(settings, container) as client:
        await login(client, "owner")
        patched = await client.patch(
            f"/api/v1/tenants/{tenant.id}",
            json={"monthly_token_quota": 5000, "plan_tokens": 100000},
            headers=csrf(client),
        )
        events = await client.get(
            "/api/v1/admin-audit?action=tenant.updated",
        )

    assert patched.status_code == 200
    assert events.status_code == 200
    items = events.json()["items"]
    assert len(items) == 1
    event = items[0]
    assert event["actor_name"] == "owner"
    assert event["actor_type"] == "admin"
    assert event["target_type"] == "tenant"
    assert event["target_id"] == str(tenant.id)
    assert event["before"]["monthly_token_quota"] is None
    assert event["after"]["monthly_token_quota"] == 5000
    assert event["after"]["plan_tokens"] == 100000
    assert event["request_id"]


async def test_password_change_revokes_existing_sessions(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    container = make_container(settings, clock=FrozenClock(NOW))
    await make_admin(container, username="owner")
    bob = await make_admin(container, username="bob", role=AdminRole.OPERATOR)

    async with make_client(settings, container) as bob_client:
        await login(bob_client, "bob")

        async with make_client(settings, container) as owner_client:
            await login(owner_client, "owner")
            changed = await owner_client.patch(
                f"/api/v1/admins/{bob.id}",
                json={"password": "another-long-password"},
                headers=csrf(owner_client),
            )

        me = await bob_client.get("/api/v1/auth/me")

    assert changed.status_code == 200
    assert me.status_code == 401


async def test_bootstrap_creates_one_owner_and_is_idempotent(
    settings: Settings,
    make_container: Callable[..., Container],
    make_client: Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]],
) -> None:
    boot = settings.model_copy(
        update={
            "bootstrap_admin_username": "root",
            "bootstrap_admin_password": SecretStr("bootstrap-password-123"),
        }
    )
    container = make_container(boot, clock=FrozenClock(NOW))

    async with make_client(boot, container) as client:
        response = await login(client, "root", "bootstrap-password-123")

    assert response.status_code == 200
    assert response.json()["role"] == "owner"

    admins, total = await container.admins.list_admins(limit=10, offset=0)
    assert total == 1
    assert admins[0].username == "root"
