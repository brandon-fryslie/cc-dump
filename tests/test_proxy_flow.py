"""Tests for pure proxy planning/parsing helpers."""

from cc_dump.pipeline.proxy_flow import (
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


def test_decode_json_response_body_returns_dict_only():
    assert decode_json_response_body(b'{"ok":true}') == {"ok": True}
    assert decode_json_response_body(b'["not","object"]') == {}
    assert decode_json_response_body(b"not-json") == {}
