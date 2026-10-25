from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx

from llm_gateway.app import create_app
from llm_gateway.auth.keys import hash_api_key
from llm_gateway.config import Settings
from llm_gateway.container import Container
from llm_gateway.providers.base import ProviderName
from llm_gateway.providers.fake import FakeProvider
from llm_gateway.providers.openai import OpenAIProvider
from llm_gateway.providers.registry import ProviderRegistry
from llm_gateway.providers.retry import RetryPolicy
from support import (
    FROZEN_NOW,
    FrozenClock,
    seed_api_key,
    seed_model,
    seed_tenant,
)

FAKE_MODEL = "fake-model"
UPSTREAM_MODEL = "upstream-fake-model"
USER_MESSAGE = {"role": "user", "content": "hello"}


class SteppingClock:
    """Clock that hands out increasing timestamps so ordering is deterministic."""

    def __init__(
        self,
        *,
        start: datetime = FROZEN_NOW,
        step: timedelta = timedelta(seconds=1),
    ) -> None:
        self._now = start
        self._step = step

    def now(self) -> datetime:
        current = self._now
        self._now += self._step
        return current


def _master(settings: Settings) -> str:
    return settings.master_key.get_secret_value()


def _auth(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def _registry(clock: Any) -> ProviderRegistry:
    return ProviderRegistry({ProviderName.FAKE: FakeProvider(clock=clock)})


def _deepseek_registry() -> ProviderRegistry:
    return ProviderRegistry(
        {
            ProviderName.DEEPSEEK: OpenAIProvider(
                name=ProviderName.DEEPSEEK,
                api_key="sk-deepseek-test",
                base_url="https://api.deepseek.com",
                timeout=httpx.Timeout(5.0),
                retry_policy=RetryPolicy(max_attempts=1),
            )
        }
    )


def _error(response: httpx.Response) -> dict[str, Any]:
    body = response.json()
    error = body["error"]
    assert isinstance(error, dict)
    return error


async def test_admin_routes_require_the_master_key(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    clock = FrozenClock()
    container = make_container(settings, providers=_registry(clock), clock=clock)
    inference_key = await seed_api_key(container)

    async with make_client(settings, container) as client:
        missing = await client.get("/api/v1/keys")
        wrong = await client.get("/api/v1/keys", headers=_auth("wrong-master-key"))
        inference = await client.get("/api/v1/keys", headers=_auth(inference_key))
        master = await client.get("/api/v1/keys", headers=_auth(_master(settings)))

    assert missing.status_code == 401
    assert _error(missing)["code"] == "master_key_required"
    assert wrong.status_code == 401
    assert _error(wrong)["code"] == "invalid_api_key"
    assert inference.status_code == 401
    assert _error(inference)["code"] == "invalid_api_key"
    assert master.status_code == 200


async def test_create_api_key_returns_plaintext_once_and_stores_only_hash(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    clock = FrozenClock()
    container = make_container(settings, clock=clock)
    tenant = await seed_tenant(container)

    async with make_client(settings, container) as client:
        created = await client.post(
            "/api/v1/keys",
            json={"name": "  ci key  ", "tenant_id": str(tenant.id)},
            headers=_auth(_master(settings)),
        )
        listing = await client.get("/api/v1/keys", headers=_auth(_master(settings)))

    assert created.status_code == 201
    body = created.json()
    secret = body["key"]
    assert secret.startswith("sk-gw-")
    assert body["key_prefix"] == secret[: len(body["key_prefix"])]
    assert body["name"] == "ci key"
    assert body["tenant_id"] == str(tenant.id)
    assert body["expires_at"] is None

    assert listing.status_code == 200
    listed = listing.json()
    assert secret not in listing.text
    assert all("key" not in item for item in listed["items"])
    assert set(listed["items"][0]) == {
        "id",
        "tenant_id",
        "name",
        "key_prefix",
        "created_at",
        "expires_at",
        "revoked_at",
        "last_used_at",
    }

    record = await container.api_keys.get_key(UUID(body["id"]))
    assert record is not None
    assert record.key_hash == hash_api_key(secret)
    assert secret not in (record.name, record.key_prefix, record.key_hash)


async def test_created_key_authenticates_inference_requests(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    clock = FrozenClock()
    container = make_container(settings, providers=_registry(clock), clock=clock)
    tenant = await seed_tenant(container)
    await seed_model(
        container,
        model_id=FAKE_MODEL,
        provider=ProviderName.FAKE,
        upstream_model=UPSTREAM_MODEL,
    )

    async with make_client(settings, container) as client:
        created = await client.post(
            "/api/v1/keys",
            json={"name": "inference key", "tenant_id": str(tenant.id)},
            headers=_auth(_master(settings)),
        )
        secret = created.json()["key"]
        completion = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE]},
            headers=_auth(secret),
        )

    assert created.status_code == 201
    assert completion.status_code == 200
    assert completion.json()["choices"][0]["message"]["content"] == ("fake completion for: hello")


async def test_create_api_key_rejects_invalid_name_and_expiry(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    clock = FrozenClock()
    container = make_container(settings, clock=clock)
    tenant = await seed_tenant(container)
    tenant_id = str(tenant.id)

    async with make_client(settings, container) as client:
        blank = await client.post(
            "/api/v1/keys",
            json={"name": "   ", "tenant_id": tenant_id},
            headers=_auth(_master(settings)),
        )
        naive = await client.post(
            "/api/v1/keys",
            json={"name": "key", "tenant_id": tenant_id, "expires_at": "2026-01-02T03:04:05"},
            headers=_auth(_master(settings)),
        )
        past = await client.post(
            "/api/v1/keys",
            json={"name": "key", "tenant_id": tenant_id, "expires_at": "2020-01-01T00:00:00Z"},
            headers=_auth(_master(settings)),
        )

    for response in (blank, naive, past):
        assert response.status_code == 400
        assert _error(response)["code"] == "invalid_request_body"
    assert _error(past)["param"] == "expires_at"


async def test_list_api_keys_paginates_and_orders_newest_first(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    clock = SteppingClock()
    container = make_container(settings, clock=clock)
    tenant = await seed_tenant(container)

    async with make_client(settings, container) as client:
        for index in range(3):
            created = await client.post(
                "/api/v1/keys",
                json={"name": f"key-{index}", "tenant_id": str(tenant.id)},
                headers=_auth(_master(settings)),
            )
            assert created.status_code == 201

        first_page = await client.get(
            "/api/v1/keys?limit=2&offset=0",
            headers=_auth(_master(settings)),
        )
        second_page = await client.get(
            "/api/v1/keys?limit=2&offset=2",
            headers=_auth(_master(settings)),
        )
        empty_page = await client.get(
            "/api/v1/keys?limit=2&offset=3",
            headers=_auth(_master(settings)),
        )

    body = first_page.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert [item["name"] for item in body["items"]] == ["key-2", "key-1"]

    assert [item["name"] for item in second_page.json()["items"]] == ["key-0"]
    assert second_page.json()["total"] == 3

    assert empty_page.json()["items"] == []
    assert empty_page.json()["total"] == 3


async def test_revoke_api_key_removes_inference_access(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    clock = FrozenClock()
    container = make_container(settings, providers=_registry(clock), clock=clock)
    tenant = await seed_tenant(container)
    await seed_model(
        container,
        model_id=FAKE_MODEL,
        provider=ProviderName.FAKE,
        upstream_model=UPSTREAM_MODEL,
    )
    master_auth = _auth(_master(settings))

    async with make_client(settings, container) as client:
        created = await client.post(
            "/api/v1/keys",
            json={"name": "revoked key", "tenant_id": str(tenant.id)},
            headers=master_auth,
        )
        key_id = created.json()["id"]
        secret = created.json()["key"]

        revoked = await client.delete(f"/api/v1/keys/{key_id}", headers=master_auth)
        inference = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE]},
            headers=_auth(secret),
        )
        revoked_again = await client.delete(f"/api/v1/keys/{key_id}", headers=master_auth)
        unknown = await client.delete(f"/api/v1/keys/{uuid4()}", headers=master_auth)

    assert revoked.status_code == 204
    assert revoked.content == b""
    assert inference.status_code == 401
    assert _error(inference)["code"] == "invalid_api_key"
    assert revoked_again.status_code == 404
    assert _error(revoked_again)["code"] == "key_not_found"
    assert unknown.status_code == 404
    assert _error(unknown)["code"] == "key_not_found"


async def test_create_model_returns_detail_and_rejects_conflicts(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    clock = FrozenClock()
    container = make_container(settings, providers=_registry(clock), clock=clock)
    master_auth = _auth(_master(settings))
    payload = {
        "id": "sales-model",
        "provider": "fake",
        "upstream_model": " upstream-sales ",
    }

    async with make_client(settings, container) as client:
        created = await client.post("/api/v1/models", json=payload, headers=master_auth)
        duplicate = await client.post("/api/v1/models", json=payload, headers=master_auth)
        unconfigured = await client.post(
            "/api/v1/models",
            json={"id": "openai-model", "provider": "openai", "upstream_model": "gpt-4"},
            headers=master_auth,
        )
        slash_id = await client.post(
            "/api/v1/models",
            json={"id": "bad/model", "provider": "fake", "upstream_model": "up"},
            headers=master_auth,
        )
        space_id = await client.post(
            "/api/v1/models",
            json={"id": "bad id", "provider": "fake", "upstream_model": "up"},
            headers=master_auth,
        )

    assert created.status_code == 201
    body = created.json()
    assert body["id"] == "sales-model"
    assert body["provider"] == "fake"
    assert body["upstream_model"] == "upstream-sales"
    assert body["enabled"] is True
    assert body["created_at"]

    assert duplicate.status_code == 409
    assert _error(duplicate)["code"] == "duplicate_model"
    assert _error(duplicate)["param"] == "id"

    assert unconfigured.status_code == 400
    assert _error(unconfigured)["code"] == "provider_not_configured"
    assert _error(unconfigured)["param"] == "provider"
    assert "openai" in _error(unconfigured)["message"]

    for invalid in (slash_id, space_id):
        assert invalid.status_code == 400
        assert _error(invalid)["code"] == "invalid_request_body"


async def test_create_model_accepts_registered_deepseek_provider(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, providers=_deepseek_registry(), clock=FrozenClock())

    async with make_client(settings, container) as client:
        created = await client.post(
            "/api/v1/models",
            json={
                "id": "deepseek-flash",
                "provider": "deepseek",
                "upstream_model": "deepseek-flash",
            },
            headers=_auth(_master(settings)),
        )

    assert created.status_code == 201
    body = created.json()
    assert body["id"] == "deepseek-flash"
    assert body["provider"] == "deepseek"
    assert body["upstream_model"] == "deepseek-flash"


async def test_create_model_rejects_unregistered_deepseek_provider(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    clock = FrozenClock()
    container = make_container(settings, providers=_registry(clock), clock=clock)

    async with make_client(settings, container) as client:
        response = await client.post(
            "/api/v1/models",
            json={
                "id": "deepseek-flash",
                "provider": "deepseek",
                "upstream_model": "deepseek-flash",
            },
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 400
    error = _error(response)
    assert error["code"] == "provider_not_configured"
    assert error["param"] == "provider"
    assert "deepseek" in error["message"]


async def test_list_models_includes_disabled_models_and_paginates(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    clock = SteppingClock()
    container = make_container(settings, providers=_registry(clock), clock=clock)
    master_auth = _auth(_master(settings))

    async with make_client(settings, container) as client:
        for model_id, enabled in (
            ("model-a", True),
            ("model-b", False),
            ("model-c", True),
        ):
            created = await client.post(
                "/api/v1/models",
                json={
                    "id": model_id,
                    "provider": "fake",
                    "upstream_model": f"upstream-{model_id}",
                    "enabled": enabled,
                },
                headers=master_auth,
            )
            assert created.status_code == 201

        first_page = await client.get(
            "/api/v1/models?limit=2&offset=0",
            headers=master_auth,
        )
        second_page = await client.get(
            "/api/v1/models?limit=2&offset=2",
            headers=master_auth,
        )

    body = first_page.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == ["model-c", "model-b"]
    assert body["items"][1]["enabled"] is False

    assert [item["id"] for item in second_page.json()["items"]] == ["model-a"]
    assert second_page.json()["total"] == 3


async def test_delete_model_removes_it_from_admin_and_inference_lists(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    clock = FrozenClock()
    container = make_container(settings, providers=_registry(clock), clock=clock)
    inference_key = await seed_api_key(container)
    master_auth = _auth(_master(settings))

    async with make_client(settings, container) as client:
        created = await client.post(
            "/api/v1/models",
            json={"id": "doomed-model", "provider": "fake", "upstream_model": "upstream"},
            headers=master_auth,
        )
        assert created.status_code == 201

        deleted = await client.delete("/api/v1/models/doomed-model", headers=master_auth)
        admin_list = await client.get("/api/v1/models", headers=master_auth)
        inference_list = await client.get("/v1/models", headers=_auth(inference_key))
        unknown = await client.delete("/api/v1/models/missing-model", headers=master_auth)

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert admin_list.json()["items"] == []
    assert admin_list.json()["total"] == 0
    assert inference_list.json()["data"] == []
    assert unknown.status_code == 404
    assert _error(unknown)["code"] == "model_not_found"


async def test_error_responses_keep_openai_envelope_and_request_id(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    clock = FrozenClock()
    container = make_container(settings, clock=clock)
    master_auth = _auth(_master(settings))

    async with make_client(settings, container) as client:
        responses = [
            await client.get("/api/v1/keys"),
            await client.delete(f"/api/v1/keys/{uuid4()}", headers=master_auth),
            await client.post("/api/v1/keys", json={"name": ""}, headers=master_auth),
        ]

    for response in responses:
        error = _error(response)
        assert {"message", "type", "param", "code", "request_id"} <= set(error)
        assert isinstance(error["request_id"], str)
        assert error["request_id"]
        assert response.headers["x-request-id"] == error["request_id"]


async def test_every_admin_route_rejects_missing_and_inference_credentials(
    make_container: Callable[..., Container],
    settings: Settings,
) -> None:
    container = make_container(settings)
    app = create_app(settings=settings, container=container)
    inference_key = await seed_api_key(container)

    targets: list[tuple[str, str]] = []
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api/v1/"):
            continue
        concrete = path.replace("{key_id}", str(uuid4())).replace("{model_id}", "missing-model")
        targets.extend((method.upper(), concrete) for method in operations)

    assert targets, "expected the management routes to be mounted"
    assert ("GET", "/api/v1/usage/summary") in targets
    assert ("GET", "/api/v1/usage/by-key") in targets
    assert ("GET", "/api/v1/usage/series") in targets
    assert any(path == "/api/v1/tenants" for _, path in targets), (
        "tenant routes must be covered by the credential boundary test"
    )

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for method, path in targets:
            anonymous = await client.request(method, path, json={})
            inference = await client.request(method, path, json={}, headers=_auth(inference_key))

            assert anonymous.status_code == 401, f"{method} {path} must require the master key"
            assert _error(anonymous)["code"] == "master_key_required"
            assert inference.status_code == 401, f"{method} {path} must reject inference keys"
            assert _error(inference)["code"] == "invalid_api_key"


async def test_create_tenant_returns_detail_and_rejects_duplicates(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=SteppingClock())
    master_auth = _auth(_master(settings))

    async with make_client(settings, container) as client:
        created = await client.post(
            "/api/v1/tenants",
            json={"name": "  acme  "},
            headers=master_auth,
        )
        duplicate = await client.post(
            "/api/v1/tenants",
            json={"name": "acme"},
            headers=master_auth,
        )

    assert created.status_code == 201
    body = created.json()
    assert set(body) == {
        "id",
        "name",
        "created_at",
        "monthly_token_quota",
        "requests_per_minute",
    }
    assert body["name"] == "acme"
    assert UUID(body["id"])
    assert body["created_at"]

    assert duplicate.status_code == 409
    error = _error(duplicate)
    assert error["code"] == "duplicate_tenant"
    assert error["param"] == "name"
    assert "acme" in error["message"]


async def test_create_tenant_rejects_blank_and_too_long_names(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    master_auth = _auth(_master(settings))

    async with make_client(settings, container) as client:
        blank = await client.post(
            "/api/v1/tenants",
            json={"name": "   "},
            headers=master_auth,
        )
        too_long = await client.post(
            "/api/v1/tenants",
            json={"name": "x" * 101},
            headers=master_auth,
        )

    for response in (blank, too_long):
        assert response.status_code == 400
        assert _error(response)["code"] == "invalid_request_body"


async def test_list_tenants_paginates_newest_first(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=SteppingClock())
    master_auth = _auth(_master(settings))

    async with make_client(settings, container) as client:
        for index in range(3):
            created = await client.post(
                "/api/v1/tenants",
                json={"name": f"tenant-{index}"},
                headers=master_auth,
            )
            assert created.status_code == 201

        first_page = await client.get(
            "/api/v1/tenants?limit=2&offset=0",
            headers=master_auth,
        )
        second_page = await client.get(
            "/api/v1/tenants?limit=2&offset=2",
            headers=master_auth,
        )

    body = first_page.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert [item["name"] for item in body["items"]] == ["tenant-2", "tenant-1"]
    assert [item["name"] for item in second_page.json()["items"]] == ["tenant-0"]
    assert second_page.json()["total"] == 3


async def test_create_api_key_requires_a_tenant_id(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())

    async with make_client(settings, container) as client:
        response = await client.post(
            "/api/v1/keys",
            json={"name": "key"},
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 400
    assert _error(response)["code"] == "invalid_request_body"


async def test_create_api_key_rejects_unknown_tenant(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    unknown_tenant_id = uuid4()

    async with make_client(settings, container) as client:
        response = await client.post(
            "/api/v1/keys",
            json={"name": "key", "tenant_id": str(unknown_tenant_id)},
            headers=_auth(_master(settings)),
        )

    assert response.status_code == 404
    error = _error(response)
    assert error["code"] == "tenant_not_found"
    assert error["param"] == "tenant_id"
    assert str(unknown_tenant_id) in error["message"]


async def test_list_api_keys_filters_by_tenant_and_isolates_other_tenants(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=SteppingClock())
    tenant_a = await seed_tenant(container, name="tenant-a")
    tenant_b = await seed_tenant(container, name="tenant-b")
    master_auth = _auth(_master(settings))

    async with make_client(settings, container) as client:
        for name, tenant in (("a-key", tenant_a), ("b-key", tenant_b)):
            created = await client.post(
                "/api/v1/keys",
                json={"name": name, "tenant_id": str(tenant.id)},
                headers=master_auth,
            )
            assert created.status_code == 201
            assert created.json()["tenant_id"] == str(tenant.id)

        page_a = await client.get(
            f"/api/v1/keys?tenant_id={tenant_a.id}",
            headers=master_auth,
        )
        page_b = await client.get(
            f"/api/v1/keys?tenant_id={tenant_b.id}",
            headers=master_auth,
        )
        page_unknown = await client.get(
            f"/api/v1/keys?tenant_id={uuid4()}",
            headers=master_auth,
        )

    body_a = page_a.json()
    assert body_a["total"] == 1
    assert body_a["tenant_id"] == str(tenant_a.id)
    assert [item["name"] for item in body_a["items"]] == ["a-key"]
    assert body_a["items"][0]["tenant_id"] == str(tenant_a.id)

    body_b = page_b.json()
    assert body_b["total"] == 1
    assert [item["name"] for item in body_b["items"]] == ["b-key"]

    assert page_unknown.status_code == 404
    assert _error(page_unknown)["code"] == "tenant_not_found"


async def test_tenant_key_authenticates_inference_and_health_is_unaffected(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    clock = FrozenClock()
    container = make_container(settings, providers=_registry(clock), clock=clock)
    await seed_model(
        container,
        model_id=FAKE_MODEL,
        provider=ProviderName.FAKE,
        upstream_model=UPSTREAM_MODEL,
    )
    master_auth = _auth(_master(settings))

    async with make_client(settings, container) as client:
        tenant = await client.post(
            "/api/v1/tenants",
            json={"name": "e2e-tenant"},
            headers=master_auth,
        )
        assert tenant.status_code == 201
        tenant_id = tenant.json()["id"]

        created = await client.post(
            "/api/v1/keys",
            json={"name": "e2e-key", "tenant_id": tenant_id},
            headers=master_auth,
        )
        assert created.status_code == 201
        assert created.json()["tenant_id"] == tenant_id
        secret = created.json()["key"]

        completion = await client.post(
            "/v1/chat/completions",
            json={"model": FAKE_MODEL, "messages": [USER_MESSAGE]},
            headers=_auth(secret),
        )
        readyz = await client.get("/readyz")

    assert completion.status_code == 200
    assert readyz.status_code == 200


async def test_create_tenant_persists_limits_and_lists_them(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=SteppingClock())
    master = _auth(_master(settings))

    async with make_client(settings, container) as client:
        created = await client.post(
            "/api/v1/tenants",
            json={
                "name": "limited",
                "monthly_token_quota": 1000,
                "requests_per_minute": 5,
            },
            headers=master,
        )
        listing = await client.get("/api/v1/tenants", headers=master)

    assert created.status_code == 201
    body = created.json()
    assert body["monthly_token_quota"] == 1000
    assert body["requests_per_minute"] == 5

    item = listing.json()["items"][0]
    assert item["monthly_token_quota"] == 1000
    assert item["requests_per_minute"] == 5


async def test_patch_tenant_limits_replaces_clears_and_keeps_omitted_fields(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=SteppingClock())
    master = _auth(_master(settings))

    async with make_client(settings, container) as client:
        created = await client.post(
            "/api/v1/tenants",
            json={"name": "patch-me"},
            headers=master,
        )
        tenant_id = created.json()["id"]

        both = await client.patch(
            f"/api/v1/tenants/{tenant_id}",
            json={"monthly_token_quota": 100, "requests_per_minute": 3},
            headers=master,
        )
        one = await client.patch(
            f"/api/v1/tenants/{tenant_id}",
            json={"monthly_token_quota": 200},
            headers=master,
        )
        cleared = await client.patch(
            f"/api/v1/tenants/{tenant_id}",
            json={"monthly_token_quota": None},
            headers=master,
        )
        noop = await client.patch(
            f"/api/v1/tenants/{tenant_id}",
            json={},
            headers=master,
        )

    assert both.status_code == 200
    assert both.json()["monthly_token_quota"] == 100
    assert both.json()["requests_per_minute"] == 3

    assert one.json()["monthly_token_quota"] == 200
    assert one.json()["requests_per_minute"] == 3

    assert cleared.json()["monthly_token_quota"] is None
    assert cleared.json()["requests_per_minute"] == 3

    assert noop.status_code == 200
    assert noop.json()["monthly_token_quota"] is None
    assert noop.json()["requests_per_minute"] == 3


async def test_patch_tenant_limits_validates_target_and_values(
    make_container: Callable[..., Container],
    make_client: Callable[..., Any],
    settings: Settings,
) -> None:
    container = make_container(settings, clock=FrozenClock())
    master = _auth(_master(settings))

    async with make_client(settings, container) as client:
        unknown = await client.patch(
            f"/api/v1/tenants/{uuid4()}",
            json={"requests_per_minute": 1},
            headers=master,
        )
        created = await client.post(
            "/api/v1/tenants",
            json={"name": "zero-limits"},
            headers=master,
        )
        tenant_id = created.json()["id"]
        zero = await client.patch(
            f"/api/v1/tenants/{tenant_id}",
            json={"monthly_token_quota": 0},
            headers=master,
        )
        negative = await client.patch(
            f"/api/v1/tenants/{tenant_id}",
            json={"requests_per_minute": -1},
            headers=master,
        )

    assert unknown.status_code == 404
    assert _error(unknown)["code"] == "tenant_not_found"
    assert _error(unknown)["param"] == "tenant_id"

    for response in (zero, negative):
        assert response.status_code == 400
        assert _error(response)["code"] == "invalid_request_body"
