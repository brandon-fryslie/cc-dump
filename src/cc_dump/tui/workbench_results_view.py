"""Conversation-area view for AI Workbench results.

RELOADABLE module. This is a read-focused surface for long outputs that don't
fit comfortably in the sidebar panel.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Markdown, Static


class WorkbenchResultsView(Widget):
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
        self._last_text = ""
        self._last_source = ""
        self._last_elapsed_ms = 0
        self._last_action = ""
        self._last_meta = ""

    def compose(self) -> ComposeResult:
        yield Static("Workbench Results", id="workbench-results-title")
        yield Static("", id="workbench-results-meta")
        with VerticalScroll(id="workbench-results-scroll"):
            yield Markdown("No workbench output yet.", id="workbench-results-markdown")

    def update_result(
        self,
        *,
        text: str,
        source: str,
        elapsed_ms: int,
        action: str,
    ) -> None:
        """Update result markdown and metadata line.

        // [LAW:single-enforcer] Result-view formatting is centralized here.
        """
        self._last_text = str(text or "")
        self._last_source = str(source or "")
        self._last_elapsed_ms = int(elapsed_ms or 0)
        self._last_action = str(action or "")

        markdown = self.query_one("#workbench-results-markdown", Markdown)
        markdown.update(self._last_text or "No workbench output yet.")

        meta = self.query_one("#workbench-results-meta", Static)
        parts: list[str] = []
        if self._last_source:
            parts.append(f"source={self._last_source}")
        parts.append(f"elapsed={self._last_elapsed_ms}ms")
        if self._last_action:
            parts.append(f"action={self._last_action}")
        self._last_meta = "  ".join(parts)
        meta.update(self._last_meta)


def create_workbench_results_view() -> WorkbenchResultsView:
    """Factory for app compose."""
    return WorkbenchResultsView()
