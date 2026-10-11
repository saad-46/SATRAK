"""Exactly one trust path for forwarded client addresses (uvicorn is told not to add another)."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from app.core.config import Environment, RateLimitSettings, Settings
from app.core.proxy_trust import (
    UnsafeProxyTrustError,
    unsafe_forwarded_allow_ips,
    verify_forwarded_allow_ips,
)
from app.main import create_app
from tests.auth_support import TestIdp, auth_settings

API_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "value", ["*", "10.0.0.0/8,*", " * ", "0.0.0.0/0", "::/0", "127.0.0.1, 0.0.0.0/0"]
)
def test_blanket_trust_lists_are_unsafe(value: str) -> None:
    assert unsafe_forwarded_allow_ips(value)


@pytest.mark.parametrize("value", [None, "", "127.0.0.1,::1", "10.0.0.0/8", "10.1.2.3, fd00::/8"])
def test_bounded_trust_lists_are_not_flagged(value: str | None) -> None:
    assert unsafe_forwarded_allow_ips(value) is None


def test_only_deployed_environments_refuse_to_start() -> None:
    verify_forwarded_allow_ips({"FORWARDED_ALLOW_IPS": "*"}, enforce=False)
    verify_forwarded_allow_ips({}, enforce=True)
    with pytest.raises(UnsafeProxyTrustError, match="FORWARDED_ALLOW_IPS is unsafe"):
        verify_forwarded_allow_ips({"FORWARDED_ALLOW_IPS": "*"}, enforce=True)


@pytest.mark.parametrize("environment", [Environment.STAGING, Environment.PRODUCTION])
async def test_the_lifespan_refuses_a_wildcard_trust_list(
    environment: Environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        environment=environment,
        network_topology="behind_proxy",
        log_format="console",
        auth=auth_settings(),
        rate_limit=RateLimitSettings(trusted_proxy_hops=1, trusted_proxy_cidrs=["10.0.0.0/8"]),
        redis_url="redis://localhost:6379/0",
        database_url="postgresql+asyncpg://u:p@localhost:5432/satrak",
        _env_file=None,  # type: ignore[call-arg]
    )
    app = create_app(settings, auth=TestIdp().runtime(settings.auth))
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    with pytest.raises(UnsafeProxyTrustError):
        async with app.router.lifespan_context(app):
            pytest.fail("the application must not start")


def _dockerfile_command(path: Path) -> list[str]:
    match = re.search(r"^CMD (\[.*\])\s*$", path.read_text(), re.MULTILINE)
    assert match, f"no exec-form CMD in {path}"
    return list(json.loads(match.group(1)))


def test_the_api_image_starts_uvicorn_without_proxy_headers() -> None:
    command = _dockerfile_command(API_ROOT / "Dockerfile")
    assert command[0] == "uvicorn"
    assert "--no-proxy-headers" in command
    assert "--proxy-headers" not in command
    assert not any(part.startswith("--forwarded-allow-ips") for part in command)


# --- The installed uvicorn really behaves as the Dockerfile assumes ---------------------------
ECHO_APP = """
async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    client = scope.get("client")
    body = (client[0] if client else "none").encode()
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": body})
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _client_seen_by_the_app(tmp_path: Path, extra_args: list[str], forwarded_allow: str) -> str:
    (tmp_path / "echo_app.py").write_text(ECHO_APP)
    port = _free_port()
    env = {**os.environ, "FORWARDED_ALLOW_IPS": forwarded_allow, "PYTHONPATH": str(tmp_path)}
    proc = subprocess.Popen(  # nosec B603 - fixed arguments, test-only echo app
        [
            sys.executable,
            "-m",
            "uvicorn",
            "echo_app:app",
            "--port",
            str(port),
            "--host",
            "127.0.0.1",
            *extra_args,
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/", headers={"X-Forwarded-For": "6.6.6.6"}
        )
        deadline = time.monotonic() + 15
        while True:
            try:
                with urllib.request.urlopen(request, timeout=2) as response:  # nosec B310
                    return response.read().decode()
            except OSError:
                if time.monotonic() > deadline or proc.poll() is not None:
                    raise
                time.sleep(0.2)
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_uvicorn_rewrites_the_client_address_by_default_when_trusted(tmp_path: Path) -> None:
    # Documents the risk: with a wildcard list and proxy headers on, a caller chooses its address.
    assert _client_seen_by_the_app(tmp_path, [], "*") == "6.6.6.6"


def test_no_proxy_headers_ignores_forwarded_headers_even_with_a_wildcard(tmp_path: Path) -> None:
    assert _client_seen_by_the_app(tmp_path, ["--no-proxy-headers"], "*") == "127.0.0.1"
