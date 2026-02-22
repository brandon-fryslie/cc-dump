"""Tests for special-content navigation actions."""

import cc_dump.tui.action_handlers as actions
from cc_dump.formatting import ConfigContentBlock, ToolUseBlock, TextContentBlock, populate_content_regions


class _Turn:
    def __init__(self, blocks):
        self.blocks = blocks
        self.is_streaming = False
        self.block_strip_map = {idx: idx for idx, _ in enumerate(blocks)}
        self._flat_blocks = list(blocks)


class _Conv:
    def __init__(self, turns):
        self._turns = turns
        self.ensure_calls: list[int] = []
        self.scroll_calls: list[tuple[int, int]] = []
        self.rerender_calls = 0

    def ensure_turn_rendered(self, turn_index: int):
        self.ensure_calls.append(turn_index)

    def scroll_to_block(self, turn_index: int, block_index: int):
        self.scroll_calls.append((turn_index, block_index))

    def rerender(self, _filters):
        self.rerender_calls += 1


class _App:
    def __init__(self, conv):
        self._conv = conv
        self._app_state: dict = {}
        self.active_filters = {}
        self.notifications: list[str] = []

    def _get_conv(self):
        return self._conv

    def notify(self, msg, severity=None):  # pragma: no cover - severity unused
        self.notifications.append(str(msg))


def test_next_special_navigates_to_first_location():
    b0 = ConfigContentBlock(source="/tmp/CLAUDE.md", content="x")
    conv = _Conv([_Turn([b0])])
    app = _App(conv)

    actions.next_special(app)

    assert conv.ensure_calls == [0]
    assert conv.scroll_calls == [(0, 0)]
    assert conv.rerender_calls == 1
    assert app._app_state["special_nav_cursor"]["all"] == 0
    assert any("CLAUDE.md" in msg for msg in app.notifications)


def test_next_special_wraps_across_multiple_locations():
    b0 = ConfigContentBlock(source="/tmp/CLAUDE.md", content="x")
    b1 = ToolUseBlock(name="Skill", input_size=1)
    conv = _Conv([_Turn([b0]), _Turn([b1])])
    app = _App(conv)

    actions.next_special(app)
    actions.next_special(app)
    actions.next_special(app)

    assert conv.scroll_calls == [(0, 0), (1, 0), (0, 0)]
    assert app._app_state["special_nav_cursor"]["all"] == 0


def test_prev_special_wraps_to_last_location_on_first_call():
    b0 = ConfigContentBlock(source="/tmp/CLAUDE.md", content="x")
    b1 = ToolUseBlock(name="Skill", input_size=1)
    conv = _Conv([_Turn([b0]), _Turn([b1])])
    app = _App(conv)

    actions.prev_special(app)

    assert conv.scroll_calls == [(1, 0)]
    assert app._app_state["special_nav_cursor"]["all"] == 1


def test_next_special_notifies_when_no_locations():
    conv = _Conv([_Turn([])])
    app = _App(conv)

    actions.next_special(app)

    assert conv.scroll_calls == []
    assert app.notifications[-1] == "No matching special sections"


def test_next_region_tag_navigates_to_matching_region():
    block = TextContentBlock(
        content="Intro\n<thinking>\ninner\n</thinking>\nOutro",
    )
    populate_content_regions(block)
    conv = _Conv([_Turn([block])])
    app = _App(conv)

    actions.next_region_tag(app, "thinking")

    assert conv.ensure_calls == [0]
    assert conv.scroll_calls == [(0, 0)]
    assert conv.rerender_calls == 1
    assert app._app_state["region_nav_cursor"]["thinking"] == 0
    assert any("thinking" in msg for msg in app.notifications)


def test_next_region_tag_notifies_when_no_matching_tags():
    block = TextContentBlock(content="plain text")
    populate_content_regions(block)
    conv = _Conv([_Turn([block])])
    app = _App(conv)

    actions.next_region_tag(app, "thinking")

    assert conv.scroll_calls == []
    assert app.notifications[-1] == "No matching region tags"
