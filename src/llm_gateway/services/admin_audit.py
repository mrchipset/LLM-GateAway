"""Admin action audit.

Auditing is best effort: the action has already happened by the time we write, so
blocking the response would misreport it. A write failure is therefore loud in logs and
counted in metrics, and the gap is deliberate rather than silent.

Payload rules: record business fields only (limits, roles, policy, price values). Never
record passwords, password hashes, session tokens, key plaintext, or key hashes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from uuid import uuid4

from llm_gateway.auth.admin_auth import AdminPrincipal
from llm_gateway.container import Container
from llm_gateway.logging import get_logger
from llm_gateway.metrics import current_metrics
from llm_gateway.request_context import get_request_id
from llm_gateway.storage.repositories import AdminAuditEvent

logger = get_logger(__name__)

ADMIN_AUDIT_TIMEOUT_SECONDS = 2.0


def _event(
    *,
    principal: AdminPrincipal,
    action: str,
    target_type: str,
    target_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    now: datetime,
) -> AdminAuditEvent:
    return AdminAuditEvent(
        id=uuid4(),
        actor_type=principal.actor_type,
        actor_id=principal.admin_id,
        actor_name=principal.name,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=before,
        after=after,
        request_id=get_request_id(),
        created_at=now,
    )


async def record_admin_event_safely(
    *,
    container: Container,
    principal: AdminPrincipal,
    action: str,
    target_type: str,
    target_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    timeout_seconds: float = ADMIN_AUDIT_TIMEOUT_SECONDS,
) -> None:
    try:
        async with asyncio.timeout(timeout_seconds):
            await container.admin_audit.record(
                _event(
                    principal=principal,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    before=before,
                    after=after,
                    now=container.clock.now(),
                )
            )
    except Exception as exc:
        current_metrics().admin_audit_failures.add(1)
        logger.warning(
            "admin_audit_write_failed",
            extra={
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "actor": principal.name,
                "error": type(exc).__name__,
            },
        )


def tenant_snapshot(tenant: Any) -> dict[str, object]:
    """Business fields only, so audit rows are safe to export."""
    return {
        "name": tenant.name,
        "monthly_token_quota": tenant.monthly_token_quota,
        "requests_per_minute": tenant.requests_per_minute,
        "audit_enabled": tenant.audit_enabled,
        "model_access_mode": str(tenant.model_access_mode),
        "plan_tokens": tenant.plan_tokens,
        "plan_allow_overage": tenant.plan_allow_overage,
        "monthly_cost_budget": (
            str(tenant.monthly_cost_budget) if tenant.monthly_cost_budget is not None else None
        ),
    }


def model_snapshot(model: Any) -> dict[str, object]:
    return {
        "provider": model.provider.value,
        "upstream_model": model.upstream_model,
        "enabled": model.enabled,
    }


def price_snapshot(price: Any) -> dict[str, object]:
    return {
        "input_per_million": str(price.input_per_million),
        "cached_input_per_million": (
            str(price.cached_input_per_million)
            if price.cached_input_per_million is not None
            else None
        ),
        "output_per_million": str(price.output_per_million),
        "currency": price.currency,
        "effective_from": price.effective_from.isoformat(),
    }


def admin_snapshot(admin: Any) -> dict[str, object]:
    return {
        "username": admin.username,
        "display_name": admin.display_name,
        "role": str(admin.role),
        "active": admin.active,
    }


def key_snapshot(key: Any) -> dict[str, object]:
    """Key metadata only; never the plaintext or the hash."""
    return {
        "name": key.name,
        "tenant_id": str(key.tenant_id),
        "key_prefix": key.key_prefix,
        "expires_at": key.expires_at.isoformat() if key.expires_at is not None else None,
        "revoked": key.revoked_at is not None,
    }


def deployment_snapshot(deployment: Any) -> dict[str, object]:
    return {
        "name": deployment.name,
        "provider": deployment.provider.value,
        "upstream_model": deployment.upstream_model,
        "weight": deployment.weight,
        "enabled": deployment.enabled,
        "credential_env": deployment.credential_env,
        "base_url": deployment.base_url,
    }
