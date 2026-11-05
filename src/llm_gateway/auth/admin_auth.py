"""Management-plane authentication: local admins, sessions, role checks.

Flow:

* login verifies a local password (scrypt), applies a per-username failure throttle,
  creates an opaque session, and returns its token plus a CSRF token;
* the session token travels in an HttpOnly cookie, the CSRF token in a readable
  cookie, and state-changing requests must echo the CSRF token in a header
  (double submit);
* the master key remains a break-glass path that maps to the owner role.

Nothing here logs passwords, password hashes, session tokens, or CSRF tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from llm_gateway.auth.passwords import (
    generate_csrf_token,
    generate_session_token,
    hash_token,
    verify_against_dummy,
    verify_password,
)
from llm_gateway.clock import Clock
from llm_gateway.storage.repositories import (
    AdminActorType,
    AdminRole,
    AdminSession,
    AdminSessionRepository,
    AdminUser,
    AdminUserRepository,
    LoginThrottle,
)

LOGIN_ATTEMPT_LIMIT = 5
LOGIN_WINDOW_SECONDS = 15 * 60

_WRITE_ROLES = frozenset({AdminRole.OWNER, AdminRole.OPERATOR})
_ADMIN_MANAGEMENT_ROLES = frozenset({AdminRole.OWNER})
_AUDIT_READ_ROLES = frozenset({AdminRole.OWNER, AdminRole.AUDITOR})


@dataclass(frozen=True, slots=True)
class AdminPrincipal:
    """The authenticated caller for one management request."""

    actor_type: AdminActorType
    role: AdminRole
    name: str
    admin_id: UUID | None = None
    session_id: UUID | None = None

    @property
    def is_master(self) -> bool:
        return self.actor_type is AdminActorType.MASTER

    @property
    def can_write(self) -> bool:
        return self.role in _WRITE_ROLES

    @property
    def can_manage_admins(self) -> bool:
        return self.role in _ADMIN_MANAGEMENT_ROLES

    @property
    def can_read_audit(self) -> bool:
        return self.role in _AUDIT_READ_ROLES


@dataclass(frozen=True, slots=True)
class LoginResult:
    admin: AdminUser
    session: AdminSession
    token: str
    csrf_token: str


class LoginThrottledError(Exception):
    """Too many failed attempts for this username inside the window."""


class AdminAuthService:
    def __init__(
        self,
        *,
        admins: AdminUserRepository,
        sessions: AdminSessionRepository,
        throttle: LoginThrottle,
        clock: Clock,
        session_ttl_hours: int,
    ) -> None:
        self._admins = admins
        self._sessions = sessions
        self._throttle = throttle
        self._clock = clock
        self._session_ttl = timedelta(hours=session_ttl_hours)

    async def login(self, *, username: str, password: str, now: datetime) -> LoginResult | None:
        normalized = normalize_username(username)
        throttle_key = f"user:{normalized}"
        allowed = await self._throttle.hit(
            key=throttle_key,
            limit=LOGIN_ATTEMPT_LIMIT,
            window_seconds=LOGIN_WINDOW_SECONDS,
            now=now,
        )
        if not allowed:
            raise LoginThrottledError

        admin = await self._admins.get_admin_by_username(normalized)
        if admin is None:
            verify_against_dummy(password)
            return None
        if not admin.active:
            verify_against_dummy(password)
            return None
        if not verify_password(password, admin.password_hash):
            return None

        await self._throttle.clear(key=throttle_key)
        return await self.issue_session(admin, now=now)

    async def issue_session(self, admin: AdminUser, *, now: datetime) -> LoginResult:
        """Create an admin session for an already-authenticated principal (e.g. OIDC)."""
        token = generate_session_token()
        csrf_token = generate_csrf_token()
        session = AdminSession(
            id=uuid4(),
            admin_id=admin.id,
            token_hash=hash_token(token),
            csrf_hash=hash_token(csrf_token),
            created_at=now,
            expires_at=now + self._session_ttl,
        )
        await self._sessions.create_session(session)
        updated = await self._admins.update_admin(
            admin.id,
            last_login_at=now,
            updated_at=now,
        )
        return LoginResult(
            admin=updated if updated is not None else admin,
            session=session,
            token=token,
            csrf_token=csrf_token,
        )

    async def authenticate(self, token: str, *, now: datetime) -> AdminPrincipal | None:
        session = await self._sessions.get_session_by_token_hash(hash_token(token))
        if session is None or not session.is_active(now):
            return None
        admin = await self._admins.get_admin(session.admin_id)
        if admin is None or not admin.active:
            return None
        return AdminPrincipal(
            actor_type=AdminActorType.ADMIN,
            role=admin.role,
            name=admin.username,
            admin_id=admin.id,
            session_id=session.id,
        )

    async def logout(self, principal: AdminPrincipal, *, now: datetime) -> None:
        if principal.session_id is not None:
            await self._sessions.revoke_session(principal.session_id, at=now)

    async def revoke_all_sessions(self, admin_id: UUID, *, now: datetime) -> int:
        return await self._sessions.revoke_sessions_for_admin(admin_id, at=now)


def normalize_username(username: str) -> str:
    return username.strip().lower()


def csrf_matches(expected_hash: str, presented_token: str | None) -> bool:
    import hmac

    if not presented_token:
        return False
    return hmac.compare_digest(hash_token(presented_token), expected_hash)


def master_principal() -> AdminPrincipal:
    return AdminPrincipal(
        actor_type=AdminActorType.MASTER,
        role=AdminRole.OWNER,
        name="master-key",
    )
