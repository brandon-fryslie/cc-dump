"""Tests for pure proxy planning/parsing helpers."""

from cc_dump.pipeline.proxy_flow import (
    decode_json_response_body,
    parse_request_json,
    resolve_proxy_target,
)


def test_parse_request_json_accepts_object_payload():
    body, error = parse_request_json(b'{"a":1,"b":"x"}', expects_json=True)
    assert error == ""
    assert body == {"a": 1, "b": "x"}


def test_parse_request_json_rejects_non_object_payload():
    body, error = parse_request_json(b'[1,2,3]', expects_json=True)
    assert body is None
    assert "top level" in error.lower()


def test_parse_request_json_rejects_invalid_json():
    body, error = parse_request_json(b"{not-json", expects_json=True)
    assert body is None
    assert error != ""


def test_parse_request_json_rejects_invalid_utf8_payload():
    body, error = parse_request_json(b'"\xff"', expects_json=True)
    assert body is None
    assert error != ""


def test_decode_json_response_body_returns_dict_only():
    assert decode_json_response_body(b'{"ok":true}') == {"ok": True}
    assert decode_json_response_body(b'["not","object"]') == {}
    assert decode_json_response_body(b"not-json") == {}


def test_resolve_proxy_target_concatenates_path_onto_target_host():
    target = resolve_proxy_target(
        "/v1/messages",
        "https://api.anthropic.com",
    )
    assert target.error_reason == ""
    assert target.error_status == 0
    assert target.request_path == "/v1/messages"
    assert target.upstream_url == "https://api.anthropic.com/v1/messages"


def test_resolve_proxy_target_preserves_absolute_form():
    target = resolve_proxy_target(
        "https://api.anthropic.com/v1/messages?x=1",
        "https://api.anthropic.com",
    )
    assert target.error_reason == ""
    assert target.request_path == "/v1/messages?x=1"
    assert target.upstream_url == "https://api.anthropic.com/v1/messages?x=1"


def test_resolve_proxy_target_refuses_without_target_host():
    target = resolve_proxy_target("/v1/messages", None)
    assert target.error_status == 500
    assert target.upstream_url == ""
    assert "reverse proxy" in target.error_reason.lower()
