"""Pure planning/parsing helpers for proxy request orchestration.

// [LAW:locality-or-seam] Pure flow planning is separated from socket/network side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from collections.abc import Mapping
from urllib.parse import urlparse

from pydantic import TypeAdapter, ValidationError


_JSON_OBJECT = TypeAdapter(dict[str, object])


@dataclass(frozen=True)
class ProxyTarget:
    request_path: str
    upstream_url: str
    error_reason: str = ""
    error_status: int = 0


def resolve_proxy_target(path: str, target_host: str | None) -> ProxyTarget:
    """Resolve request path and upstream URL for forward/reverse proxy modes."""
    return resolve_proxy_target_for_origin(path, target_host, required_origin=None)


def resolve_proxy_target_for_origin(
    path: str,
    target_host: str | None,
    *,
    required_origin: str | None,
) -> ProxyTarget:
    """Resolve request path + upstream URL and optionally constrain to a required origin.

    // [LAW:single-enforcer] Absolute-form target confinement for CONNECT tunnels lives here.
    """
    if path.startswith("http://") or path.startswith("https://"):
        parsed = urlparse(path)
        request_path = parsed.path or "/"
        if parsed.query:
            request_path = f"{request_path}?{parsed.query}"
        upstream_url = path if path.startswith("https://") else "https://" + path[7:]
        target = ProxyTarget(
            request_path=request_path,
            upstream_url=upstream_url,
        )
    elif not target_host:
        target = ProxyTarget(
            request_path=path,
            upstream_url="",
            error_reason="No target_host configured for reverse proxy mode",
            error_status=500,
        )
    else:
        target = ProxyTarget(
            request_path=path,
            upstream_url=f"{target_host}{path}",
        )

    return _constrain_target_origin(target, required_origin=required_origin)


def _constrain_target_origin(
    target: ProxyTarget,
    *,
    required_origin: str | None,
) -> ProxyTarget:
    if not required_origin or target.error_reason:
        return target

    parsed_required = urlparse(required_origin)
    parsed_upstream = urlparse(target.upstream_url)
    if _normalized_origin(parsed_upstream) != _normalized_origin(parsed_required):
        return ProxyTarget(
            request_path=target.request_path,
            upstream_url="",
            error_reason="CONNECT target origin mismatch",
            error_status=403,
        )

    return ProxyTarget(
        request_path=target.request_path,
        upstream_url=f"{required_origin}{target.request_path}",
    )


def _normalized_origin(parsed) -> str:
    scheme = (parsed.scheme or "").lower()
    hostname = (parsed.hostname or "").lower()
    if not scheme or not hostname:
        return ""
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80 if scheme == "http" else -1
    return f"{scheme}://{hostname}:{port}"


def parse_request_json(
    body_bytes: bytes,
    *,
    expects_json: bool,
) -> tuple[dict[str, object] | None, str]:
    """Parse request body as JSON for API paths, returning parse error text when invalid."""
    if (not body_bytes) or (not expects_json):
        return None, ""
    try:
        parsed = json.loads(body_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, str(exc)
    try:
        validated = _JSON_OBJECT.validate_python(parsed)
    except ValidationError:
        return None, "Request JSON must be an object at the top level"
    return validated, ""


def build_upstream_headers(headers: Mapping[str, str], *, content_length: int) -> dict[str, str]:
    """Build upstream headers with host/content-length normalization."""
    forwarded = {
        k: v
        for k, v in headers.items()
        if k.lower() not in ("host", "content-length")
    }
    forwarded["Content-Length"] = str(content_length)
    return forwarded


def decode_json_response_body(data: bytes) -> dict[str, object]:
    """Best-effort JSON decode for response completion payloads."""
    try:
        parsed = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    try:
        return _JSON_OBJECT.validate_python(parsed)
    except ValidationError:
        return {}
