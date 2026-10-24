from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from llm_gateway import __version__
from llm_gateway.api.admin import router as admin_router
from llm_gateway.api.health import router as health_router
from llm_gateway.api.inference import router as inference_router
from llm_gateway.config import Settings
from llm_gateway.container import Container, build_container
from llm_gateway.errors import register_error_handlers
from llm_gateway.logging import configure_logging
from llm_gateway.request_context import RequestContextMiddleware


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
        try:
            yield
        finally:
            await resolved_container.aclose()

    app = FastAPI(
        title="LLM-GateAway",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.container = resolved_container
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(inference_router)
    app.include_router(admin_router)
    return app
