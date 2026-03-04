"""Session panel — shows Claude Code connection status.

This module is RELOADABLE. Uses module-level imports for hot-reload.

// [LAW:one-source-of-truth] Connection state derived from last_message_time.
"""

from dataclasses import dataclass
import time

from snarfx import Observable, reaction
from textual.widgets import Static

import cc_dump.tui.panel_renderers

_CONNECTION_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class SessionPanelState:
    session_id: str | None = None
    last_message_time: float | None = None


class SessionPanel(Static):
    """Displays Claude Code connection status, session ID, and request count.

    "Connected" = last_message_time exists AND age < _CONNECTION_TIMEOUT_S.
    """

    def __init__(self):
        super().__init__("")
        self._state: Observable[SessionPanelState] = Observable(SessionPanelState())
        self._clock_tick: Observable[int] = Observable(0)
        self._session_id_span: tuple[int, int] | None = None
        # [LAW:single-enforcer] One reactive projection owns panel text/span rendering.
        self._state_reaction = reaction(
            lambda: (self._clock_tick.get(), self._state.get()),
            self._render_projection,
            fire_immediately=False,
        )

    @property
    def _session_id(self) -> str | None:
        return self._state.get().session_id

    @property
    def _connected(self) -> bool:
        """Backward-compatible accessor for tests/consumers."""
        return self._connected_from_state(self._state.get())

    @staticmethod
    def _connected_from_state(state: SessionPanelState) -> bool:
        """// [LAW:one-source-of-truth] Connected is derived from projected state."""
        if state.last_message_time is None:
            return False
        return (time.monotonic() - state.last_message_time) < _CONNECTION_TIMEOUT_S

    def on_mount(self) -> None:
        """Start 1s timer for live age updates. Textual auto-stops on widget removal."""
        self.set_interval(1.0, self._tick_clock)
        self._render_session(self._state.get())

    def on_unmount(self) -> None:
        self._state_reaction.dispose()

    def _tick_clock(self) -> None:
        self._clock_tick.set(self._clock_tick.get() + 1)

    def _render_projection(self, projection: tuple[int, SessionPanelState]) -> None:
        _, state = projection
        self._render_session(state)

    def refresh_session_state(
        self,
        session_id: str | None,
        last_message_time: float | None,
    ) -> None:
        """Update session state and refresh display."""
        self._state.set(
            SessionPanelState(
                session_id=session_id,
                last_message_time=last_message_time,
            )
        )

    def _render_session(self, state: SessionPanelState) -> None:
        rich_text, self._session_id_span = cc_dump.tui.panel_renderers.render_session_panel(
            connected=self._connected_from_state(state),
            session_id=state.session_id,
            last_message_time=state.last_message_time,
        )
        if self.is_attached:
            self.update(rich_text)

    def on_click(self, event) -> None:
        """Copy session ID to clipboard when clicking on the session ID span."""
        session_id = self._session_id
        if self._session_id_span is not None and session_id:
            start, end = self._session_id_span
            if start <= event.x < end:
                self.app.copy_to_clipboard(session_id)
                self.app.notify("Copied session ID", severity="information")

    def refresh_from_store(self, store, **kwargs) -> None:
        """No-op — session panel doesn't use the analytics store."""

    def cycle_mode(self) -> None:
        """No-op — session panel has no sub-modes."""

    def get_state(self) -> dict:
        state = self._state.get()
        return {
            "session_id": state.session_id,
            "last_message_time": state.last_message_time,
        }

    def restore_state(self, state: dict) -> None:
        self._state.set(
            SessionPanelState(
                session_id=state.get("session_id"),
                last_message_time=state.get("last_message_time"),
            )
        )


def create_session_panel() -> SessionPanel:
    """Factory function for creating a SessionPanel instance."""
    return SessionPanel()
