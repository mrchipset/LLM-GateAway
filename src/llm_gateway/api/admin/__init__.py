from __future__ import annotations

from fastapi import APIRouter

from llm_gateway.api.admin import keys, models, tenants

router = APIRouter(prefix="/api/v1", tags=["admin"])
router.include_router(keys.router)
router.include_router(models.router)
router.include_router(tenants.router)

__all__ = ["router"]
