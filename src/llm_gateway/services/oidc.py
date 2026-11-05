"""OIDC authorization-code flow for the admin console.

The gateway acts as a confidential client: it starts the flow, exchanges the code
server-side, validates the ID token against the provider's JWKS, maps a role from a
configured claim, and then issues the same opaque admin session used by password
login. The browser never sees the client secret, the ID token, or the access token.

Scope decisions:

* no OIDC session is kept outside the admin session table;
* an OIDC identity is linked by ``sub`` only; local accounts are never silently
  taken over by a matching username;
* JIT provisioning is opt-in and creates an active admin with the mapped role, so
  an IdP administrator can decide who gets access without touching the gateway.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWK

from llm_gateway.config import Settings
from llm_gateway.logging import get_logger
from llm_gateway.storage.repositories import AdminRole

logger = get_logger(__name__)

_DISCOVERY_TTL_SECONDS = 3600.0
_JWKS_TTL_SECONDS = 3600.0
_ALLOWED_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"}
)
_ROLE_PRIORITY = (AdminRole.OWNER, AdminRole.OPERATOR, AdminRole.AUDITOR)


class OIDCError(Exception):
    """A failure that is safe to show to the operator as a short code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class OIDCDiscovery:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


@dataclass(frozen=True, slots=True)
class OIDCIdentity:
    subject: str
    username: str
    fallback_username: str
    display_name: str
    role: AdminRole


