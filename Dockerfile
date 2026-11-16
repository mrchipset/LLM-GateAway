FROM ghcr.io/astral-sh/uv:0.11.28 AS uv

FROM python:3.12-slim AS builder
# Package index for both sync steps. The default stays on PyPI so CI and other
# regions build unchanged; pass a mirror with --build-arg or compose args.
ARG UV_DEFAULT_INDEX=https://pypi.org/simple
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_DEFAULT_INDEX=${UV_DEFAULT_INDEX}

COPY --from=uv /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime
# pip is not used to build the image, but operators run it by hand inside the
# container; keep the same index override available there.
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PIP_INDEX_URL=${PIP_INDEX_URL}

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder --chown=app:app /app /app

USER app
EXPOSE 4000
# Shell form so the graceful-shutdown bound and worker count track the environment.
# The app also drains in-flight requests; uvicorn's timeout is the hard ceiling.
CMD ["sh", "-c", "exec uvicorn llm_gateway.app:create_app --factory --host 0.0.0.0 --port 4000 --workers ${GATEWAY_WORKERS:-1} --timeout-graceful-shutdown ${GATEWAY_SHUTDOWN_GRACE_SECONDS:-30}"]
