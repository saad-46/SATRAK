"""Container HEALTHCHECK: exit 0 only if the liveness endpoint answers HTTP 200.

Standard library only (the runtime image has no curl). Semantics, stricter than ``curl -f``:

* any answer other than exactly 200 is unhealthy, including 2xx other than 200 and redirects
  (redirects are never followed);
* connection refused, DNS/socket errors, timeouts and malformed URLs are unhealthy;
* system proxy settings are ignored, and the default URL is the container's own loopback address,
  so the check never needs external network access.

Usage: ``python healthcheck.py [URL]`` (the URL argument exists for tests).
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from http.client import HTTPException
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8000/api/v1/health/live"
TIMEOUT_SECONDS = 4.0  # below the Dockerfile HEALTHCHECK --timeout of 5s


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def is_healthy(url: str = DEFAULT_URL, timeout: float = TIMEOUT_SECONDS) -> bool:
    if not url.startswith("http://"):
        return False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    try:
        with opener.open(url, timeout=timeout) as response:
            return bool(response.status == 200)
    except (urllib.error.URLError, HTTPException, OSError, ValueError):
        return False


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    url = args[0] if args else DEFAULT_URL
    return 0 if is_healthy(url) else 1


if __name__ == "__main__":
    sys.exit(main())
