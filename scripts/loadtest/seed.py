"""Create the tenant, model, key, and optional billing state for a load run.

Uses the management API, so it exercises the same paths an operator would. Safe to
re-run: an existing tenant or model is reused; API keys are always newly minted.

Environment:
  GATEWAY_URL                 default http://127.0.0.1:4000
  ADMIN_USERNAME/ADMIN_PASSWORD   preferred (session + CSRF)
  GATEWAY_MASTER_KEY          fallback break-glass credential
  TENANT_NAME                 default loadtest
  MODEL_ID                    default loadtest-model
  UPSTREAM_MODEL              default stub-model
  PLAN_TOKENS                 optional monthly token plan
  MONTHLY_COST_BUDGET         optional cost budget
  ALLOW_OVERAGE               "true" to allow overage
  PRICE_INPUT_PER_MILLION     optional; creates a price version when set
  PRICE_OUTPUT_PER_MILLION    optional, defaults to the input price
"""

from __future__ import annotations

import os
import secrets
import sys

import httpx

BASE_URL = os.environ.get("GATEWAY_URL", "http://127.0.0.1:4000").rstrip("/")
TENANT_NAME = os.environ.get("TENANT_NAME", "loadtest")
MODEL_ID = os.environ.get("MODEL_ID", "loadtest-model")
UPSTREAM_MODEL = os.environ.get("UPSTREAM_MODEL", "stub-model")


def _client() -> tuple[httpx.Client, dict[str, str]]:
    client = httpx.Client(base_url=BASE_URL, timeout=30)
    username = os.environ.get("ADMIN_USERNAME")
    password = os.environ.get("ADMIN_PASSWORD")
    if username and password:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        response.raise_for_status()
        csrf = client.cookies.get("gw_admin_csrf")
        if csrf is None:
            raise SystemExit("login succeeded but no CSRF cookie was set")
        return client, {"x-csrf-token": csrf}

    master = os.environ.get("GATEWAY_MASTER_KEY")
    if not master:
        raise SystemExit("set ADMIN_USERNAME/ADMIN_PASSWORD or GATEWAY_MASTER_KEY")
    return client, {"Authorization": f"Bearer {master}"}


def _ensure_tenant(client: httpx.Client, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/tenants",
        headers=headers,
        json={"name": TENANT_NAME},
    )
    if response.status_code not in (201, 409):
        raise SystemExit(f"create tenant failed: {response.status_code} {response.text}")

    listing = client.get("/api/v1/tenants", headers=headers, params={"limit": 100})
    listing.raise_for_status()
    for item in listing.json()["items"]:
        if item["name"] == TENANT_NAME:
            return str(item["id"])
    raise SystemExit("tenant was created but not found in the listing")


def _configure_billing(client: httpx.Client, headers: dict[str, str], tenant_id: str) -> None:
    patch: dict[str, object] = {}
    plan = os.environ.get("PLAN_TOKENS")
    if plan:
        patch["plan_tokens"] = int(plan)
        patch["plan_allow_overage"] = os.environ.get("ALLOW_OVERAGE", "false").lower() == "true"
    budget = os.environ.get("MONTHLY_COST_BUDGET")
    if budget:
        patch["monthly_cost_budget"] = budget
    if not patch:
        return
    response = client.patch(f"/api/v1/tenants/{tenant_id}", headers=headers, json=patch)
    if response.status_code != 200:
        raise SystemExit(f"set billing failed: {response.status_code} {response.text}")


def _ensure_model(client: httpx.Client, headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/models",
        headers=headers,
        json={
            "id": MODEL_ID,
            "provider": "openai",
            "upstream_model": UPSTREAM_MODEL,
            "enabled": True,
        },
    )
    if response.status_code not in (201, 409):
        raise SystemExit(f"register model failed: {response.status_code} {response.text}")


def _maybe_price(client: httpx.Client, headers: dict[str, str]) -> None:
    input_price = os.environ.get("PRICE_INPUT_PER_MILLION")
    if not input_price:
        return
    output_price = os.environ.get("PRICE_OUTPUT_PER_MILLION", input_price)
    response = client.post(
        f"/api/v1/models/{MODEL_ID}/prices",
        headers=headers,
        json={
            "input_per_million": input_price,
            "output_per_million": output_price,
        },
    )
    # 409 means this run already has a price at the same instant; reuse it.
    if response.status_code not in (201, 409):
        raise SystemExit(f"create price failed: {response.status_code} {response.text}")


def _create_key(client: httpx.Client, headers: dict[str, str], tenant_id: str) -> str:
    name = f"loadtest-{secrets.token_hex(4)}"
    response = client.post(
        "/api/v1/keys",
        headers=headers,
        json={"name": name, "tenant_id": tenant_id},
    )
    if response.status_code != 201:
        raise SystemExit(f"create key failed: {response.status_code} {response.text}")
    return str(response.json()["key"])


def main() -> int:
    client, headers = _client()
    try:
        tenant_id = _ensure_tenant(client, headers)
        _configure_billing(client, headers, tenant_id)
        _ensure_model(client, headers)
        _maybe_price(client, headers)
        key = _create_key(client, headers, tenant_id)
    finally:
        client.close()

    print(f"export GATEWAY_KEY={key}")
    print(f"export GATEWAY_MODEL={MODEL_ID}")
    print(f"export TENANT_ID={tenant_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
