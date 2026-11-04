"""Audit retention cleanup.

The cleanup lane deletes audited requests older than a per-tenant cutoff and then
removes sessions that no longer have any requests. It runs out of band with the
inference path and is deliberately sequential per tenant so that a large backlog
cannot saturate the database.

A tenant whose effective retention is zero is on legal hold and is skipped without
touching storage. A failure for one tenant is recorded, counted and logged; it must
never prevent the remaining tenants from being cleaned.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from llm_gateway.clock import Clock
from llm_gateway.config import Settings
from llm_gateway.logging import get_logger
from llm_gateway.metrics import current_metrics
from llm_gateway.storage.repositories import AuditRepository, Tenant, TenantRepository

logger = get_logger(__name__)

_TENANT_PAGE_SIZE = 200

CleanupOutcome = Literal["completed", "skipped", "failed"]


class _DeleteBatch(Protocol):
    async def __call__(self, *, tenant_id: UUID, cutoff: datetime, batch_size: int) -> int: ...


@dataclass(frozen=True, slots=True)
class TenantCleanupOutcome:
    """Result of one tenant's cleanup attempt."""

    tenant_id: UUID
    outcome: CleanupOutcome
    effective_days: int
    cutoff: datetime | None
    requests_deleted: int
    sessions_deleted: int
    truncated: bool
    dry_run: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class CleanupReport:
    """Aggregate result of one cleanup invocation."""

    outcomes: tuple[TenantCleanupOutcome, ...]
    requests_deleted: int
    sessions_deleted: int
    failed: int
    skipped: int
    truncated: bool
    dry_run: bool

    def to_dict(self) -> dict[str, object]:
        """JSON-safe view for operator output; contains no audit content."""
        return {
            "dry_run": self.dry_run,
            "tenants": len(self.outcomes),
            "requests_deleted": self.requests_deleted,
            "sessions_deleted": self.sessions_deleted,
            "failed": self.failed,
            "skipped": self.skipped,
            "truncated": self.truncated,
            "outcomes": [
                {
                    "tenant_id": str(outcome.tenant_id),
                    "outcome": outcome.outcome,
                    "effective_days": outcome.effective_days,
                    "cutoff": outcome.cutoff.isoformat() if outcome.cutoff is not None else None,
                    "requests_deleted": outcome.requests_deleted,
                    "sessions_deleted": outcome.sessions_deleted,
                    "truncated": outcome.truncated,
                    "dry_run": outcome.dry_run,
                    "reason": outcome.reason,
                }
                for outcome in self.outcomes
            ],
        }


