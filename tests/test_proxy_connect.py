"""Unit tests for CONNECT authority parsing in proxy handler."""

import pytest

from cc_dump.pipeline.proxy import _parse_connect_authority


@pytest.mark.parametrize(
    "authority,expected",
    [
        ("example.com", ("example.com", 443)),
        ("example.com:8443", ("example.com", 8443)),
        ("[::1]", ("::1", 443)),
        ("[::1]:9443", ("::1", 9443)),
        ("[2001:db8::1]:443", ("2001:db8::1", 443)),
    ],
)
def test_parse_connect_authority_valid(authority, expected):
    assert _parse_connect_authority(authority) == expected


@pytest.mark.parametrize(
    "authority",
    [
        "",
        ":443",
        "example.com:",
        "example.com:notaport",
        "example.com:70000",
        "[::1",
        "[::1]junk",
        "::1:443",  # unbracketed IPv6 is invalid CONNECT authority
    ],
)
def test_parse_connect_authority_invalid(authority):
    assert _parse_connect_authority(authority) is None
