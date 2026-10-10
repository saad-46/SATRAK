"""Test identity provider: a fake OIDC issuer that exists only inside the test process.

The issuer/audience values are reserved ``.invalid`` placeholders, not a real provider. Keys
are generated per run; discovery and JWKS are served through an in-process ``httpx`` mock
transport so no network is touched.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from app.core.auth import AuthRuntime, build_auth_runtime
from app.core.config import AuthSettings, Environment, Settings

TEST_ISSUER = "https://issuer.example.invalid"
TEST_AUDIENCE = "satrak-api-test"


def auth_settings(**overrides: Any) -> AuthSettings:
    values: dict[str, Any] = {
        "enabled": True,
        "issuer": TEST_ISSUER,
        "audiences": [TEST_AUDIENCE],
        "jwks_min_refresh_interval_seconds": 1,
    }
    values.update(overrides)
    return AuthSettings(**values)


def make_settings(**auth_overrides: Any) -> Settings:
    return Settings(
        environment=Environment.TEST,
        log_format="console",
        auth=auth_settings(**auth_overrides),
    )


class TestKey:
    __test__ = False

    def __init__(self, kid: str, *, kind: str = "rsa") -> None:
        self.kid = kid
        self.kind = kind
        if kind == "rsa":
            self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            self.alg = "RS256"
            jwk = json.loads(RSAAlgorithm.to_jwk(self.private.public_key()))
        else:
            self.private = ec.generate_private_key(ec.SECP256R1())
            self.alg = "ES256"
            jwk = json.loads(ECAlgorithm.to_jwk(self.private.public_key()))
        jwk.update({"kid": kid, "use": "sig", "alg": self.alg})
        self.jwk = jwk


class TestIdp:
    """Serves discovery + JWKS and mints tokens. Mutable so tests can rotate or break it."""

    __test__ = False

    def __init__(self) -> None:
        self.keys: list[TestKey] = [TestKey("key-1")]
        self.online = True
        self.jwks_requests = 0
        self.discovery_requests = 0
        self.discovery_issuer = TEST_ISSUER

    @property
    def signing_key(self) -> TestKey:
        return self.keys[0]

    def handler(self, request: httpx.Request) -> httpx.Response:
        if not self.online:
            raise httpx.ConnectError("idp offline", request=request)
        url = str(request.url)
        if url == f"{TEST_ISSUER}/.well-known/openid-configuration":
            self.discovery_requests += 1
            return httpx.Response(
                200,
                json={"issuer": self.discovery_issuer, "jwks_uri": f"{TEST_ISSUER}/jwks"},
            )
        if url == f"{TEST_ISSUER}/jwks":
            self.jwks_requests += 1
            return httpx.Response(200, json={"keys": [k.jwk for k in self.keys]})
        return httpx.Response(404)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def runtime(self, settings: AuthSettings | None = None) -> AuthRuntime:
        runtime = build_auth_runtime(settings or auth_settings(), client=self.client())
        assert runtime is not None
        return runtime

    def token(
        self,
        *,
        key: TestKey | None = None,
        claims: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
        remove: tuple[str, ...] = (),
        alg: str | None = None,
        secret: Any = None,
    ) -> str:
        key = key or self.signing_key
        now = int(time.time())
        payload: dict[str, Any] = {
            "iss": TEST_ISSUER,
            "aud": TEST_AUDIENCE,
            "sub": "user-123",
            "iat": now,
            "exp": now + 900,
            "jti": uuid.uuid4().hex,
        }
        payload.update(claims or {})
        for name in remove:
            payload.pop(name, None)
        header = {"kid": key.kid}
        header.update(headers or {})
        header = {k: v for k, v in header.items() if v is not None}
        return jwt.encode(
            payload,
            secret if secret is not None else key.private,
            algorithm=alg or key.alg,
            headers=header,
        )

    def bearer(self, **kwargs: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(**kwargs)}"}