class OIDCService:
    def __init__(self, *, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        if not settings.oidc_enabled:
            raise ValueError("OIDCService requires oidc_enabled")
        if settings.oidc_issuer is None or settings.oidc_client_id is None:
            raise ValueError("OIDC issuer and client id are required")
        if settings.oidc_client_secret is None:
            raise ValueError("OIDC client secret is required")
        self._settings = settings
        self._issuer = settings.oidc_issuer.rstrip("/")
        self._client_id = settings.oidc_client_id
        self._client_secret = settings.oidc_client_secret.get_secret_value()
        self._scopes = settings.oidc_scopes
        self._role_claim = settings.oidc_role_claim
        self._role_map = self._parse_role_map(settings.oidc_role_map)
        self._owns_client = client is None
        self._client = (
            client
            if client is not None
            else httpx.AsyncClient(
                timeout=httpx.Timeout(
                    settings.request_timeout_seconds,
                    connect=settings.connect_timeout_seconds,
                )
            )
        )
        self._discovery: OIDCDiscovery | None = None
        self._discovery_at = 0.0
        self._jwks: dict[str, PyJWK] = {}
        self._jwks_at = 0.0

    @staticmethod
    def _parse_role_map(raw: str) -> dict[str, AdminRole]:
        import json

        loaded = json.loads(raw or "{}")
        if not isinstance(loaded, dict):
            raise ValueError("oidc_role_map must be a JSON object")
        return {str(claim): AdminRole(str(role)) for claim, role in loaded.items()}

    async def discovery(self) -> OIDCDiscovery:
        now = time.monotonic()
        if self._discovery is not None and now - self._discovery_at < _DISCOVERY_TTL_SECONDS:
            return self._discovery
        url = f"{self._issuer}/.well-known/openid-configuration"
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCError(
                "discovery_failed", "Could not load the OIDC discovery document"
            ) from exc
        try:
            discovery = OIDCDiscovery(
                issuer=str(payload["issuer"]).rstrip("/"),
                authorization_endpoint=str(payload["authorization_endpoint"]),
                token_endpoint=str(payload["token_endpoint"]),
                jwks_uri=str(payload["jwks_uri"]),
            )
        except (KeyError, TypeError) as exc:
            raise OIDCError(
                "discovery_invalid", "OIDC discovery is missing required fields"
            ) from exc
        if discovery.issuer != self._issuer:
            raise OIDCError("issuer_mismatch", "OIDC discovery issuer does not match configuration")
        self._discovery = discovery
        self._discovery_at = now
        return discovery

    async def authorize_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        discovery = await self.discovery()
        params = urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "redirect_uri": self._settings.oidc_redirect_uri,
                "scope": self._scopes,
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{discovery.authorization_endpoint}?{params}"

    async def exchange(self, *, code: str, code_verifier: str, nonce: str) -> OIDCIdentity:
        discovery = await self.discovery()
        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._settings.oidc_redirect_uri or "",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code_verifier": code_verifier,
        }
        try:
            response = await self._client.post(discovery.token_endpoint, data=data)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCError("token_exchange_failed", "OIDC token exchange failed") from exc
        id_token = payload.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise OIDCError("missing_id_token", "OIDC provider returned no id_token")

        claims = await self._decode(id_token)
        if claims.get("nonce") != nonce:
            raise OIDCError("nonce_mismatch", "OIDC nonce did not match")
        role = self._role_for(claims)
        if role is None:
            raise OIDCError("role_not_mapped", "OIDC role claim did not map to a gateway role")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise OIDCError("missing_subject", "OIDC id_token has no subject")
        return OIDCIdentity(
            subject=subject,
            username=self._username(claims, subject),
            fallback_username=f"oidc-{_short_hash(subject)}",
            display_name=self._display_name(claims, subject),
            role=role,
        )

    async def _decode(self, id_token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise OIDCError("invalid_id_token", "OIDC id_token header is invalid") from exc
        algorithm = header.get("alg")
        if algorithm not in _ALLOWED_ALGORITHMS:
            raise OIDCError("invalid_id_token", "OIDC id_token uses an unsupported algorithm")
        key = await self._signing_key(header.get("kid"))
        discovery = await self.discovery()
        try:
            return jwt.decode(
                id_token,
                key=key,
                algorithms=[algorithm],
                audience=self._client_id,
                issuer=discovery.issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise OIDCError("invalid_id_token", "OIDC id_token validation failed") from exc

    async def _signing_key(self, kid: object) -> Any:
        if kid in self._jwks and time.monotonic() - self._jwks_at < _JWKS_TTL_SECONDS:
            return self._jwks[str(kid)].key
        discovery = await self.discovery()
        try:
            response = await self._client.get(discovery.jwks_uri)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCError("jwks_failed", "Could not load the OIDC signing keys") from exc
        keys = payload.get("keys") if isinstance(payload, dict) else None
        if not isinstance(keys, list):
            raise OIDCError("jwks_invalid", "OIDC JWKS is missing keys")
        loaded: dict[str, PyJWK] = {}
        for entry in keys:
            if not isinstance(entry, dict):
                continue
            entry_kid = entry.get("kid")
            if isinstance(entry_kid, str):
                loaded[entry_kid] = PyJWK(entry)
        self._jwks = loaded
        self._jwks_at = time.monotonic()
        if kid is None:
            if len(loaded) != 1:
                raise OIDCError("jwks_ambiguous", "OIDC id_token has no kid and JWKS is ambiguous")
            return next(iter(loaded.values())).key
        if str(kid) not in loaded:
            raise OIDCError("jwks_unknown_kid", "OIDC id_token kid is not in JWKS")
        return loaded[str(kid)].key

    def _role_for(self, claims: dict[str, Any]) -> AdminRole | None:
        raw = claims.get(self._role_claim)
        if isinstance(raw, str):
            values = [raw]
        elif isinstance(raw, list):
            values = [value for value in raw if isinstance(value, str)]
        else:
            values = []
        granted = {self._role_map[value] for value in values if value in self._role_map}
        for role in _ROLE_PRIORITY:
            if role in granted:
                return role
        return None

    def _username(self, claims: dict[str, Any], subject: str) -> str:
        candidate = claims.get("preferred_username") or claims.get("email") or ""
        if not isinstance(candidate, str):
            candidate = ""
        normalized = candidate.split("@", 1)[0].strip().lower()
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in normalized)
        safe = safe.strip("-._")
        if len(safe) < 3:
            safe = f"oidc-{_short_hash(subject)}"
        return safe[:64]

    def _display_name(self, claims: dict[str, Any], subject: str) -> str:
        for field in ("name", "preferred_username", "email"):
            value = claims.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()[:100]
        return f"OIDC {_short_hash(subject)}"

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _short_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
