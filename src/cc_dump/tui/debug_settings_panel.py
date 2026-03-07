"""Debug settings panel — runtime toggles for logging and diagnostics.

This module is RELOADABLE. Changes are live and session-only (no disk persistence).
"""

from __future__ import annotations

import logging
import tracemalloc

from snarfx import Observable, reaction
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Label, Select, Static

from cc_dump.tui.chip import ToggleChip

import cc_dump.core.palette
import cc_dump.io.perf_logging


def _initial_memory_snapshots_enabled(app_ref) -> bool:
    return bool(getattr(app_ref, "_memory_snapshot_enabled", False)) if app_ref else False


class DebugSettingsPanel(VerticalScroll):
    """Side panel for runtime debug toggles. Changes apply immediately."""

    DEFAULT_CSS = """
    DebugSettingsPanel {
        dock: right;
        width: 35%;
        min-width: 30;
        max-width: 50;
        border-left: solid $accent;
        padding: 0 1;
        height: 1fr;
    }
    DebugSettingsPanel .panel-title {
        text-style: bold;
        margin-bottom: 0;
    }
    DebugSettingsPanel .field-desc {
        color: $text-muted;
        text-style: italic;
        padding-left: 2;
        margin-bottom: 0;
    }
    DebugSettingsPanel .panel-footer {
        margin-top: 1;
        color: $text-muted;
    }
    DebugSettingsPanel ToggleChip {
        margin-top: 1;
    }
    DebugSettingsPanel Select {
        width: 1fr;
        margin-top: 1;
    }
    DebugSettingsPanel .select-label {
        text-style: bold;
        margin-top: 1;
    }
    """

    def __init__(self, *, app_ref=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._app_ref = app_ref
        perf_enabled = bool(cc_dump.io.perf_logging.is_enabled())
        mem_enabled = _initial_memory_snapshots_enabled(self._app_ref)
        self._toggle_state: Observable[tuple[bool, bool]] = Observable((perf_enabled, mem_enabled))
        # [LAW:single-enforcer] One reactive projection owns runtime debug side effects.
        self._toggle_reaction = reaction(
            lambda: self._toggle_state.get(),
            self._apply_toggle_state,
            fire_immediately=True,
        )

    def compose(self) -> ComposeResult:
        p = cc_dump.core.palette.PALETTE

        yield Static("Debug Settings", classes="panel-title")

        # Log level
        current_level = logging.getLogger("cc_dump").getEffectiveLevel()
        current_name = logging.getLevelName(current_level)
        options = [("DEBUG", "DEBUG"), ("INFO", "INFO"), ("WARNING", "WARNING"), ("ERROR", "ERROR")]
        yield Label("Log Level", classes="select-label")
        yield Select(options, value=current_name, allow_blank=False, id="debug-log-level")
        yield Static("Runtime log level for cc_dump logger", classes="field-desc")

        # Perf logging
        yield ToggleChip(
            "Perf Logging",
            value=cc_dump.io.perf_logging.is_enabled(),
            id="debug-perf-logging",
            on_change=self._handle_debug_toggle,
        )
        yield Static("Stack traces when render stages exceed thresholds", classes="field-desc")

        # Memory snapshots
        mem_enabled = bool(getattr(self._app_ref, "_memory_snapshot_enabled", False)) if self._app_ref else False
        yield ToggleChip(
            "Memory Snapshots",
            value=mem_enabled,
            id="debug-memory-snapshots",
            on_change=self._handle_debug_toggle,
        )
        yield Static("tracemalloc snapshots at startup/shutdown", classes="field-desc")

        yield Static(
            "[bold {info}]Esc[/] close  (changes apply immediately)".format(info=p.info),
            classes="panel-footer",
        )

    def on_mount(self) -> None:
        focusable = self.query("Select, ToggleChip")
        if focusable:
            focusable.first().focus()

    def on_unmount(self) -> None:
        self._toggle_reaction.dispose()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.control.id == "debug-log-level" and event.value is not None:
            level = getattr(logging, str(event.value), logging.INFO)
            logging.getLogger("cc_dump").setLevel(level)

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self.remove()
            if self._app_ref:
                conv = self._app_ref._get_conv()
                if conv is not None:
                    conv.focus()

    def _handle_debug_toggle(self, chip: ToggleChip, value: bool) -> None:
        perf_enabled, mem_enabled = self._toggle_state.get()
        control_id = str(chip.id or "")
        if control_id == "debug-perf-logging":
            perf_enabled = bool(value)
        elif control_id == "debug-memory-snapshots":
            mem_enabled = bool(value)
        self._toggle_state.set((perf_enabled, mem_enabled))

    def _apply_toggle_state(self, toggle_state: tuple[bool, bool]) -> None:
        perf_enabled, mem_enabled = toggle_state
        cc_dump.io.perf_logging.set_enabled(perf_enabled)
        # [LAW:single-enforcer] Memory tracing is app-scoped and enforced only when an app context exists.
        if self._app_ref:
            self._app_ref._memory_snapshot_enabled = mem_enabled
            if mem_enabled and not tracemalloc.is_tracing():
                tracemalloc.start(25)
            if (not mem_enabled) and tracemalloc.is_tracing():
                tracemalloc.stop()


def create_debug_settings_panel(app_ref=None) -> DebugSettingsPanel:
    """Create a new DebugSettingsPanel instance."""
    return DebugSettingsPanel(app_ref=app_ref)
