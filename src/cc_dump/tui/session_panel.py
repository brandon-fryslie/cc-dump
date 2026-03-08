"""Session panel — shows Claude Code connection status.

This module is RELOADABLE. Uses module-level imports for hot-reload.

// [LAW:one-source-of-truth] Connection state derived from last_message_time.
"""

from dataclasses import dataclass
import time

from snarfx import Observable, reaction
from snarfx import textual as stx
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
        self._store_reaction_disposer = None
        self._session_id_span: tuple[int, int] | None = None
        # [LAW:single-enforcer] One reactive projection owns panel text/span rendering.
        self._state_reaction = reaction(
            lambda: self._state.get(),
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
        self._bind_store_reaction()
        self._pull_from_app()
        self._render_session(self._state.get())

    def _bind_store_reaction(self) -> None:
        app = getattr(self, "app", None)
        view_store = getattr(app, "_view_store", None) if app is not None else None
        if app is None or view_store is None:
            return
        # [LAW:single-enforcer] Session panel pulls only when store revision changes.
        self._store_reaction_disposer = stx.reaction(
            app,
            lambda: (
                view_store.get("session:revision"),
                view_store.get("panel:active"),
            ),
            self._pull_from_store_signal,
        )

    def on_unmount(self) -> None:
        if callable(self._store_reaction_disposer):
            self._store_reaction_disposer()
            self._store_reaction_disposer = None
        self._state_reaction.dispose()

    def _pull_from_store_signal(self, _signal: tuple[object, object]) -> None:
        self._pull_from_app()

    def _render_projection(self, state: SessionPanelState) -> None:
        self._render_session(state)

    def _apply_store_state(self, payload: object) -> None:
        # [LAW:dataflow-not-control-flow] Canonical payload shape drives rendering values.
        state_dict = payload if isinstance(payload, dict) else {}
        raw_session_id = state_dict.get("session_id")
        session_id = raw_session_id if isinstance(raw_session_id, str) else None
        raw_last_message_time = state_dict.get("last_message_time")
        last_message_time = (
            float(raw_last_message_time)
            if isinstance(raw_last_message_time, (int, float))
            else None
        )
        self.update_display(
            SessionPanelState(
                session_id=session_id,
                last_message_time=last_message_time,
            )
        )

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

    def _pull_from_app(self) -> None:
        # [LAW:dataflow-not-control-flow] exception: pull requires mounted widget/app context.
        if not self.is_attached:
            return
        app = getattr(self, "app", None)
        if app is None:
            return
        state_getter = getattr(app, "_get_active_session_panel_state", None)
        if callable(state_getter):
            session_id, last_message_time = state_getter()
        else:
            session_id = getattr(app, "_session_id", None)
            app_state = getattr(app, "_app_state", {})
            last_message_time = app_state.get("last_message_time")
        self.refresh_session_state(
            session_id=session_id,
            last_message_time=last_message_time,
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

    def refresh_from_store(self, store=None, **kwargs) -> None:
        """Back-compat seam: pull from app-owned session state."""
        _ = (store, kwargs)
        self._pull_from_app()

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
