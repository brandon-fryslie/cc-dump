"""Conversation-area view for AI Workbench results.

RELOADABLE module. This is a read-focused surface for long outputs that don't
fit comfortably in the sidebar panel.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from snarfx import Observable, reaction
from snarfx import textual as stx
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Markdown, Static
from cc_dump.tui.store_widget import StoreWidget


@dataclass(frozen=True)
class WorkbenchResultState:
    text: str = ""
    source: str = ""
    elapsed_ms: int = 0
    action: str = ""
    context_session_id: str = ""
    meta: str = ""


class WorkbenchResultsView(StoreWidget):
    """Renders the most recent workbench output in a full-width conversation tab."""

    DEFAULT_CSS = """
    WorkbenchResultsView {
        height: 1fr;
        width: 1fr;
        layout: vertical;
        padding: 0 1;
    }

    WorkbenchResultsView #workbench-results-title {
        text-style: bold;
        margin-bottom: 1;
    }

    WorkbenchResultsView #workbench-results-meta {
        color: $text-muted;
        margin-bottom: 1;
    }

    WorkbenchResultsView #workbench-results-scroll {
        height: 1fr;
        border: round $panel-lighten-1;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._result_state: Observable[WorkbenchResultState] = Observable(
            WorkbenchResultState()
        )
        # [LAW:single-enforcer] One reactive projection owns markdown/meta rendering.
        self._result_state_reaction = reaction(
            lambda: self._result_state.get(),
            self._render_result_state,
            fire_immediately=False,
        )

    def compose(self) -> ComposeResult:
        yield Static("Workbench Results", id="workbench-results-title")
        yield Static("", id="workbench-results-meta")
        with VerticalScroll(id="workbench-results-scroll"):
            yield Markdown("No workbench output yet.", id="workbench-results-markdown")

    def on_mount(self) -> None:
        super().on_mount()
        self._render_result_state(self._result_state.get())

    def on_unmount(self) -> None:
        super().on_unmount()
        self._result_state_reaction.dispose()

    def _setup_store_reactions(self) -> list:
        store = getattr(self.app, "_view_store", None)
        if store is None:
            return []
        return [
            stx.reaction(
                self.app,
                lambda: store.workbench_state.get(),
                self._sync_from_store_projection,
                fire_immediately=True,
            )
        ]

    def _sync_from_store_projection(self, projection: dict[str, object]) -> None:
        self.update_result(
            text=str(projection.get("text", "")),
            source=str(projection.get("source", "")),
            elapsed_ms=_read_elapsed_ms(projection),
            action=str(projection.get("action", "")),
            context_session_id=str(projection.get("context_session_id", "")),
        )

    @staticmethod
    def _build_meta_line(state: WorkbenchResultState) -> str:
        parts: list[str] = []
        if state.context_session_id:
            parts.append(f"context={state.context_session_id}")
        if state.source:
            parts.append(f"source={state.source}")
        parts.append(f"elapsed={state.elapsed_ms}ms")
        if state.action:
            parts.append(f"action={state.action}")
        return "  ".join(parts)

    def _render_result_state(self, state: WorkbenchResultState) -> None:
        if not self.is_attached:
            return
        markdown = self.query_one("#workbench-results-markdown", Markdown)
        markdown.update(state.text or "No workbench output yet.")

        meta = self.query_one("#workbench-results-meta", Static)
        meta.update(state.meta)

    def update_result(
        self,
        *,
        text: str,
        source: str,
        elapsed_ms: int,
        action: str,
        context_session_id: str,
    ) -> None:
        """Update result markdown and metadata line.

        // [LAW:single-enforcer] Result-view formatting is centralized here.
        """
        base_state = WorkbenchResultState(
            text=str(text or ""),
            source=str(source or ""),
            elapsed_ms=int(elapsed_ms or 0),
            action=str(action or ""),
            context_session_id=str(context_session_id or ""),
        )
        self._result_state.set(replace(base_state, meta=self._build_meta_line(base_state)))

    @property
    def _last_text(self) -> str:
        return self._result_state.get().text

    @property
    def _last_source(self) -> str:
        return self._result_state.get().source

    @property
    def _last_elapsed_ms(self) -> int:
        return self._result_state.get().elapsed_ms

    @property
    def _last_action(self) -> str:
        return self._result_state.get().action

    @property
    def _last_context_session_id(self) -> str:
        return self._result_state.get().context_session_id

    @property
    def _last_meta(self) -> str:
        return self._result_state.get().meta

    def get_state(self) -> dict[str, object]:
        """Expose latest rendered state for deterministic tests."""
        state = self._result_state.get()
        return {
            "text": state.text,
            "source": state.source,
            "elapsed_ms": state.elapsed_ms,
            "action": state.action,
            "context_session_id": state.context_session_id,
            "meta": state.meta,
        }


def create_workbench_results_view() -> WorkbenchResultsView:
    """Factory for app compose."""
    return WorkbenchResultsView()


def _read_elapsed_ms(projection: dict[str, object]) -> int:
    value = projection.get("elapsed_ms")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
