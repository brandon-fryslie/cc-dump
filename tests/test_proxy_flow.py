"""Tests for pure proxy planning/parsing helpers."""

from cc_dump.pipeline.proxy_flow import (
    resolve_proxy_target_for_origin,
    parse_request_json,
    decode_json_response_body,
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


def test_resolve_proxy_target_for_origin_allows_matching_absolute_form():
    target = resolve_proxy_target_for_origin(
        "https://api.githubcopilot.com/chat/completions?x=1",
        "https://api.githubcopilot.com",
        required_origin="https://api.githubcopilot.com",
    )
    assert target.error_reason == ""
    assert target.error_status == 0
    assert target.request_path == "/chat/completions?x=1"
    assert target.upstream_url == "https://api.githubcopilot.com/chat/completions?x=1"


def test_resolve_proxy_target_for_origin_rejects_mismatched_absolute_form():
    target = resolve_proxy_target_for_origin(
        "https://api.openai.com/v1/chat/completions",
        "https://api.githubcopilot.com",
        required_origin="https://api.githubcopilot.com",
    )
    assert target.error_status == 403
    assert "mismatch" in target.error_reason.lower()
    assert target.upstream_url == ""


def test_resolve_proxy_target_for_origin_normalizes_default_port():
    target = resolve_proxy_target_for_origin(
        "https://api.githubcopilot.com:443/chat/completions",
        "https://api.githubcopilot.com",
        required_origin="https://api.githubcopilot.com",
    )
    assert target.error_reason == ""
    assert target.upstream_url == "https://api.githubcopilot.com/chat/completions"
