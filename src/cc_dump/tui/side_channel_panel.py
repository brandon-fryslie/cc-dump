"""AI Workbench sidebar panel.

This module is RELOADABLE. When it reloads, any mounted panel is
removed during hot-reload (stateless, user can re-open with X).
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widget import Widget
from textual.widgets import Checkbox, Input, Select, Static

from cc_dump.core.analysis import fmt_tokens
from cc_dump.ai.utility_catalog import UtilityRegistry
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
class QAComposerDraft:
    """Raw composer input collected from the panel widgets."""

    question: str
    scope_mode: str
    source_start_text: str
    source_end_text: str
    indices_text: str
    explicit_whole_session: bool


@dataclass(frozen=True)
class ActionReviewDraft:
    """Raw action/deferred review selections from panel widgets."""

    accept_indices_text: str
    reject_indices_text: str
    create_beads: bool


@dataclass(frozen=True)
class UtilityLaunchDraft:
    """Selected utility from bounded launcher."""

    utility_id: str


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
                key="qa_estimate",
                intent="ask",
                label="Estimate Q&A",
                action="app.sc_qa_estimate",
                availability="ready",
                owner_ticket="cc-dump-mjb.1",
            ),
            WorkbenchControlSpec(
                key="qa_submit",
                intent="ask",
                label="Ask Scoped Q&A",
                action="app.sc_qa_submit",
                availability="ready",
                owner_ticket="cc-dump-mjb.1",
            ),
        ),
    ),
    WorkbenchControlGroup(
        title="Extract",
        controls=(
            WorkbenchControlSpec(
                key="action_extract",
                intent="extract",
                label="Extract Actions",
                action="app.sc_action_extract",
                availability="ready",
                owner_ticket="cc-dump-mjb.3",
            ),
            WorkbenchControlSpec(
                key="action_apply_review",
                intent="extract",
                label="Apply Review",
                action="app.sc_action_apply_review",
                availability="ready",
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
                key="utility_run",
                intent="utility",
                label="Run Utility",
                action="app.sc_utility_run",
                availability="ready",
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
        border-left: solid $secondary-muted;
        padding: 1;
        height: 1fr;
        layout: vertical;
        background: $panel;
        color: $text;
    }

    SideChannelPanel #sc-title {
        text-style: bold;
        margin-bottom: 1;
        color: $text-primary;
    }

    SideChannelPanel #sc-status {
        margin-bottom: 1;
        color: $text-secondary;
        background: $panel-darken-1;
        padding: 0 1;
    }

    SideChannelPanel #sc-usage-summary {
        color: $text-muted;
        margin-bottom: 1;
    }

    SideChannelPanel .sc-group-title {
        text-style: bold;
        color: $text-secondary;
        margin-top: 1;
        border-top: solid $border-blurred;
        padding-top: 1;
    }

    SideChannelPanel Chip {
        width: auto;
        height: 1;
        margin-bottom: 1;
    }

    SideChannelPanel Chip.-dim {
        background: $surface;
        color: $text-disabled;
    }

    SideChannelPanel #sc-qa-question {
        margin-top: 1;
    }

    SideChannelPanel #sc-qa-scope {
        margin-top: 1;
    }

    SideChannelPanel #sc-qa-range-row Input {
        width: 1fr;
    }

    SideChannelPanel #sc-qa-indices {
        margin-top: 1;
    }

    SideChannelPanel #sc-qa-whole {
        margin-top: 1;
        margin-bottom: 1;
    }

    SideChannelPanel #sc-action-accept {
        margin-top: 1;
    }

    SideChannelPanel #sc-action-reject {
        margin-top: 1;
    }

    SideChannelPanel #sc-action-beads {
        margin-top: 1;
        margin-bottom: 1;
    }

    SideChannelPanel #sc-utility-select {
        margin-top: 1;
        margin-bottom: 1;
    }

    SideChannelPanel #sc-result-scroll {
        height: 1fr;
        margin-top: 1;
        border: round $border;
        background: $surface-darken-1;
        padding: 0 1;
    }

    SideChannelPanel #sc-meta {
        text-style: italic;
        color: $text-muted;
        margin-top: 1;
        background: $panel-darken-1;
        padding: 0 1;
    }

    SideChannelPanel #sc-usage {
        margin-top: 1;
        color: $text-muted;
    }

    SideChannelPanel Input,
    SideChannelPanel Select {
        background: $surface;
        color: $text;
        border: round $border;
    }

    SideChannelPanel Input:focus,
    SideChannelPanel Select:focus {
        border: round $primary;
        background: $surface-lighten-1;
    }

    SideChannelPanel Checkbox {
        color: $text-secondary;
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
        yield Static("Q&A Scope", classes="sc-group-title")
        yield Input(placeholder="Ask about this conversation history…", id="sc-qa-question")
        yield Select(
            [
                ("Selected Range", "selected_range"),
                ("Selected Indices", "selected_indices"),
                ("Whole Session", "whole_session"),
            ],
            value="selected_range",
            allow_blank=False,
            id="sc-qa-scope",
        )
        with Horizontal(id="sc-qa-range-row"):
            yield Input(placeholder="start idx", id="sc-qa-start")
            yield Input(placeholder="end idx", id="sc-qa-end")
        yield Input(placeholder="indices (e.g. 0,4,7)", id="sc-qa-indices")
        yield Checkbox("Confirm whole-session scope", id="sc-qa-whole")
        yield Static("Action Review", classes="sc-group-title")
        yield Input(placeholder="accept indices (e.g. 0,2)", id="sc-action-accept")
        yield Input(placeholder="reject indices (e.g. 1,3)", id="sc-action-reject")
        yield Checkbox("Create beads for accepted items", id="sc-action-beads")
        yield Static("Utility Launcher", classes="sc-group-title")
        yield Select(
            _utility_options(),
            value=_utility_default_value(),
            allow_blank=False,
            id="sc-utility-select",
        )
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

    def read_qa_draft(self) -> QAComposerDraft:
        """Read composer values for app-level scope normalization/dispatch."""
        scope_widget = self.query_one("#sc-qa-scope", Select)
        scope_value = scope_widget.value
        return QAComposerDraft(
            question=self.query_one("#sc-qa-question", Input).value.strip(),
            scope_mode=scope_value if isinstance(scope_value, str) else "selected_range",
            source_start_text=self.query_one("#sc-qa-start", Input).value.strip(),
            source_end_text=self.query_one("#sc-qa-end", Input).value.strip(),
            indices_text=self.query_one("#sc-qa-indices", Input).value.strip(),
            explicit_whole_session=self.query_one("#sc-qa-whole", Checkbox).value,
        )

    def read_action_review_draft(self) -> ActionReviewDraft:
        """Read action review accept/reject + beads confirmation inputs."""
        return ActionReviewDraft(
            accept_indices_text=self.query_one("#sc-action-accept", Input).value.strip(),
            reject_indices_text=self.query_one("#sc-action-reject", Input).value.strip(),
            create_beads=self.query_one("#sc-action-beads", Checkbox).value,
        )

    def read_utility_draft(self) -> UtilityLaunchDraft:
        """Read selected utility from bounded launcher select."""
        value = self.query_one("#sc-utility-select", Select).value
        utility_id = value if isinstance(value, str) else _utility_default_value()
        return UtilityLaunchDraft(utility_id=utility_id)


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
            "qa_estimate": "Q&A Estimate",
            "qa_submit": "Scoped Q&A",
            "action_extract": "Action Extraction",
            "action_apply_review": "Apply Review",
            "utility_run": "Utility Runner",
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


def render_qa_estimate_line(
    *,
    scope_mode: str,
    message_count: int,
    estimated_input_tokens: int,
    estimated_output_tokens: int,
    estimated_total_tokens: int,
) -> str:
    """Render deterministic estimate text for pre-send and post-send display."""
    return (
        "estimate: scope={} messages={} in={} out={} total={}".format(
            scope_mode,
            message_count,
            fmt_tokens(estimated_input_tokens),
            fmt_tokens(estimated_output_tokens),
            fmt_tokens(estimated_total_tokens),
        )
    )


def render_qa_scope_line(*, scope_mode: str, selected_indices: tuple[int, ...]) -> str:
    """Render selected scope summary for the panel result area."""
    return f"scope:{scope_mode} indices={list(selected_indices)}"


def parse_review_indices(text: str) -> tuple[tuple[int, ...], str]:
    """Parse comma-delimited review indexes from panel input."""
    stripped = text.strip()
    if not stripped:
        return ((), "")
    parts = [part.strip() for part in stripped.split(",") if part.strip()]
    try:
        parsed = tuple(sorted({int(part) for part in parts}))
    except ValueError:
        return ((), "review indices must be integers")
    negative = [idx for idx in parsed if idx < 0]
    if negative:
        return ((), "review indices must be non-negative")
    return (parsed, "")


def _utility_specs():
    return UtilityRegistry().list()


def _utility_options() -> list[tuple[str, str]]:
    specs = _utility_specs()
    if not specs:
        return [("(none)", "")]
    return [(spec.title, spec.utility_id) for spec in specs]


def _utility_default_value() -> str:
    specs = _utility_specs()
    return specs[0].utility_id if specs else ""
