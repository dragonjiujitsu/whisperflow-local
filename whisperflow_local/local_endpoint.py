"""Validation and transport helpers for authenticated loopback HTTP services."""
from __future__ import annotations

import ipaddress
from urllib import error, request
from urllib.parse import urlsplit


def validate_loopback_http_url(value: str) -> str:
    """Return a normalized URL after enforcing an explicit loopback endpoint."""
    raw = str(value)
    if raw != raw.strip() or any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise ValueError("cleanup base_url contains invalid whitespace")

    parts = urlsplit(raw)
    if parts.scheme.lower() != "http":
        raise ValueError("cleanup base_url must use HTTP")
    if parts.username is not None or parts.password is not None:
        raise ValueError("cleanup base_url must not contain credentials")
    if parts.query or parts.fragment:
        raise ValueError("cleanup base_url must not contain a query or fragment")

    host = parts.hostname
    if not host:
        raise ValueError("cleanup base_url must include a loopback host")
    if host.lower() == "localhost":
        host = "127.0.0.1"
    else:
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError("cleanup base_url host must be loopback")
        except ValueError as exc:
            raise ValueError("cleanup base_url host must be loopback") from exc

    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("cleanup base_url must include a valid port") from exc
    if port is None or not 1 <= port <= 65535:
        raise ValueError("cleanup base_url must include a valid port")

    path = parts.path.rstrip("/")
    authority_host = f"[{host}]" if ":" in host else host
    return f"http://{authority_host}:{port}{path}"


class NoRedirectHandler(request.HTTPRedirectHandler):
    """Reject redirects so credentials and transcript data stay on loopback."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise error.HTTPError(
            req.full_url,
            code,
            "redirects are disabled for the local cleanup service",
            headers,
            fp,
        )


def open_local_request(req: request.Request, timeout: float):
    """Open a validated local request without proxy or redirect handling."""
    validate_loopback_http_url(req.full_url)
    opener = request.build_opener(request.ProxyHandler({}), NoRedirectHandler())
    return opener.open(req, timeout=timeout)
