"""Unit tests for built-in filterset presets."""

from cc_dump.io.settings import DEFAULT_FILTERSETS, get_filterset


def test_get_filterset_returns_defaults():
    """get_filterset always returns built-in defaults."""
    for slot, expected in DEFAULT_FILTERSETS.items():
        result = get_filterset(slot)
        assert result == expected, f"slot {slot}: expected defaults"


def test_get_filterset_unknown_slot_returns_none():
    """Unknown slot returns None."""
    assert get_filterset("99") is None


def test_filterset_slots_share_the_same_category_keys():
    """All built-in presets cover the same category set."""
    slot_keys = [set(filters.keys()) for filters in DEFAULT_FILTERSETS.values()]
    assert slot_keys, "expected at least one built-in filterset"
    assert all(keys == slot_keys[0] for keys in slot_keys[1:])
