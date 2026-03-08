"""App lifecycle management for Textual in-process tests.

Creates CcDumpApp instances wired for testing and manages run_test() lifecycle.
State isolation: every call creates fresh queue, router, state dict, and app.
"""

import queue
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable

from textual.pilot import Pilot

from cc_dump.app.analytics_store import AnalyticsStore
from cc_dump.pipeline.router import EventRouter, QueueSubscriber
from cc_dump.tui.app import CcDumpApp


@asynccontextmanager
async def run_app(
    *,
    size: tuple[int, int] = (120, 40),
    replay_data: list | None = None,
    message_hook: Callable | None = None,
) -> AsyncIterator[tuple[Pilot, CcDumpApp]]:
    """Create and run a CcDumpApp in test mode.

    Yields (pilot, app) tuple. The router is NOT started (no background thread).
    Events can be injected by putting them on the QueueSubscriber's queue.

    Args:
        size: Terminal dimensions (width, height).
        replay_data: Optional HAR replay data list.
        message_hook: Optional Textual message hook for MessageCapture.
    """
    # [LAW:no-shared-mutable-globals] Fresh state for every test
    source_queue = queue.Queue()
    router = EventRouter(source_queue)
    tui_sub = QueueSubscriber()
    router.add_subscriber(tui_sub)
    # Router NOT started — no background thread

    state = {
        "request_counter": 0,
    }

    # Create in-memory analytics store for testing
    analytics_store = AnalyticsStore()

    # Create view store for visibility state
    import cc_dump.app.view_store
    view_store = cc_dump.app.view_store.create()

    app = CcDumpApp(
        event_queue=tui_sub.queue,
        state=state,
        router=router,
        analytics_store=analytics_store,
        replay_data=replay_data,
        view_store=view_store,
    )

    async with app.run_test(
        size=size,
        message_hook=message_hook,
    ) as pilot:
        # Ensure on_mount processing (including replay) has completed
        await pilot.pause()

        # View-store reactions are bound by app.on_mount(); keep a compatibility
        # fallback for older app instances that don't provide mount binding.
        if not getattr(view_store, "_reaction_disposers", None):
            bind_reactions = getattr(app, "_bind_view_store_reactions", None)
            if callable(bind_reactions):
                bind_reactions()
            else:
                view_store._reaction_disposers = cc_dump.app.view_store.setup_reactions(
                    view_store, {"app": app}
                )

        yield pilot, app
