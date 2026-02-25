"""Regression tests for click-to-toggle block expansion in ConversationView."""

import pytest

from cc_dump.tui import rendering
from tests.harness import run_app
from tests.harness.builders import make_replay_entry

pytestmark = pytest.mark.textual


async def test_click_toggles_clicked_block_not_adjacent_block():
    """Clicking an arrow toggles the block under the click, not the next line."""
    replay_data = [
        make_replay_entry(
            content="hi",
            response_text="\n".join(f"line {i}" for i in range(20)),
        )
    ]

    async with run_app(replay_data=replay_data, size=(140, 45)) as (pilot, app):
        conv = app._get_conv()
        first_turn = conv._turns[0]

        toggle_indices: list[int] = []
        for block_idx, start_line in first_turn.block_strip_map.items():
            strip = first_turn.strips[start_line]
            has_toggle_meta = any(
                bool((getattr(seg.style, "meta", {}) or {}).get(rendering.META_TOGGLE_BLOCK))
                for seg in strip
                if seg.style is not None
            )
            if has_toggle_meta:
                toggle_indices.append(block_idx)

        assert len(toggle_indices) >= 2, "Need at least two clickable toggle rows for this regression test"

        target_idx = toggle_indices[0]
        neighbor_idx = toggle_indices[1]
        target_block = first_turn._flat_blocks[target_idx]
        neighbor_block = first_turn._flat_blocks[neighbor_idx]

        target_state = conv._view_overrides.get_block(target_block.block_id)
        neighbor_state = conv._view_overrides.get_block(neighbor_block.block_id)
        assert target_state.expanded is None
        assert neighbor_state.expanded is None

        content_y = first_turn.line_offset + first_turn.block_strip_map[target_idx] - conv.scroll_offset.y
        click_x = conv.content_offset.x + 1
        click_y = conv.content_offset.y + content_y

        await pilot.click("#conversation-view", offset=(click_x, click_y))
        await pilot.pause()

        assert conv._view_overrides.get_block(target_block.block_id).expanded is not None
        assert conv._view_overrides.get_block(neighbor_block.block_id).expanded is None
