"""GitHub device auth flow for Copilot proxy credentials."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
import urllib.error
import urllib.request


GITHUB_BASE_URL = "https://github.com"
GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"
GITHUB_APP_SCOPES = "read:user"


@dataclass(frozen=True)
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


def _json_request(url: str, *, body: dict[str, object]) -> dict[str, object]:
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "content-type": "application/json",
            "accept": "application/json",
        },
        method="POST",
    )
    response = urllib.request.urlopen(request, timeout=30)
    raw = response.read().decode("utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}
    return parsed if isinstance(parsed, dict) else {}


def get_device_code() -> DeviceCodeResponse:
    data = _json_request(
        f"{GITHUB_BASE_URL}/login/device/code",
        body={"client_id": GITHUB_CLIENT_ID, "scope": GITHUB_APP_SCOPES},
    )
    return DeviceCodeResponse(
        device_code=str(data.get("device_code", "")),
        user_code=str(data.get("user_code", "")),
        verification_uri=str(data.get("verification_uri", "")),
        expires_in=int(data.get("expires_in", 0) or 0),
        interval=int(data.get("interval", 5) or 5),
    )


def poll_access_token(device_code: DeviceCodeResponse) -> str:
    started_at = time.time()
    sleep_seconds = max(1, device_code.interval + 1)
    while True:
        if device_code.expires_in > 0 and (time.time() - started_at) > device_code.expires_in:
            raise RuntimeError("GitHub device code expired before authorization completed")

        data = _json_request(
            f"{GITHUB_BASE_URL}/login/oauth/access_token",
            body={
                "client_id": GITHUB_CLIENT_ID,
                "device_code": device_code.device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
        token = str(data.get("access_token", "")).strip()
        if token:
            return token
        error = str(data.get("error", "")).strip()
        if error and error not in {"authorization_pending", "slow_down"}:
            raise RuntimeError(f"GitHub device auth failed: {error}")
        time.sleep(sleep_seconds)


def run_device_auth_flow() -> tuple[DeviceCodeResponse, str]:
    device_code = get_device_code()
    if not device_code.user_code or not device_code.verification_uri:
        raise RuntimeError("GitHub device code flow returned invalid response")
    access_token = poll_access_token(device_code)
    return device_code, access_token
