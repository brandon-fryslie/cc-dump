"""ScrollCoordinator — follow-mode + scroll anchor lifecycle.

// [LAW:one-source-of-truth] Owns follow_store, scroll_anchor,
// scrolling_programmatically flag, and deferred_anchor_resolve_scheduled.
//
// Absorbed variance: the `_scrolling_programmatically` bool was a control-flow
// flag set before every programmatic scroll and checked in watch_scroll_y to
// skip anchor recomputation. Concentrating it behind `programmatic_scroll()`
// context manager (the only writer) means no caller can leak a half-set
// flag, and watch_scroll_y has exactly one place to read it.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING

from snarfx import reaction

from cc_dump.tui.follow_mode import (
    FollowEvent,
    FollowModeStore,
    FollowState,
    FollowTransition,
)

if TYPE_CHECKING:
    from cc_dump.tui.widget_factory import ConversationView, ScrollAnchor

logger = logging.getLogger(__name__)


class ScrollCoordinator:
    """Owns follow state, anchor, and the programmatic-scroll guard."""

    def __init__(self, host: "ConversationView") -> None:
        self._host = host
        self.scroll_anchor: "ScrollAnchor | None" = None
        self.scrolling_programmatically: bool = False
        self.deferred_anchor_resolve_scheduled: bool = False
        self.follow_store = FollowModeStore(self._initial_follow_state())
        # // [LAW:single-enforcer] Follow transition side effects flow from one reaction.
        self.follow_transition_reaction = reaction(
            lambda: self.follow_store.transition.get(),
            self._apply_follow_transition,
            fire_immediately=False,
        )
        # // [LAW:single-enforcer] One projection syncs follow state into view_store.
        self.follow_state_sync_reaction = reaction(
            lambda: self.follow_store.state.get(),
            self._persist_follow_state,
            fire_immediately=True,
        )

    def dispose(self) -> None:
        self.follow_transition_reaction.dispose()
        self.follow_state_sync_reaction.dispose()
        self.follow_store.dispose()

    def _initial_follow_state(self) -> FollowState:
        view_store = self._host._view_store
        follow_raw = view_store.get("nav:follow") if view_store is not None else FollowState.ACTIVE.value
        try:
            return FollowState(str(follow_raw))
        except ValueError:
            # [LAW:dataflow-not-control-flow] exception: guard malformed persisted state.
            return FollowState.ACTIVE

    # ─── Follow state (reads/writes through FollowModeStore) ────────────

    @property
    def follow_state(self) -> FollowState:
        return self.follow_store.state.get()

    @follow_state.setter
    def follow_state(self, value: FollowState) -> None:
        self.follow_store.state.set(value)

    @property
    def is_following(self) -> bool:
        return self.follow_state == FollowState.ACTIVE

    def _persist_follow_state(self, value: FollowState) -> None:
        view_store = self._host._view_store
        if view_store is not None:
            view_store.set("nav:follow", value.value)

    def dispatch_follow_event(
        self,
        event: FollowEvent,
        *,
        at_bottom: bool,
    ) -> None:
        self.follow_store.dispatch(event, at_bottom=bool(at_bottom))

    def _apply_follow_transition(self, payload: tuple[int, FollowTransition]) -> None:
        _seq, transition = payload
        if transition.scroll_to_end:
            with self.programmatic_scroll():
                self._host.scroll_end(animate=False)

    # ─── Programmatic scroll guard ──────────────────────────────────────

    @contextmanager
    def programmatic_scroll(self):
        """Guard scroll operations from anchor recomputation."""
        self.scrolling_programmatically = True
        try:
            yield
        finally:
            self.scrolling_programmatically = False

    def scroll_programmatically_to(self, *, y: int) -> None:
        with self.programmatic_scroll():
            self._host.scroll_to(y=y, animate=False)

    # ─── Public scroll API (invoked from host delegations) ──────────────

    def toggle_follow(self) -> None:
        self.dispatch_follow_event(FollowEvent.TOGGLE, at_bottom=False)

    def scroll_to_bottom(self) -> None:
        self.dispatch_follow_event(FollowEvent.SCROLL_BOTTOM, at_bottom=False)

    def scroll_to_top(self) -> None:
        self.dispatch_follow_event(FollowEvent.DEACTIVATE, at_bottom=False)
        with self.programmatic_scroll():
            self._host.scroll_home(animate=False)

    def scroll_to_block(self, turn_index: int, block_index: int) -> None:
        host = self._host
        turns = host._turn_store.turns
        if turn_index >= len(turns):
            return
        td = turns[turn_index]
        strip_offset = td.strip_offset_for_block(block_index)
        turn_offset = host._turn_store.offset_tree.prefix_sum(turn_index)
        if strip_offset is None:
            target_y = turn_offset
        else:
            target_y = turn_offset + strip_offset
        viewport_height = host.scrollable_content_region.height
        centered_y = max(0, target_y - viewport_height // 2)
        self.dispatch_follow_event(FollowEvent.DEACTIVATE, at_bottom=False)
        with self.programmatic_scroll():
            host.scroll_to(y=centered_y, animate=False)

    def current_scroll_y(self) -> float:
        return float(self._host.scroll_offset.y)

    def restore_scroll_y(self, y: float) -> None:
        with self.programmatic_scroll():
            self._host.scroll_to(y=y, animate=False)
        # // [LAW:one-source-of-truth] Refresh anchor after programmatic restore
        # // because watch_scroll_y skips recompute while the guard is active.
        self.capture_scroll_anchor()

    # ─── Scroll anchor lifecycle ────────────────────────────────────────

    def capture_scroll_anchor(self) -> None:
        self.scroll_anchor = self.compute_anchor_from_scroll()

    def compute_anchor_from_scroll(self) -> "ScrollAnchor | None":
        from cc_dump.tui.widget_factory import ScrollAnchor
        host = self._host
        turns = host._turn_store.turns
        if not turns:
            return None
        scroll_y = int(host.scroll_offset.y)
        turn = host._turn_store.find_turn_for_line(scroll_y)
        if turn is None:
            return None
        line_in_turn = scroll_y - host._turn_store.offset_tree.prefix_sum(turn.turn_index)
        return ScrollAnchor(turn_index=turn.turn_index, line_in_turn=max(0, line_in_turn))

    def last_visible_turn_index(self) -> int | None:
        turns = self._host._turn_store.turns
        for idx in range(len(turns) - 1, -1, -1):
            if turns[idx].line_count > 0:
                return idx
        return None

    def resolve_anchor_turn_index(self, *, anchor_turn_index: int) -> int | None:
        turns = self._host._turn_store.turns
        turn_count = len(turns)
        if turn_count == 0:
            return None
        if anchor_turn_index >= turn_count:
            return self.last_visible_turn_index()
        start = min(max(anchor_turn_index, 0), turn_count - 1)
        for step in range(turn_count):
            idx = (start + step) % turn_count
            if turns[idx].line_count > 0:
                return idx
        return None

    def resolve_anchor(self) -> None:
        """Resolve stored anchor to scroll_y after content changes."""
        host = self._host
        anchor = self.scroll_anchor
        if anchor is None:
            return
        resolved_turn_index = self.resolve_anchor_turn_index(
            anchor_turn_index=anchor.turn_index
        )
        if resolved_turn_index is None:
            return
        turn = host._turn_store.turns[resolved_turn_index]
        line_in_turn = (
            min(anchor.line_in_turn, turn.line_count - 1)
            if resolved_turn_index == anchor.turn_index
            else 0
        )
        target_y = host._turn_store.offset_tree.prefix_sum(resolved_turn_index) + line_in_turn
        self.scroll_programmatically_to(y=target_y)

    def rebase_scroll_anchor_after_prune(self, pruned_count: int) -> None:
        from cc_dump.tui.widget_factory import ScrollAnchor
        anchor = self.scroll_anchor
        if anchor is None:
            return
        self.scroll_anchor = ScrollAnchor(
            turn_index=max(0, anchor.turn_index - pruned_count),
            line_in_turn=anchor.line_in_turn,
        )

    # ─── Deferred anchor resolve (coalescing) ───────────────────────────

    def schedule_deferred_anchor_resolve(self) -> None:
        if self.deferred_anchor_resolve_scheduled:
            return
        self.deferred_anchor_resolve_scheduled = True
        self._host.call_later(self.flush_deferred_anchor_resolve)

    def flush_deferred_anchor_resolve(self) -> None:
        self.deferred_anchor_resolve_scheduled = False
        if not self.is_following:
            self.resolve_anchor()
        self._host.refresh()

    # ─── User-scroll entry point (from watch_scroll_y) ──────────────────

    def on_user_scroll(self) -> None:
        """Called from ConversationView.watch_scroll_y when scroll changed by user."""
        self.scroll_anchor = self.compute_anchor_from_scroll()
        self.dispatch_follow_event(
            FollowEvent.USER_SCROLL,
            at_bottom=bool(self._host.is_vertical_scroll_end),
        )
