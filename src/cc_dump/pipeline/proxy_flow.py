"""Pure planning/parsing helpers for proxy request orchestration.

// [LAW:locality-or-seam] Pure flow planning is separated from socket/network side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from collections.abc import Mapping
from urllib.parse import urlparse


@dataclass(frozen=True)
class ProxyTarget:
    request_path: str
    upstream_url: str
    error_reason: str = ""
    error_status: int = 0


def resolve_proxy_target(path: str, target_host: str | None) -> ProxyTarget:
    """Resolve request path and upstream URL for forward/reverse proxy modes."""
    if path.startswith("http://") or path.startswith("https://"):
        parsed = urlparse(path)
        request_path = parsed.path or "/"
        upstream_url = path if path.startswith("https://") else "https://" + path[7:]
        return ProxyTarget(
            request_path=request_path,
            upstream_url=upstream_url,
        )
    if not target_host:
        return ProxyTarget(
            request_path=path,
            upstream_url="",
            error_reason="No target_host configured for reverse proxy mode",
            error_status=500,
        )
    return ProxyTarget(
        request_path=path,
        upstream_url=f"{target_host}{path}",
    )


def parse_request_json(body_bytes: bytes, *, expects_json: bool) -> tuple[object | None, str]:
    """Parse request body as JSON for API paths, returning parse error text when invalid."""
    if (not body_bytes) or (not expects_json):
        return None, ""
    try:
        return json.loads(body_bytes), ""
    except json.JSONDecodeError as exc:
        return None, str(exc)


def build_upstream_headers(headers: Mapping[str, str], *, content_length: int) -> dict[str, str]:
    """Build upstream headers with host/content-length normalization."""
    forwarded = {
        k: v
        for k, v in headers.items()
        if k.lower() not in ("host", "content-length")
    }
    forwarded["Content-Length"] = str(content_length)
    return forwarded


def decode_json_response_body(data: bytes) -> dict:
    """Best-effort JSON decode for response completion payloads."""
    try:
        return json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
