"""Regression test for view-store reaction binding order."""

import queue
from types import SimpleNamespace

import pytest

import cc_dump.app.view_store
import cc_dump.tui.view_store_bridge
from cc_dump.tui.app import CcDumpApp
from tests.harness import all_turns_text, make_replay_entry


pytestmark = pytest.mark.textual


async def test_pre_run_view_store_reactions_rebind_on_mount():
    """Filter chip clicks rerender conversation even when reactions were pre-bound.

    Simulates CLI startup order where view-store reactions are configured before app.run().
    """
    state = {
        "positions": {},
        "known_hashes": {},
        "next_id": 0,
        "next_color": 0,
        "request_counter": 0,
    }
    view_store = cc_dump.app.view_store.create()
    store_context: dict[str, object] = {}

    app = CcDumpApp(
        event_queue=queue.Queue(),
        state=state,
        router=SimpleNamespace(stop=lambda: None),
        replay_data=[make_replay_entry()],
        view_store=view_store,
        store_context=store_context,
    )

    # Pre-bind reactions exactly like CLI startup did before app.run().
    store_context["app"] = app
    store_context.update(cc_dump.tui.view_store_bridge.build_reaction_context(app))
    view_store._reaction_disposers = cc_dump.app.view_store.setup_reactions(
        view_store, store_context
    )

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert "Hello world" in all_turns_text(app)

        await pilot.click(widget="#cat-user")
        await pilot.pause()

        assert app._view_store.get("vis:user") is False
        assert "Hello world" not in all_turns_text(app)
