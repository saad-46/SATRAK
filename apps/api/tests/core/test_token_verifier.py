"""Story 1 — token validation (ADR-0013 C) and signing-key rotation (A1, A14)."""

from __future__ import annotations

import time

import pytest

from app.core.auth import (
    InvalidTokenError,
    JwksKeyProvider,
    JwksUnavailableError,
    TokenVerifier,
)
from tests.auth_support import TEST_ISSUER, TestIdp, TestKey, auth_settings


def _verifier(idp: TestIdp, **overrides: object) -> tuple[TokenVerifier, JwksKeyProvider]:
    settings = auth_settings(**overrides)
    provider = JwksKeyProvider(settings, idp.client())
    return TokenVerifier(settings, provider), provider


async def _reason(verifier: TokenVerifier, token: str) -> str:
    with pytest.raises(InvalidTokenError) as exc:
        await verifier.verify(token)
    return exc.value.reason


async def test_valid_token_yields_principal(idp: TestIdp) -> None:
    verifier, _ = _verifier(idp)
    principal = await verifier.verify(idp.token(claims={"sid": "s-1", "jti": "tok-1"}))
    assert principal.subject == "user-123"
    assert principal.issuer == TEST_ISSUER
    assert principal.token_id == "tok-1"
    assert principal.session_id == "s-1"
    assert principal.expires_at > principal.issued_at


async def test_audience_may_be_a_list_containing_ours(idp: TestIdp) -> None:
    verifier, _ = _verifier(idp)
    await verifier.verify(idp.token(claims={"aud": ["other", "satrak-api-test"]}))


async def test_es256_is_supported_when_allowed() -> None:
    idp = TestIdp()
    idp.keys = [TestKey("ec-1", kind="ec")]
    verifier, _ = _verifier(idp, allowed_algorithms=["ES256"])
    await verifier.verify(idp.token())


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"claims": {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}}, "expired"),
        ({"claims": {"iss": "https://evil.example.invalid"}}, "bad_issuer"),
        ({"claims": {"aud": "someone-else"}}, "bad_audience"),
        ({"claims": {"aud": ["a", "b"]}}, "bad_audience"),
        ({"remove": ("exp",)}, "missing_claim"),
        ({"remove": ("iat",)}, "missing_claim"),
        ({"remove": ("sub",)}, "missing_claim"),
        ({"remove": ("aud",)}, "missing_claim"),
        ({"remove": ("iss",)}, "missing_claim"),
        ({"claims": {"sub": ""}}, "bad_subject"),
        ({"claims": {"sub": "x" * 300}}, "bad_subject"),
        ({"claims": {"nbf": int(time.time()) + 3600}}, "invalid"),
        ({"claims": {"iat": int(time.time()) + 3600}}, "invalid"),
        ({"headers": {"kid": "unknown"}}, "unknown_kid"),
        ({"headers": {"kid": None}}, "missing_kid"),
        ({"headers": {"jku": "https://evil.example.invalid/jwks"}}, "forbidden_header"),
        ({"headers": {"x5u": "https://evil.example.invalid/c"}}, "forbidden_header"),
        ({"headers": {"jwk": {"kty": "RSA"}}}, "forbidden_header"),
    ],
)
async def test_invalid_tokens_are_rejected(
    idp: TestIdp, kwargs: dict[str, object], reason: str
) -> None:
    verifier, _ = _verifier(idp)
    assert await _reason(verifier, idp.token(**kwargs)) == reason  # type: ignore[arg-type]


async def test_token_signed_by_a_different_key_with_known_kid_is_rejected(idp: TestIdp) -> None:
    verifier, _ = _verifier(idp)
    attacker = TestKey("key-1")  # same kid, different key material
    assert await _reason(verifier, idp.token(key=attacker)) == "bad_signature"


async def test_tampered_payload_is_rejected(idp: TestIdp) -> None:
    verifier, _ = _verifier(idp)
    head, _, sig = idp.token().split(".")
    forged = idp.token(claims={"sub": "admin"}).split(".")[1]
    assert await _reason(verifier, f"{head}.{forged}.{sig}") == "bad_signature"


async def test_alg_none_is_rejected(idp: TestIdp) -> None:
    import base64
    import json

    verifier, _ = _verifier(idp)

    def b64(obj: object) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    now = int(time.time())
    claims = {"iss": TEST_ISSUER, "aud": "satrak-api-test", "sub": "x", "iat": now, "exp": now + 60}
    token = f"{b64({'alg': 'none', 'kid': 'key-1'})}.{b64(claims)}."
    assert await _reason(verifier, token) == "algorithm_not_allowed"


async def test_hs256_signed_with_the_public_key_is_rejected(idp: TestIdp) -> None:
    """Classic algorithm-confusion attack: HMAC keyed with the published public key.

    PyJWT refuses to mint such a token, so it is forged by hand.
    """
    import base64
    import hashlib
    import hmac
    import json

    from cryptography.hazmat.primitives import serialization

    verifier, _ = _verifier(idp)
    public_pem = idp.signing_key.private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    now = int(time.time())
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "key-1"}).encode())
    claims = {"iss": TEST_ISSUER, "aud": "satrak-api-test", "sub": "x", "iat": now, "exp": now + 60}
    payload = b64(json.dumps(claims).encode())
    signature = b64(hmac.new(public_pem, f"{header}.{payload}".encode(), hashlib.sha256).digest())
    assert await _reason(verifier, f"{header}.{payload}.{signature}") == "algorithm_not_allowed"


