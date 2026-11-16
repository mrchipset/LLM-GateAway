from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from llm_gateway.auth.admin_auth import AdminPrincipal
from llm_gateway.auth.admin_deps import current_admin
from llm_gateway.providers.throughput import THROUGHPUT_WINDOW_SECONDS, recent_throughput
from llm_gateway.schemas.throughput import ThroughputResponse, ThroughputStatsItem

router = APIRouter(tags=["admin-throughput"])


@router.get("/throughput", response_model=ThroughputResponse)
async def get_throughput(
    _: Annotated[AdminPrincipal, Depends(current_admin)],
) -> ThroughputResponse:
    """Recent prefill and decode rates measured by this worker.

    The window is in-process and rolling; a multi-worker deployment returns the
    values collected by the worker that served the request.
    """
    stats = recent_throughput()
    return ThroughputResponse(
        window_seconds=THROUGHPUT_WINDOW_SECONDS,
        items=[
            ThroughputStatsItem(
                provider=item.provider,
                model=item.model,
                samples=item.samples,
                prefill_tokens_per_second_p50=item.prefill_tokens_per_second_p50,
                prefill_tokens_per_second_p95=item.prefill_tokens_per_second_p95,
                decode_tokens_per_second_p50=item.decode_tokens_per_second_p50,
                decode_tokens_per_second_p95=item.decode_tokens_per_second_p95,
                last_observed_at=item.last_observed_at,
            )
            for item in stats
        ],
    )