class AuditRetentionService:
    def __init__(
        self,
        settings: Settings,
        audit: AuditRepository,
        tenants: TenantRepository,
        clock: Clock,
    ) -> None:
        self._settings = settings
        self._audit = audit
        self._tenants = tenants
        self._clock = clock

    def effective_days(self, tenant: Tenant) -> int:
        """Tenant override when set, otherwise the global default."""
        if tenant.audit_retention_days is not None:
            return tenant.audit_retention_days
        return self._settings.audit_retention_days

    async def run(
        self,
        *,
        tenant_ids: Sequence[UUID] | None = None,
        dry_run: bool = False,
        batch_size: int = 5000,
        max_batches: int = 100,
    ) -> CleanupReport:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if max_batches < 1:
            raise ValueError("max_batches must be >= 1")

        now = self._clock.now()
        if now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")

        tenants = await self._resolve_tenants(tenant_ids)
        outcomes = [
            await self._run_tenant(
                tenant_id,
                tenant,
                now=now,
                dry_run=dry_run,
                batch_size=batch_size,
                max_batches=max_batches,
            )
            for tenant_id, tenant in tenants
        ]
        report = CleanupReport(
            outcomes=tuple(outcomes),
            requests_deleted=sum(outcome.requests_deleted for outcome in outcomes),
            sessions_deleted=sum(outcome.sessions_deleted for outcome in outcomes),
            failed=sum(1 for outcome in outcomes if outcome.outcome == "failed"),
            skipped=sum(1 for outcome in outcomes if outcome.outcome == "skipped"),
            truncated=any(outcome.truncated for outcome in outcomes),
            dry_run=dry_run,
        )
        logger.info(
            "audit_cleanup_summary",
            extra={
                "tenants": len(outcomes),
                "requests_deleted": report.requests_deleted,
                "sessions_deleted": report.sessions_deleted,
                "failed": report.failed,
                "skipped": report.skipped,
                "truncated": report.truncated,
                "dry_run": dry_run,
            },
        )
        return report

    async def _resolve_tenants(
        self, tenant_ids: Sequence[UUID] | None
    ) -> list[tuple[UUID, Tenant | None]]:
        if tenant_ids is None:
            return [(tenant.id, tenant) for tenant in await self._all_tenants()]
        return [(tenant_id, await self._tenants.get_tenant(tenant_id)) for tenant_id in tenant_ids]

    async def _all_tenants(self) -> list[Tenant]:
        tenants: list[Tenant] = []
        offset = 0
        while True:
            page, total = await self._tenants.list_tenants(limit=_TENANT_PAGE_SIZE, offset=offset)
            tenants.extend(page)
            offset += len(page)
            if not page or offset >= total:
                return tenants

    async def _run_tenant(
        self,
        tenant_id: UUID,
        tenant: Tenant | None,
        *,
        now: datetime,
        dry_run: bool,
        batch_size: int,
        max_batches: int,
    ) -> TenantCleanupOutcome:
        if tenant is None:
            return self._finish(
                tenant_id,
                TenantCleanupOutcome(
                    tenant_id=tenant_id,
                    outcome="skipped",
                    effective_days=0,
                    cutoff=None,
                    requests_deleted=0,
                    sessions_deleted=0,
                    truncated=False,
                    dry_run=dry_run,
                    reason="tenant_not_found",
                ),
            )

        days = self.effective_days(tenant)
        if days == 0:
            return self._finish(
                tenant.id,
                TenantCleanupOutcome(
                    tenant_id=tenant.id,
                    outcome="skipped",
                    effective_days=0,
                    cutoff=None,
                    requests_deleted=0,
                    sessions_deleted=0,
                    truncated=False,
                    dry_run=dry_run,
                    reason="legal_hold" if tenant.audit_retention_days == 0 else "disabled",
                ),
            )

        cutoff = now - timedelta(days=days)
        if dry_run:
            try:
                remaining = await self._audit.count_requests(
                    tenant_id=tenant.id, since=None, until=cutoff
                )
            except Exception as exc:
                return self._failed(
                    tenant.id,
                    effective_days=days,
                    cutoff=cutoff,
                    requests_deleted=0,
                    sessions_deleted=0,
                    truncated=False,
                    dry_run=True,
                    stage="requests",
                    exc=exc,
                )
            return self._finish(
                tenant.id,
                TenantCleanupOutcome(
                    tenant_id=tenant.id,
                    outcome="completed",
                    effective_days=days,
                    cutoff=cutoff,
                    requests_deleted=remaining,
                    sessions_deleted=0,
                    truncated=False,
                    dry_run=True,
                ),
            )

        try:
            requests_deleted, requests_truncated = await self._drain(
                self._audit.delete_requests_before,
                tenant_id=tenant.id,
                cutoff=cutoff,
                batch_size=batch_size,
                max_batches=max_batches,
                kind="requests",
            )
        except Exception as exc:
            return self._failed(
                tenant.id,
                effective_days=days,
                cutoff=cutoff,
                requests_deleted=0,
                sessions_deleted=0,
                truncated=False,
                dry_run=False,
                stage="requests",
                exc=exc,
            )

        try:
            sessions_deleted, sessions_truncated = await self._drain(
                self._audit.delete_orphan_sessions_before,
                tenant_id=tenant.id,
                cutoff=cutoff,
                batch_size=batch_size,
                max_batches=max_batches,
                kind="sessions",
            )
        except Exception as exc:
            return self._failed(
                tenant.id,
                effective_days=days,
                cutoff=cutoff,
                requests_deleted=requests_deleted,
                sessions_deleted=0,
                truncated=requests_truncated,
                dry_run=False,
                stage="sessions",
                exc=exc,
            )

        return self._finish(
            tenant.id,
            TenantCleanupOutcome(
                tenant_id=tenant.id,
                outcome="completed",
                effective_days=days,
                cutoff=cutoff,
                requests_deleted=requests_deleted,
                sessions_deleted=sessions_deleted,
                truncated=requests_truncated or sessions_truncated,
                dry_run=False,
            ),
        )

    async def _drain(
        self,
        delete_batch: _DeleteBatch,
        *,
        tenant_id: UUID,
        cutoff: datetime,
        batch_size: int,
        max_batches: int,
        kind: Literal["requests", "sessions"],
    ) -> tuple[int, bool]:
        total = 0
        for _ in range(max_batches):
            deleted = await delete_batch(tenant_id=tenant_id, cutoff=cutoff, batch_size=batch_size)
            total += deleted
            if deleted:
                current_metrics().audit_cleanup_rows.add(deleted, {"kind": kind})
            if deleted < batch_size:
                return total, False
        return total, True

    def _failed(
        self,
        tenant_id: UUID,
        *,
        effective_days: int,
        cutoff: datetime,
        requests_deleted: int,
        sessions_deleted: int,
        truncated: bool,
        dry_run: bool,
        stage: Literal["requests", "sessions"],
        exc: Exception,
    ) -> TenantCleanupOutcome:
        current_metrics().audit_cleanup_failures.add(1, {"stage": stage})
        logger.warning(
            "audit_cleanup_failed",
            extra={
                "tenant_id": str(tenant_id),
                "stage": stage,
                "error": type(exc).__name__,
            },
        )
        return self._finish(
            tenant_id,
            TenantCleanupOutcome(
                tenant_id=tenant_id,
                outcome="failed",
                effective_days=effective_days,
                cutoff=cutoff,
                requests_deleted=requests_deleted,
                sessions_deleted=sessions_deleted,
                truncated=truncated,
                dry_run=dry_run,
                reason=f"{stage}:{type(exc).__name__}",
            ),
        )

    def _finish(self, tenant_id: UUID, outcome: TenantCleanupOutcome) -> TenantCleanupOutcome:
        logger.info(
            "audit_cleanup_finished",
            extra={
                "tenant_id": str(tenant_id),
                "outcome": outcome.outcome,
                "effective_days": outcome.effective_days,
                "requests_deleted": outcome.requests_deleted,
                "sessions_deleted": outcome.sessions_deleted,
                "truncated": outcome.truncated,
                "dry_run": outcome.dry_run,
                "reason": outcome.reason,
            },
        )
        return outcome