async def test_algorithm_outside_the_configured_allow_list_is_rejected() -> None:
    idp = TestIdp()
    idp.keys = [TestKey("ec-1", kind="ec")]
    verifier, _ = _verifier(idp)  # default allow-list is RS256 only
    assert await _reason(verifier, idp.token()) == "algorithm_not_allowed"


@pytest.mark.parametrize("junk", ["", "a", "a.b", "a.b.c", "....", "💥" * 10])
async def test_malformed_tokens_are_rejected(idp: TestIdp, junk: str) -> None:
    verifier, _ = _verifier(idp)
    assert await _reason(verifier, junk) == "malformed"


async def test_oversized_token_is_rejected_before_any_parsing(idp: TestIdp) -> None:
    verifier, _ = _verifier(idp, max_token_bytes=256)
    assert await _reason(verifier, idp.token(claims={"pad": "x" * 600})) == "token_too_large"


async def test_clock_skew_leeway_is_bounded(idp: TestIdp) -> None:
    now = int(time.time())
    verifier, _ = _verifier(idp, clock_skew_seconds=30)
    await verifier.verify(idp.token(claims={"exp": now - 10, "iat": now - 900}))
    assert (
        await _reason(verifier, idp.token(claims={"exp": now - 120, "iat": now - 900})) == "expired"
    )


# --- Key discovery, caching and rotation (A14) --------------------------------------------
async def test_keys_are_cached_between_requests(idp: TestIdp) -> None:
    idp = TestIdp()
    verifier, _ = _verifier(idp)
    for _ in range(5):
        await verifier.verify(idp.token())
    assert (idp.discovery_requests, idp.jwks_requests) == (1, 1)


async def test_rotation_new_kid_is_accepted_after_one_bounded_refresh() -> None:
    idp = TestIdp()
    clock = [1000.0]
    settings = auth_settings(jwks_min_refresh_interval_seconds=30)
    provider = JwksKeyProvider(settings, idp.client(), clock=lambda: clock[0])
    verifier = TokenVerifier(settings, provider)
    await verifier.verify(idp.token())  # primes the cache with key-1

    new_key = TestKey("key-2")
    idp.keys = [new_key, idp.keys[0]]  # rotation: new key published, old still listed
    clock[0] += 31
    await verifier.verify(idp.token(key=new_key))
    await verifier.verify(idp.token(key=idp.keys[1]))  # previous key still valid while published
    assert idp.jwks_requests == 2


async def test_retired_key_is_rejected_once_unpublished() -> None:
    idp = TestIdp()
    clock = [1000.0]
    settings = auth_settings(jwks_cache_ttl_seconds=60, jwks_min_refresh_interval_seconds=1)
    provider = JwksKeyProvider(settings, idp.client(), clock=lambda: clock[0])
    verifier = TokenVerifier(settings, provider)
    old = idp.keys[0]
    await verifier.verify(idp.token())
    idp.keys = [TestKey("key-2")]
    clock[0] += 120  # cache expired -> refreshed set no longer contains key-1
    assert await _reason(verifier, idp.token(key=old)) == "unknown_kid"


async def test_unknown_kid_flood_cannot_cause_refresh_storm() -> None:
    idp = TestIdp()
    clock = [1000.0]
    settings = auth_settings(jwks_min_refresh_interval_seconds=30)
    provider = JwksKeyProvider(settings, idp.client(), clock=lambda: clock[0])
    verifier = TokenVerifier(settings, provider)
    await verifier.verify(idp.token())
    before = idp.jwks_requests
    for i in range(50):
        clock[0] += 0.1
        assert await _reason(verifier, idp.token(headers={"kid": f"junk-{i}"})) == "unknown_kid"
    assert idp.jwks_requests - before <= 1


async def test_discovery_with_mismatched_issuer_is_not_trusted() -> None:
    idp = TestIdp()
    idp.discovery_issuer = "https://other.example.invalid"
    verifier, _ = _verifier(idp)
    with pytest.raises(JwksUnavailableError):
        await verifier.verify(idp.token())


async def test_cold_start_with_idp_down_fails_closed() -> None:
    idp = TestIdp()
    idp.online = False
    verifier, _ = _verifier(idp)
    with pytest.raises(JwksUnavailableError):
        await verifier.verify(idp.token())


async def test_stale_keys_keep_working_only_within_the_bounded_window() -> None:
    idp = TestIdp()
    clock = [1000.0]
    settings = auth_settings(
        jwks_cache_ttl_seconds=60, jwks_max_stale_seconds=600, jwks_min_refresh_interval_seconds=1
    )
    provider = JwksKeyProvider(settings, idp.client(), clock=lambda: clock[0])
    verifier = TokenVerifier(settings, provider)
    await verifier.verify(idp.token())
    idp.online = False
    clock[0] += 300  # stale but within ttl + max_stale
    await verifier.verify(idp.token())
    clock[0] += 1000  # beyond the window -> fail closed
    with pytest.raises(JwksUnavailableError):
        await verifier.verify(idp.token())


async def test_explicit_jwks_url_skips_discovery() -> None:
    idp = TestIdp()
    verifier, _ = _verifier(idp, jwks_url=f"{TEST_ISSUER}/jwks")
    await verifier.verify(idp.token())
    assert idp.discovery_requests == 0
