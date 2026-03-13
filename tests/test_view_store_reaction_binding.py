"""Regression test for view-store reaction binding order."""

import queue
from types import SimpleNamespace

import pytest

import cc_dump.app.view_store
from cc_dump.core.formatting_impl import ProviderRuntimeState
from cc_dump.tui.app import CcDumpApp
from tests.harness import all_turns_text, make_replay_entry


pytestmark = pytest.mark.textual


async def test_pre_run_view_store_reactions_rebind_on_mount():
    """Filter chip clicks rerender conversation even when reactions were pre-bound.

    Simulates CLI startup order where view-store reactions are configured before app.run().
    """
    state = ProviderRuntimeState()
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
