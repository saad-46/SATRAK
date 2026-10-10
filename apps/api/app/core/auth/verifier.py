"""Access-token validation (ADR-0013 C).

Signature, issuer, audience, expiry and the required claims are all checked with an
explicit allow-list of asymmetric algorithms. The algorithm is never taken on trust from
the token header, and headers that could redirect key lookup are rejected outright.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

import jwt
from jwt import PyJWK

from app.core.auth.jwks import JwksUnavailableError, KeyNotFoundError
from app.core.auth.principal import Principal
from app.core.config import AuthSettings

_REQUIRED_CLAIMS = ("exp", "iat", "iss", "aud", "sub")
# Headers that let a token influence where verification keys come from.
_FORBIDDEN_HEADERS = frozenset({"jku", "x5u", "x5c", "jwk", "crit"})
_MAX_CLAIM_LENGTH = 256


class InvalidTokenError(Exception):
    """The token must be rejected. ``reason`` is a log-safe code, never shown to callers."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class KeyProvider(Protocol):
    async def get_key(self, kid: str) -> PyJWK: ...


class TokenVerifier:
    def __init__(self, settings: AuthSettings, keys: KeyProvider) -> None:
        if settings.issuer is None:
            raise ValueError("an issuer is required to verify tokens")
        self._settings = settings
        self._issuer: str = settings.issuer
        self._keys = keys
        self._algorithms = tuple(settings.allowed_algorithms)

    async def verify(self, token: str) -> Principal:
        if len(token.encode("utf-8", errors="replace")) > self._settings.max_token_bytes:
            raise InvalidTokenError("token_too_large")
        kid, alg = self._inspect_header(token)
        try:
            key = await self._keys.get_key(kid)
        except KeyNotFoundError as exc:
            raise InvalidTokenError("unknown_kid") from exc
        # JwksUnavailableError propagates: the caller fails closed with a 503, not a 401.
        claims = self._decode(token, key, alg)
        return self._principal(claims)

    # -- steps --------------------------------------------------------------------------
    def _inspect_header(self, token: str) -> tuple[str, str]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("malformed") from exc
        if _FORBIDDEN_HEADERS & header.keys():
            raise InvalidTokenError("forbidden_header")
        alg = header.get("alg")
        if not isinstance(alg, str) or alg not in self._algorithms:
            raise InvalidTokenError("algorithm_not_allowed")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid or len(kid) > _MAX_CLAIM_LENGTH:
            raise InvalidTokenError("missing_kid")
        return kid, alg

    def _decode(self, token: str, key: PyJWK, alg: str) -> dict[str, Any]:
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key.key,
                algorithms=[alg],
                audience=list(self._settings.audiences),
                issuer=self._issuer,
                leeway=self._settings.clock_skew_seconds,
                options={"require": list(_REQUIRED_CLAIMS)},
            )
        except jwt.ExpiredSignatureError as exc:
            raise InvalidTokenError("expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise InvalidTokenError("bad_audience") from exc
        except jwt.InvalidIssuerError as exc:
            raise InvalidTokenError("bad_issuer") from exc
        except jwt.MissingRequiredClaimError as exc:
            raise InvalidTokenError("missing_claim") from exc
        except jwt.InvalidSignatureError as exc:
            raise InvalidTokenError("bad_signature") from exc
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("invalid") from exc
        return claims

    def _principal(self, claims: dict[str, Any]) -> Principal:
        subject = claims["sub"]
        if not isinstance(subject, str) or not subject or len(subject) > _MAX_CLAIM_LENGTH:
            raise InvalidTokenError("bad_subject")
        try:
            issued_at = datetime.fromtimestamp(float(claims["iat"]), tz=UTC)
            expires_at = datetime.fromtimestamp(float(claims["exp"]), tz=UTC)
        except (TypeError, ValueError, OverflowError, OSError) as exc:
            raise InvalidTokenError("bad_timestamp") from exc
        return Principal(
            subject=subject,
            issuer=self._issuer,
            issued_at=issued_at,
            expires_at=expires_at,
            token_id=_optional_str(claims.get("jti")),
            session_id=_optional_str(claims.get("sid")),
        )


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and 0 < len(value) <= _MAX_CLAIM_LENGTH:
        return value
    return None


__all__ = ["InvalidTokenError", "JwksUnavailableError", "KeyProvider", "TokenVerifier"]
