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
        self._proxy_url: str = ""
        self._request_count: int = 0

    @property
    def _connected(self) -> bool:
        """// [LAW:one-source-of-truth] Derived from last_message_time."""
        if self._last_message_time is None:
            return False
        return (time.monotonic() - self._last_message_time) < _CONNECTION_TIMEOUT_S

    def refresh_session_state(
        self,
        session_id: str | None,
        last_message_time: float | None,
        proxy_url: str,
        request_count: int,
    ) -> None:
        """Update session state and refresh display."""
        self._session_id = session_id
        self._last_message_time = last_message_time
        self._proxy_url = proxy_url
        self._request_count = request_count
        self._refresh_display()

    def _refresh_display(self) -> None:
        rich_text = cc_dump.tui.panel_renderers.render_session_panel(
            connected=self._connected,
            session_id=self._session_id,
            last_message_time=self._last_message_time,
            proxy_url=self._proxy_url,
            request_count=self._request_count,
        )
        self.update(rich_text)

    def refresh_from_store(self, store, **kwargs) -> None:
        """No-op — session panel doesn't use the analytics store."""

    def cycle_mode(self) -> None:
        """No-op — session panel has no sub-modes."""

    def get_state(self) -> dict:
        return {
            "session_id": self._session_id,
            "last_message_time": self._last_message_time,
            "proxy_url": self._proxy_url,
            "request_count": self._request_count,
        }

    def restore_state(self, state: dict) -> None:
        self._session_id = state.get("session_id")
        self._last_message_time = state.get("last_message_time")
        self._proxy_url = state.get("proxy_url", "")
        self._request_count = state.get("request_count", 0)
        self._refresh_display()


def create_session_panel() -> SessionPanel:
    """Factory function for creating a SessionPanel instance."""
    return SessionPanel()
