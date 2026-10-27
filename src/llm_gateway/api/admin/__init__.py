from __future__ import annotations

from fastapi import APIRouter

from llm_gateway.api.admin import audit, keys, models, tenants, usage

router = APIRouter(prefix="/api/v1", tags=["admin"])
router.include_router(audit.router)
router.include_router(keys.router)
router.include_router(models.router)
router.include_router(tenants.router)
router.include_router(usage.router)

__all__ = ["router"]
