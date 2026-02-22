"""Side-channel panel — test UI for AI-powered summaries.

This module is RELOADABLE. When it reloads, any mounted panel is
removed during hot-reload (stateless, user can re-open with X).
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from cc_dump.tui.chip import Chip


@dataclass
class SideChannelPanelState:
    """Display state pushed from app.py to the panel."""

    enabled: bool
    loading: bool
    result_text: str
    result_source: str  # "ai" | "fallback" | "error" | ""
    result_elapsed_ms: int
    purpose_usage: dict[str, dict[str, int]]


class SideChannelPanel(Widget):
    """Docked panel for side-channel AI interaction."""

    DEFAULT_CSS = """
    SideChannelPanel {
        dock: right;
        width: 40%;
        min-width: 30;
        max-width: 60;
        border-left: solid $accent;
        padding: 1;
        height: 1fr;
        layout: vertical;
    }

    SideChannelPanel #sc-title {
        text-style: bold;
        margin-bottom: 1;
    }

    SideChannelPanel #sc-status {
        margin-bottom: 1;
    }

    SideChannelPanel Chip {
        width: auto;
        height: 1;
        text-style: bold;
        margin-bottom: 1;
    }

    SideChannelPanel Chip:hover {
        opacity: 0.8;
    }

    SideChannelPanel Chip.-dim {
        opacity: 0.5;
    }

    SideChannelPanel Chip.-dim:hover {
        opacity: 0.7;
    }

    SideChannelPanel #sc-result-scroll {
        height: 1fr;
    }

    SideChannelPanel #sc-meta {
        text-style: italic;
        color: $text-muted;
        margin-top: 1;
    }

    SideChannelPanel #sc-usage {
        margin-top: 1;
        color: $text-muted;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("AI Side Channel", id="sc-title")
        yield Static("Status: Enabled", id="sc-status")
        yield Chip(" Summarize Last 10 Messages ", action="app.sc_summarize", id="sc-summarize")
        yield Chip(" Toggle AI ", action="app.sc_toggle", id="sc-toggle")
        with VerticalScroll(id="sc-result-scroll"):
            yield Static("", id="sc-result")
        yield Static("", id="sc-meta")
        yield Static("Purpose usage: (none)", id="sc-usage")

    def update_display(self, state: SideChannelPanelState) -> None:
        """Update child widgets from state."""
        # Status
        status = self.query_one("#sc-status", Static)
        status.update(f"Status: {'Enabled' if state.enabled else 'Disabled'}")

        # Toggle chip label
        toggle = self.query_one("#sc-toggle", Chip)
        toggle.update(" Disable AI " if state.enabled else " Enable AI ")

        # Summarize chip
        chip = self.query_one("#sc-summarize", Chip)
        chip.update(" Working... " if state.loading else " Summarize Last 10 Messages ")
        chip.set_class(state.loading, "-dim")

        # Result text
        result = self.query_one("#sc-result", Static)
        result.update(state.result_text)

        # Metadata line
        meta = self.query_one("#sc-meta", Static)
        parts: list[str] = []
        if state.result_source:
            parts.append(f"Source: {state.result_source}")
        if state.result_elapsed_ms > 0:
            parts.append(f"{state.result_elapsed_ms}ms")
        meta.update("  ".join(parts))

        usage = self.query_one("#sc-usage", Static)
        usage.update(_render_purpose_usage(state.purpose_usage))

    def get_state(self) -> dict:
        return {}  # Stateless

    def restore_state(self, state: dict) -> None:
        pass


def create_side_channel_panel() -> SideChannelPanel:
    """Create a new SideChannelPanel instance."""
    return SideChannelPanel()


def _render_purpose_usage(usage: dict[str, dict[str, int]]) -> str:
    if not usage:
        return "Purpose usage: (none)"
    rows: list[str] = ["Purpose usage:"]
    ordered = sorted(
        usage.items(),
        key=lambda item: (
            -int(item[1].get("turns", 0)),
            -int(item[1].get("input_tokens", 0)),
            item[0],
        ),
    )
    for purpose, row in ordered:
        rows.append(
            "  {}  runs={}  in={}  cache_read={}  cache_create={}  out={}".format(
                purpose,
                int(row.get("turns", 0)),
                int(row.get("input_tokens", 0)),
                int(row.get("cache_read_tokens", 0)),
                int(row.get("cache_creation_tokens", 0)),
                int(row.get("output_tokens", 0)),
            )
        )
    return "\n".join(rows)
