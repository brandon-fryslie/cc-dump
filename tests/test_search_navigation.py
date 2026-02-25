"""Unit tests for search navigation expansion and scroll behavior."""

from dataclasses import dataclass

import cc_dump.app.view_store
import cc_dump.core.formatting
import cc_dump.tui.search
import cc_dump.tui.search_controller as search_controller
import cc_dump.tui.view_overrides


@dataclass
class _FakeTurn:
    turn_index: int
    blocks: list
    line_offset: int = 0

    def __post_init__(self):
        self._flat_blocks = list(self.blocks)
        self.block_strip_map = {idx: idx for idx, _ in enumerate(self.blocks)}


class _FakeConv:
    def __init__(self, turns):
        self._turns = turns
        self._view_overrides = cc_dump.tui.view_overrides.ViewOverrides()
        self.scroll_calls: list[tuple[int, int, int]] = []
        self.rerender_calls = 0

    def ensure_turn_rendered(self, _turn_index: int) -> None:
        return None

    def scroll_to_block(self, turn_index: int, block_index: int, line_in_block: int = 0) -> None:
        self.scroll_calls.append((turn_index, block_index, line_in_block))

    def rerender(self, _filters, search_ctx=None) -> None:
        self.rerender_calls += 1


class _FakeApp:
    def __init__(self, conv):
        self._view_store = cc_dump.app.view_store.create()
        self._search_state = cc_dump.tui.search.SearchState(self._view_store)
        self._conv = conv
        self.active_filters = {}

    def _get_conv(self):
        return self._conv

    def _get_search_bar(self):
        return None

    def _get_footer(self):
        return None


def _fenced_text(needle: str, line_index: int, total_lines: int = 140) -> str:
    lines = [f"line {idx}" for idx in range(total_lines)]
    lines[line_index] = needle
    code = "\n".join(lines)
    return f"intro\n```python\n{code}\n```\noutro"


def _make_text_block(content: str) -> cc_dump.core.formatting.TextContentBlock:
    block = cc_dump.core.formatting.TextContentBlock(
        content=content,
        category=cc_dump.core.formatting.Category.ASSISTANT,
    )
    cc_dump.core.formatting.populate_content_regions(block)
    return block


def test_navigate_next_restores_previous_region_and_expands_new_match_region():
    """Search navigation restores previous region expansion before applying next."""
    needle = "needle_shared_marker"
    block_a = _make_text_block(_fenced_text(needle, 80))
    block_b = _make_text_block(_fenced_text(needle, 95))
    turns = [_FakeTurn(0, [block_a], line_offset=0), _FakeTurn(1, [block_b], line_offset=10)]
    conv = _FakeConv(turns)
    app = _FakeApp(conv)
    state = app._search_state

    offset_a = block_a.content.index(needle)
    offset_b = block_b.content.index(needle)
    state.matches = [
        cc_dump.tui.search.SearchMatch(1, 0, offset_b, len(needle), block=block_b),
        cc_dump.tui.search.SearchMatch(0, 0, offset_a, len(needle), block=block_a),
    ]
    state.current_index = 0

    first_region_idx = search_controller._matched_region_index(block_b, offset_b)
    second_region_idx = search_controller._matched_region_index(block_a, offset_a)
    assert first_region_idx is not None
    assert second_region_idx is not None

    search_controller.navigate_to_current(app)
    assert conv._view_overrides.get_region(block_b.block_id, first_region_idx).expanded is True

    search_controller.navigate_next(app)
    assert state.current_index == 1
    assert conv._view_overrides.get_region(block_b.block_id, first_region_idx).expanded is None
    assert conv._view_overrides.get_region(block_a.block_id, second_region_idx).expanded is True


def test_navigate_to_current_passes_deep_line_hint_to_scroll():
    """Search navigation scrolls toward match line, not always block header."""
    needle = "needle_deep_line_220"
    content = "\n".join(
        needle if idx == 220 else f"assistant line {idx}" for idx in range(260)
    )
    block = _make_text_block(content)
    turn = _FakeTurn(0, [block], line_offset=0)
    conv = _FakeConv([turn])
    app = _FakeApp(conv)
    state = app._search_state

    offset = content.index(needle)
    state.matches = [cc_dump.tui.search.SearchMatch(0, 0, offset, len(needle), block=block)]
    state.current_index = 0

    expected_line_hint = content.count("\n", 0, offset)
    search_controller.navigate_to_current(app)

    assert conv.scroll_calls
    _, _, line_hint = conv.scroll_calls[-1]
    assert line_hint == expected_line_hint
    assert line_hint > 0
