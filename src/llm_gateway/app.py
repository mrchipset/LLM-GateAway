from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from llm_gateway import __version__
from llm_gateway.api.admin import router as admin_router
from llm_gateway.api.health import router as health_router
from llm_gateway.api.inference import router as inference_router
from llm_gateway.body_limit import RequestBodyLimitMiddleware
from llm_gateway.config import Settings
from llm_gateway.container import Container, build_container
from llm_gateway.errors import register_error_handlers
from llm_gateway.lifecycle import InFlightMiddleware
from llm_gateway.logging import configure_logging, get_logger
from llm_gateway.metrics import configure_metrics, current_metrics
from llm_gateway.request_context import RequestContextMiddleware
from llm_gateway.services.bootstrap import bootstrap_admin
from llm_gateway.telemetry import configure_telemetry

logger = get_logger(__name__)


def create_app(
    settings: Settings | None = None,
    container: Container | None = None,
) -> FastAPI:
    if settings is not None and container is not None and container.settings != settings:
        raise ValueError("container.settings must match the provided settings")

    if container is None:
        resolved_settings = settings if settings is not None else Settings(**{})
        resolved_container = build_container(resolved_settings)
    else:
        resolved_settings = container.settings
        resolved_container = container

    configure_logging(resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if not resolved_settings.billing_enabled:
            logger.warning(
                "billing_disabled",
                extra={
                    "consequence": (
                        "plan and budget enforcement are skipped; usage costs are not settled"
                    )
                },
            )
        await bootstrap_admin(resolved_container)
        try:
            yield
        finally:
            tracker = resolved_container.inflight
            grace = resolved_settings.shutdown_grace_seconds
            idle = await tracker.wait_for_idle(grace) if grace > 0 else tracker.active == 0
            if not idle:
                logger.warning(
                    "shutdown_grace_exceeded",
                    extra={"active_requests": tracker.active},
                )
                current_metrics().forced_shutdowns.add(1)
            await resolved_container.aclose()

    app = FastAPI(
        title="LLM-GateAway",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.container = resolved_container
    configure_metrics(resolved_settings)
    telemetry = resolved_container.telemetry
    if telemetry is None:
        telemetry = configure_telemetry(resolved_settings)
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=resolved_settings.max_request_bytes,
    )
    app.add_middleware(RequestContextMiddleware, telemetry=telemetry)
    app.add_middleware(InFlightMiddleware, tracker=resolved_container.inflight)
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(inference_router)
    app.include_router(admin_router)
    return app
