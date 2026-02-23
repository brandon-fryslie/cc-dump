"""AI Workbench sidebar panel.

This module is RELOADABLE. When it reloads, any mounted panel is
removed during hot-reload (stateless, user can re-open with X).
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from cc_dump.core.analysis import fmt_tokens
from cc_dump.tui.chip import Chip


@dataclass
class SideChannelPanelState:
    """Display state pushed from app.py to the panel."""

    enabled: bool
    loading: bool
    active_action: str
    result_text: str
    result_source: str  # "ai" | "fallback" | "error" | "preview" | ""
    result_elapsed_ms: int
    purpose_usage: dict[str, dict[str, int]]


@dataclass(frozen=True)
class WorkbenchControlSpec:
    key: str
    intent: str
    label: str
    action: str
    availability: str  # "ready" | "placeholder"
    owner_ticket: str


@dataclass(frozen=True)
class WorkbenchControlGroup:
    title: str
    controls: tuple[WorkbenchControlSpec, ...]


WORKBENCH_CONTROL_GROUPS: tuple[WorkbenchControlGroup, ...] = (
    WorkbenchControlGroup(
        title="Summarize",
        controls=(
            WorkbenchControlSpec(
                key="summarize_recent",
                intent="summarize",
                label="Summarize Recent",
                action="app.sc_summarize_recent",
                availability="ready",
                owner_ticket="cc-dump-yv6.1",
            ),
        ),
    ),
    WorkbenchControlGroup(
        title="Ask",
        controls=(
            WorkbenchControlSpec(
                key="qa_composer",
                intent="ask",
                label="Q&A Composer",
                action="app.sc_preview_qa",
                availability="placeholder",
                owner_ticket="cc-dump-p2c.1",
            ),
        ),
    ),
    WorkbenchControlGroup(
        title="Extract",
        controls=(
            WorkbenchControlSpec(
                key="action_review",
                intent="extract",
                label="Action Review",
                action="app.sc_preview_action_review",
                availability="placeholder",
                owner_ticket="cc-dump-mjb.3",
            ),
        ),
    ),
    WorkbenchControlGroup(
        title="Draft",
        controls=(
            WorkbenchControlSpec(
                key="handoff_draft",
                intent="draft",
                label="Handoff Draft",
                action="app.sc_preview_handoff",
                availability="placeholder",
                owner_ticket="cc-dump-mjb.4",
            ),
            WorkbenchControlSpec(
                key="release_notes",
                intent="draft",
                label="Release Notes",
                action="app.sc_preview_release_notes",
                availability="placeholder",
                owner_ticket="cc-dump-mjb.4",
            ),
        ),
    ),
    WorkbenchControlGroup(
        title="Utilities",
        controls=(
            WorkbenchControlSpec(
                key="utility_runner",
                intent="utility",
                label="Utility Runner",
                action="app.sc_preview_utilities",
                availability="placeholder",
                owner_ticket="cc-dump-mjb.6",
            ),
        ),
    ),
)


class SideChannelPanel(Widget):
    """Docked panel for Workbench orchestration controls and status."""

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

    SideChannelPanel #sc-usage-summary {
        color: $text-muted;
        margin-bottom: 1;
    }

    SideChannelPanel .sc-group-title {
        text-style: bold;
        color: $text-muted;
        margin-top: 1;
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
        margin-top: 1;
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
        yield Static("AI Workbench", id="sc-title")
        yield Static("", id="sc-status")
        yield Static("", id="sc-usage-summary")
        for group in WORKBENCH_CONTROL_GROUPS:
            yield Static(group.title, classes="sc-group-title")
            for control in group.controls:
                yield Chip("", action=control.action, id=f"sc-{control.key}")
        with VerticalScroll(id="sc-result-scroll"):
            yield Static("", id="sc-result")
        yield Static("", id="sc-meta")
        yield Static("", id="sc-usage")

    def update_display(self, state: SideChannelPanelState) -> None:
        """Update child widgets from state.

        // [LAW:dataflow-not-control-flow] Every control runs through the same
        rendering pipeline; state values drive action/label classes.
        """
        status = self.query_one("#sc-status", Static)
        status.update(
            _render_status_line(
                enabled=state.enabled,
                loading=state.loading,
                active_action=state.active_action,
            )
        )

        usage_summary = self.query_one("#sc-usage-summary", Static)
        usage_summary.update(_render_usage_summary(state.purpose_usage))

        for control in _iter_controls():
            chip = self.query_one(f"#sc-{control.key}", Chip)
            is_active = state.loading and state.active_action == control.key
            action = _resolve_action(control=control, state=state, is_active=is_active)
            chip._action = action
            chip.update(
                _render_control_label(
                    control=control,
                    state=state,
                    is_active=is_active,
                    actionable=action is not None,
                )
            )
            chip.set_class(action is None, "-dim")

        result = self.query_one("#sc-result", Static)
        result.update(_render_result_preview(state.result_text))

        meta = self.query_one("#sc-meta", Static)
        meta.update(_render_meta(state))

        usage = self.query_one("#sc-usage", Static)
        usage.update(_render_purpose_usage(state.purpose_usage))

    def get_state(self) -> dict:
        return {}  # Stateless

    def restore_state(self, state: dict) -> None:
        pass


def create_side_channel_panel() -> SideChannelPanel:
    """Create a new SideChannelPanel instance."""
    return SideChannelPanel()


def _iter_controls() -> tuple[WorkbenchControlSpec, ...]:
    controls: list[WorkbenchControlSpec] = []
    for group in WORKBENCH_CONTROL_GROUPS:
        controls.extend(group.controls)
    return tuple(controls)


def _resolve_action(
    *,
    control: WorkbenchControlSpec,
    state: SideChannelPanelState,
    is_active: bool,
) -> str | None:
    """Return chip action for deterministic disabled/in-progress behavior.

    // [LAW:single-enforcer] Action enable/disable policy is centralized here.
    """
    if state.loading:
        return control.action if is_active else None
    if control.availability == "ready" and not state.enabled:
        return None
    return control.action


def _render_status_line(*, enabled: bool, loading: bool, active_action: str) -> str:
    if not enabled:
        return "Status: Disabled (enable AI in Settings)"
    if loading:
        action_name = {
            "summarize_recent": "Summarize Recent",
        }.get(active_action, "Workbench run")
        return f"Status: Running {action_name}"
    return "Status: Ready"


def _render_usage_summary(usage: dict[str, dict[str, int]]) -> str:
    total_runs = sum(int(row.get("turns", 0)) for row in usage.values())
    total_purposes = sum(1 for row in usage.values() if int(row.get("turns", 0)) > 0)
    if total_runs <= 0:
        return "Usage: no runs yet"
    return f"Usage: {total_runs} runs across {total_purposes} purposes"


def _render_control_label(
    *,
    control: WorkbenchControlSpec,
    state: SideChannelPanelState,
    is_active: bool,
    actionable: bool,
) -> str:
    if control.availability != "ready":
        return f" {control.label} ({control.owner_ticket}) "
    if is_active:
        return f" {control.label} [running] "
    if not actionable and not state.enabled:
        return f" {control.label} [disabled] "
    return f" {control.label} "


def _render_result_preview(text: str) -> str:
    if not text:
        return "No workbench output yet."
    lines = text.splitlines()
    limit = 16
    if len(lines) <= limit:
        return text
    hidden = len(lines) - limit
    preview = "\n".join(lines[:limit])
    return f"{preview}\n… {hidden} more lines"


def _render_meta(state: SideChannelPanelState) -> str:
    parts: list[str] = []
    if state.result_source:
        parts.append(f"Source: {state.result_source}")
    if state.result_elapsed_ms > 0:
        parts.append(f"{state.result_elapsed_ms}ms")
    if state.active_action:
        parts.append(f"Action: {state.active_action}")
    return "  ".join(parts)


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
                fmt_tokens(int(row.get("input_tokens", 0))),
                fmt_tokens(int(row.get("cache_read_tokens", 0))),
                fmt_tokens(int(row.get("cache_creation_tokens", 0))),
                fmt_tokens(int(row.get("output_tokens", 0))),
            )
        )
    return "\n".join(rows)
