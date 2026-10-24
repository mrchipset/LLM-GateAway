# PostgreSQL persistence and migrations

Status: implemented in `src/llm_gateway/storage/{tables,db,sql}.py` and
`alembic/`.

## Problem and constraints

Keys and models must survive restarts and be shared between processes. The MVP
already defined repository protocols for the in-memory backend, so persistence
has to satisfy the same contracts without leaking ORM types into services,
routes, or tests. Every unit test must keep running without a database.

## Assumptions

- PostgreSQL is the only durable backend for now; Redis and other stores are out
  of scope.
- Schema changes are applied by an operator (or a deploy step) with
  `alembic upgrade head`, not automatically at application startup. Running
  migrations from multiple workers is unsafe.
- The registry is small enough that offset pagination and simple `count(*)`
  queries are acceptable.

## Options considered

**`Base.metadata.create_all` at startup vs Alembic.** `create_all` hides drift
and cannot evolve a schema. Alembic is the only supported path; tests run the
real migration so the migration itself is exercised.

**Instantiating `Settings` in `alembic/env.py` vs reading
`GATEWAY_DATABASE_URL`.** `Settings` requires a master key and other runtime
config. Migrations should need only a database URL, so `env.py` reads the
environment variable directly and fails with an explicit error when it is
missing.

**SQLModel vs SQLAlchemy 2 typed ORM.** SQLAlchemy 2 with `Mapped[...]` columns
keeps the ORM at the storage boundary and avoids a second modeling layer. Domain
dataclasses are converted at the repository edge.

**Naive vs timezone-aware columns.** All timestamp columns are
`TIMESTAMP WITH TIME ZONE`, and the domain records reject naive datetimes. This
keeps `created` values correct regardless of the server's local timezone and
makes expiry comparisons meaningful.

**Automatically creating tables in tests vs running the migration.** The
integration fixture runs `alembic upgrade head` once and truncates between
tests, so migration and ORM metadata are validated together.

## Chosen approach

- `ApiKeyRow` / `ModelRow` map to the existing domain dataclasses. `key_hash` is
  unique-indexed (`ix_api_keys_key_hash`); `provider` is stored as text and
  parsed back into `ProviderName` with an explicit error on unknown values.
- `SqlAlchemy*Repository` performs one transaction per operation, converts rows
  to domain objects before returning, maps unique violations to
  `DuplicateModelError` / `DuplicateApiKeyError`, implements revocation as a
  conditional update, and raises `KeyError` when `touch_last_used` targets a
  missing row.
- `Database` owns the engine and session factory with bounded pool
  (`pool_size=5`, `max_overflow=5`), `pool_pre_ping`, connect timeout, and
  `pool_recycle`. `ping()` issues `SELECT 1` under `asyncio.timeout` for
  readiness; failure logs once per transition and returns False.
- `build_container` selects memory or PostgreSQL explicitly. The PostgreSQL
  branch wires the repositories, a `database` readiness check, and closes the
  engine in `Container.aclose()`.
- Integration tests are marked `integration` and skipped unless
  `GATEWAY_TEST_DATABASE_URL` is set. 16 tests cover CRUD, ordering,
  pagination, `enabled_only`, duplicate detection, revocation transitions, and
  `ping`/`aclose`.

## Trade-offs and risks

- No migration-on-startup and no migration job in compose yet; deploys must run
  Alembic explicitly.
- A single pool configuration; no per-endpoint tuning or statement timeouts.
- `last_used_at` is a write on every authenticated request, which will contend
  at high request rates.
- Model updates are not supported; soft state (`enabled`) still requires a
  delete/recreate for other fields.
- No audit table, spend table, or request log table yet; the schema is
  intentionally limited to the MVP control-plane objects.
- Integration tests share one database and truncate tables, so they must not
  run concurrently against the same schema.

## References

- `src/llm_gateway/storage/tables.py`, `storage/db.py`, `storage/sql.py`
- `src/llm_gateway/storage/repositories.py` (protocols and invariants)
- `alembic/env.py`, `alembic/versions/0001_initial_schema.py`
- `tests/test_postgres_repositories.py`
- `design.md` sections 4.6, 4.10
