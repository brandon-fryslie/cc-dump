from cc_dump.proxies.copilot.auth import DeviceCodeResponse, poll_access_token


def test_poll_access_token_retries_pending(monkeypatch):
    responses = iter(
        [
            {"error": "authorization_pending"},
            {"access_token": "gho_test"},
        ]
    )

    def fake_json_request(url: str, *, body: dict[str, object]):
        _ = url
        _ = body
        return next(responses)

    monkeypatch.setattr("cc_dump.proxies.copilot.auth._json_request", fake_json_request)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    token = poll_access_token(
        DeviceCodeResponse(
            device_code="dev",
            user_code="USER",
            verification_uri="https://github.com/login/device",
            expires_in=300,
            interval=1,
        )
    )
    assert token == "gho_test"
