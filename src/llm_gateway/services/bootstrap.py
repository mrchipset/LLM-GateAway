"""First-run admin bootstrap.

The bootstrap account is created only when no active owner exists. It never resets a
password and never overrides an existing installation, so leaving the environment
variables set after the first start is harmless.

If the master key is disabled and no owner exists, startup fails instead of bringing up
a management plane that nobody can use.
"""

from __future__ import annotations

from uuid import uuid4

from llm_gateway.auth.admin_auth import AdminPrincipal, normalize_username
from llm_gateway.auth.passwords import hash_password
from llm_gateway.container import Container
from llm_gateway.logging import get_logger
from llm_gateway.services.admin_audit import record_admin_event_safely
from llm_gateway.storage.repositories import (
    AdminActorType,
    AdminRole,
    AdminUser,
    DuplicateAdminError,
    LastOwnerError,
)

logger = get_logger(__name__)


async def bootstrap_admin(container: Container) -> None:
    settings = container.settings
    username = settings.bootstrap_admin_username
    password = settings.bootstrap_admin_password

    if username is None or password is None:
        if not settings.master_key_enabled:
            owners = await container.admins.count_active_owners()
            if owners == 0:
                raise RuntimeError(
                    "master key is disabled and no active owner exists; "
                    "configure bootstrap_admin_username and bootstrap_admin_password"
                )
        return

    if await container.admins.count_active_owners() > 0:
        return

    normalized = normalize_username(username)
    if await container.admins.get_admin_by_username(normalized) is not None:
        return

    now = container.clock.now()
    admin = AdminUser(
        id=uuid4(),
        username=normalized,
        display_name=normalized,
        role=AdminRole.OWNER,
        password_hash=hash_password(password.get_secret_value()),
        active=True,
        created_at=now,
        updated_at=now,
        password_changed_at=now,
    )
    try:
        created = await container.admins.create_admin(admin)
    except (DuplicateAdminError, LastOwnerError):
        # Another worker won the race; startup must not fail because of that.
        return

    await record_admin_event_safely(
        container=container,
        principal=AdminPrincipal(
            actor_type=AdminActorType.BOOTSTRAP,
            role=AdminRole.OWNER,
            name="bootstrap",
        ),
        action="admin.bootstrap_created",
        target_type="admin",
        target_id=str(created.id),
        after={"username": created.username, "role": str(created.role)},
    )
    logger.info("bootstrap_admin_created", extra={"username": created.username})
