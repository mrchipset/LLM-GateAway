# Backend foundation: configuration, logging, errors, health

Status: implemented in `src/llm_gateway/`.

## Problem and constraints

The gateway needs a runtime foundation that later stages can build on without
rework: validated configuration, a single dependency-injection seam for tests,
observability from the first request, an OpenAI-compatible error contract, and
liveness/readiness endpoints. `AGENTS.md` forbids speculative abstractions,
untyped public boundaries, swallowed exceptions, and network calls without
timeouts.

## Assumptions

- One process serves both the data plane and the control plane for the MVP;
  module boundaries inside `src/llm_gateway/` provide the separation.
- Deployment topology (multiple workers, external state) is a later concern, so
  an in-memory storage backend is acceptable for development and tests as long
  as choosing it is explicit.
- Clients tolerate one extra field (`request_id`) inside the error object; the
  OpenAI envelope's required fields stay unchanged.

## Options considered

**YAML config file vs environment-driven settings.** `design.md` proposes a YAML
schema. For the MVP, `pydantic-settings` covers deployment-time configuration
without a second parser, schema drift, or config-file precedence rules. Dynamic
model/key state lives behind the repository interfaces instead. Revisit if
GitOps-style declarative model lists are needed.

**`structlog` vs stdlib logging + a JSON formatter.** One JSON formatter over the
standard library keeps the dependency surface small. Uvicorn's own loggers are
neutralized so there is exactly one structured output stream.

**`BaseHTTPMiddleware` vs pure ASGI middleware.** Request-id propagation and
access logging are implemented as pure ASGI middleware. `BaseHTTPMiddleware`
wraps the response in an extra task group, which historically interferes with
streaming and disconnect semantics — the riskiest part of the inference path.

**Global `app.state` access vs a typed container.** All external collaborators
(clock, repositories, providers) live in one `Container` created at startup and
attached to `app.state`; routers depend on it through `Depends(get_container)`.
Tests inject a container directly, so no test depends on a developer `.env` or
monkeypatches module globals.

**OpenAI 422 vs 400 for validation errors.** FastAPI defaults to 422; OpenAI
clients expect 400 with `invalid_request_error`. The validation handler maps to
400 and never echoes the submitted body.

## Chosen approach

- `Settings` is frozen, `GATEWAY_`-prefixed, and fail-closed: `environment` is
  required, production requires the postgres backend, the fake provider is
  rejected in production, placeholder master keys (`change-me`) are rejected,
  and production master keys need at least 32 characters.
- Request ids are accepted from `x-request-id` only when they match
  `^[A-Za-z0-9._:-]{1,128}$`; otherwise a UUID4 hex is generated. The id is
  stored in the ASGI scope state and a `ContextVar`, echoed on every response,
  and attached to access logs.
- Access logs are emitted once per request from the middleware, including
  `client_disconnected`, so stream failures and disconnects stay observable.
- Logging redacts sensitive keys recursively and never logs prompts,
  completions, or authorization headers.
- Readiness is a list of named async checks on the container. A raising check
  is reported as `error` without leaking the exception text, and `/readyz`
  returns 503.
- `Container.aclose()` is invoked from the FastAPI lifespan in a `try/finally`
  so providers and (later) the database engine are released on shutdown.

## Trade-offs and risks

- Configuring logging inside the app factory mutates the root logger; tests rely
  on this and it is acceptable for a single-service process.
- `GATEWAY_ENVIRONMENT` has no default. That is deliberate: a copied
  `.env.example` must fail loudly instead of silently running development
  settings in production.
- The memory backend is single-process only. Production refuses it, but
  multi-worker development with memory storage will show inconsistent state.
- The master key is a static environment secret for the MVP; rotation and
  scoped admin tokens are out of scope.

## References

- `AGENTS.md` sections 3, 6, 7, 8, 9
- `src/llm_gateway/config.py`, `errors.py`, `logging.py`, `request_context.py`,
  `container.py`, `app.py`, `api/health.py`
- `design.md` sections 4.5, 4.7, 4.9
