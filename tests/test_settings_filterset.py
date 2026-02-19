"""Unit tests for settings.get_filterset() defensive validation."""

import json
import logging

import pytest

from cc_dump.formatting import VisState
from cc_dump.settings import (
    DEFAULT_FILTERSETS,
    _VALID_CATEGORY_KEYS,
    get_filterset,
)


def test_get_filterset_returns_defaults():
    """get_filterset always returns built-in defaults."""
    for slot, expected in DEFAULT_FILTERSETS.items():
        result = get_filterset(slot)
        assert result == expected, f"slot {slot}: expected defaults"


def test_get_filterset_unknown_slot_returns_none():
    """Unknown slot returns None."""
    assert get_filterset("99") is None


def test_get_filterset_stale_data_logs_warning(tmp_path, monkeypatch, caplog):
    """Stale saved data with wrong keys produces a warning and returns defaults."""
    # Write a settings file with stale category keys (old schema)
    settings_path = tmp_path / "cc-dump" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    stale_data = {
        "filtersets": {
            "1": {
                "headers": [True, False, False],
                "budget": [True, False, False],
                "user": [True, True, False],
            }
        }
    }
    settings_path.write_text(json.dumps(stale_data), encoding="utf-8")

    # Point get_config_path to our tmp settings
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    with caplog.at_level(logging.WARNING, logger="cc_dump.settings"):
        result = get_filterset("1")

    # Should return defaults, not stale data
    assert result == DEFAULT_FILTERSETS["1"]

    # Should have logged a warning about mismatched keys
    assert any("stale filterset slot 1" in r.message.lower() for r in caplog.records), (
        f"Expected stale warning, got: {[r.message for r in caplog.records]}"
    )


def test_get_filterset_matching_saved_data_no_warning(tmp_path, monkeypatch, caplog):
    """Saved data with correct keys does NOT produce a warning."""
    # Write a settings file with correct category keys
    settings_path = tmp_path / "cc-dump" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    correct_data = {
        "filtersets": {
            "1": {k: [True, True, False] for k in _VALID_CATEGORY_KEYS}
        }
    }
    settings_path.write_text(json.dumps(correct_data), encoding="utf-8")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    with caplog.at_level(logging.WARNING, logger="cc_dump.settings"):
        result = get_filterset("1")

    # Should return defaults (we always return defaults now)
    assert result == DEFAULT_FILTERSETS["1"]

    # Should NOT have logged any warnings
    assert not any("stale" in r.message.lower() for r in caplog.records), (
        f"Unexpected warning: {[r.message for r in caplog.records]}"
    )


def test_valid_category_keys_match_defaults():
    """_VALID_CATEGORY_KEYS matches all DEFAULT_FILTERSETS slot keys."""
    for slot, filters in DEFAULT_FILTERSETS.items():
        assert set(filters.keys()) == _VALID_CATEGORY_KEYS, (
            f"slot {slot} keys don't match _VALID_CATEGORY_KEYS"
        )
