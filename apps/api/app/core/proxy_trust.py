"""Startup checks that keep exactly one trust path for forwarded client addresses.

The application resolves the caller's address itself (``resolve_client_ip``: configured proxy
hops, trusted networks, right-most entries only). uvicorn can also rewrite the client address
from ``X-Forwarded-For`` before the application runs (``--proxy-headers``, on by default,
trusting ``FORWARDED_ALLOW_IPS``). With a wildcard there, any direct caller picks its own
address and every per-IP limit and audit entry follows it. The image therefore starts uvicorn
with ``--no-proxy-headers``; this check is the second line of defence for deployments that
override the command, and refuses a wildcard trust list outside development and test.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping

ENV_VAR = "FORWARDED_ALLOW_IPS"


class UnsafeProxyTrustError(RuntimeError):
    """The process is configured to believe forwarding headers from any peer."""


def unsafe_forwarded_allow_ips(value: str | None) -> str | None:
    """Why ``value`` (uvicorn's ``FORWARDED_ALLOW_IPS``) trusts every peer, or ``None``."""
    if value is None:
        return None
    for entry in (item.strip() for item in value.split(",")):
        if entry == "*":
            return "a wildcard trusts every peer"
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue  # a literal host name or malformed entry: not a blanket range
        if network.prefixlen == 0:
            return f"{entry} trusts every address"
    return None


def verify_forwarded_allow_ips(environ: Mapping[str, str], *, enforce: bool) -> None:
    """Refuse to start when ``FORWARDED_ALLOW_IPS`` trusts every peer (``enforce`` = deployed)."""
    reason = unsafe_forwarded_allow_ips(environ.get(ENV_VAR))
    if reason is not None and enforce:
        raise UnsafeProxyTrustError(
            f"{ENV_VAR} is unsafe: {reason}. Forwarded client addresses are resolved by the "
            "application (rate_limit.trusted_proxy_*); run uvicorn with --no-proxy-headers."
        )
