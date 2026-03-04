"""Tests for shared coercion helpers."""

from cc_dump.core.coerce import coerce_int, coerce_optional_int, coerce_str_object_dict


def test_coerce_int_uses_default_on_invalid_values():
    assert coerce_int("abc", 7) == 7
    assert coerce_int(object(), 3) == 3


def test_coerce_int_accepts_common_scalar_inputs():
    assert coerce_int(True, 0) == 1
    assert coerce_int("12", 0) == 12
    assert coerce_int(12.9, 0) == 12


def test_coerce_optional_int_returns_none_on_invalid_values():
    assert coerce_optional_int("nope") is None
    assert coerce_optional_int(object()) is None


def test_coerce_optional_int_accepts_common_scalar_inputs():
    assert coerce_optional_int(False) == 0
    assert coerce_optional_int("9") == 9


def test_coerce_str_object_dict_defaults_to_empty_for_non_dict():
    assert coerce_str_object_dict("x") == {}
    assert coerce_str_object_dict(1) == {}


def test_coerce_str_object_dict_passthrough_for_dict():
    payload = {"a": 1, "b": "two"}
    assert coerce_str_object_dict(payload) == payload
