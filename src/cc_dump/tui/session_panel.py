"""Session panel — shows Claude Code connection status.

This module is RELOADABLE. Uses module-level imports for hot-reload.

// [LAW:one-source-of-truth] Connection state derived from last_message_time.
"""

import time

from textual.widgets import Static

import cc_dump.tui.panel_renderers

_CONNECTION_TIMEOUT_S = 120.0


class SessionPanel(Static):
    """Displays Claude Code connection status, session ID, and request count.

    "Connected" = last_message_time exists AND age < _CONNECTION_TIMEOUT_S.
    """

    def __init__(self):
        super().__init__("")
        self._session_id: str | None = None
        self._last_message_time: float | None = None
        self._session_id_span: tuple[int, int] | None = None

    @property
    def _connected(self) -> bool:
        """// [LAW:one-source-of-truth] Derived from last_message_time."""
        if self._last_message_time is None:
            return False
        return (time.monotonic() - self._last_message_time) < _CONNECTION_TIMEOUT_S

    def on_mount(self) -> None:
        """Start 1s timer for live age updates. Textual auto-stops on widget removal."""
        self.set_interval(1.0, self._refresh_display)

    def refresh_session_state(
        self,
        session_id: str | None,
        last_message_time: float | None,
    ) -> None:
        """Update session state and refresh display."""
        self._session_id = session_id
        self._last_message_time = last_message_time
        self._refresh_display()

    def _refresh_display(self) -> None:
        rich_text, self._session_id_span = cc_dump.tui.panel_renderers.render_session_panel(
            connected=self._connected,
            session_id=self._session_id,
            last_message_time=self._last_message_time,
        )
        self.update(rich_text)

    def on_click(self, event) -> None:
        """Copy session ID to clipboard when clicking on the session ID span."""
        if self._session_id_span is not None and self._session_id:
            start, end = self._session_id_span
            if start <= event.x < end:
                self.app.copy_to_clipboard(self._session_id)
                self.app.notify("Copied session ID", severity="information")

    def refresh_from_store(self, store, **kwargs) -> None:
        """No-op — session panel doesn't use the analytics store."""

    def cycle_mode(self) -> None:
        """No-op — session panel has no sub-modes."""

    def get_state(self) -> dict:
        return {
            "session_id": self._session_id,
            "last_message_time": self._last_message_time,
        }

    def restore_state(self, state: dict) -> None:
        self._session_id = state.get("session_id")
        self._last_message_time = state.get("last_message_time")
        self._refresh_display()


def create_session_panel() -> SessionPanel:
    """Factory function for creating a SessionPanel instance."""
    return SessionPanel()
