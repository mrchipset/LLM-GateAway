from __future__ import annotations

from fastapi import APIRouter

from llm_gateway.api.admin import (
    admin_audit,
    admins,
    audit,
    auth,
    keys,
    models,
    tenants,
    usage,
)

router = APIRouter(prefix="/api/v1", tags=["admin"])
router.include_router(auth.router)
router.include_router(admin_audit.router)
router.include_router(admins.router)
router.include_router(audit.router)
router.include_router(keys.router)
router.include_router(models.router)
router.include_router(tenants.router)
router.include_router(usage.router)

__all__ = ["router"]
