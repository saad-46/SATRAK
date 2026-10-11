"""Authentication infrastructure: OIDC access-token validation (ADR-0013).

Provider-agnostic: no identity provider, issuer, audience or claim name is built in.
The API is a relying party that *validates* tokens; it never mints them.
"""

from app.core.auth.jwks import JwksKeyProvider, JwksUnavailableError, KeyNotFoundError
from app.core.auth.principal import Principal
from app.core.auth.runtime import AuthRuntime, build_auth_runtime
from app.core.auth.verifier import InvalidTokenError, TokenVerifier

__all__ = [
    "AuthRuntime",
    "InvalidTokenError",
    "JwksKeyProvider",
    "JwksUnavailableError",
    "KeyNotFoundError",
    "Principal",
    "TokenVerifier",
    "build_auth_runtime",
]
