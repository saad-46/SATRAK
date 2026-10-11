"""Behaviour of the container HEALTHCHECK (apps/api/healthcheck.py) and of the images' contents."""

from __future__ import annotations

import http.server
import importlib.util
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "apps" / "api" / "healthcheck.py"
_spec = importlib.util.spec_from_file_location("healthcheck", SCRIPT)
assert _spec is not None and _spec.loader is not None
healthcheck = importlib.util.module_from_spec(_spec)
sys.modules["healthcheck"] = healthcheck
_spec.loader.exec_module(healthcheck)


@contextmanager
def _server(status: int, *, location: str | None = None, delay: float = 0.0) -> Iterator[str]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if delay:
                time.sleep(delay)
            self.send_response(status)
            if location:
                self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args: object) -> None:
            return None

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/api/v1/health/live"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _closed_port_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/api/v1/health/live"


def test_default_url_is_the_liveness_endpoint_on_loopback() -> None:
    assert healthcheck.DEFAULT_URL == "http://127.0.0.1:8000/api/v1/health/live"


def test_200_is_healthy() -> None:
    with _server(200) as url:
        assert healthcheck.is_healthy(url) is True


@pytest.mark.parametrize("status", [204, 301, 302, 400, 401, 404, 500, 503])
def test_anything_but_200_is_unhealthy(status: int) -> None:
    with _server(status, location="/elsewhere") as url:
        assert healthcheck.is_healthy(url) is False


def test_redirect_is_not_followed_even_to_a_healthy_target() -> None:
    with _server(200) as target, _server(302, location=target) as url:
        assert healthcheck.is_healthy(url) is False


def test_connection_refused_is_unhealthy() -> None:
    assert healthcheck.is_healthy(_closed_port_url()) is False


def test_timeout_is_unhealthy() -> None:
    with _server(200, delay=1.5) as url:
        assert healthcheck.is_healthy(url, timeout=0.3) is False


@pytest.mark.parametrize("url", ["", "not a url", "file:///etc/passwd", "https://127.0.0.1:1/x"])
def test_non_http_or_malformed_urls_are_unhealthy(url: str) -> None:
    assert healthcheck.is_healthy(url) is False


def test_timeout_stays_below_the_dockerfile_healthcheck_timeout() -> None:
    assert healthcheck.TIMEOUT_SECONDS < 5


def _run(*args: str, env: dict[str, str] | None = None) -> int:
    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], env=merged, timeout=30, check=False
    ).returncode


def test_exit_status_is_what_docker_expects() -> None:
    with _server(200) as ok, _server(503) as bad:
        assert _run(ok) == 0
        assert _run(bad) == 1
    assert _run(_closed_port_url()) == 1


def test_system_proxy_settings_are_ignored() -> None:
    with _server(200) as url:
        env = {"HTTP_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9"}
        assert _run(url, env=env) == 0


def _dockerfile_stage(name: str) -> str:
    text = (ROOT / "apps" / "api" / "Dockerfile").read_text(encoding="utf-8")
    marker = f"AS {name}"
    start = text.index(marker)
    next_from = text.find("\nFROM ", start)
    return text[start : next_from if next_from != -1 else len(text)]


def _instructions(stage: str) -> list[str]:
    return [
        line.strip()
        for line in stage.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_runtime_stage_installs_no_system_packages() -> None:
    body = "\n".join(_instructions(_dockerfile_stage("runtime")))
    for forbidden in ("apt-get", "apt ", "libgdal", "libgeos", "curl", "-dev"):
        assert forbidden not in body, forbidden


def test_runtime_healthcheck_uses_the_python_script() -> None:
    stage = _dockerfile_stage("runtime")
    assert 'CMD ["python", "/app/healthcheck.py"]' in stage
    assert "COPY --chown=satrak:satrak healthcheck.py ./" in stage
    assert "curl" not in "\n".join(_instructions(stage))


def test_healthcheck_script_is_not_excluded_from_the_build_context() -> None:
    patterns = (ROOT / "apps" / "api" / ".dockerignore").read_text().splitlines()
    assert "healthcheck.py" not in [p.strip() for p in patterns]


def test_compose_api_healthcheck_does_not_need_curl() -> None:
    compose = (ROOT / "infra" / "docker-compose" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "curl" not in compose
    assert '["CMD", "python", "/app/healthcheck.py"]' in compose
