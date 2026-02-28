"""Debug settings panel — runtime toggles for logging and diagnostics.

This module is RELOADABLE. Changes are live and session-only (no disk persistence).
"""

from __future__ import annotations

import logging
import tracemalloc

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Label, Select, Static

from cc_dump.tui.chip import ToggleChip

import cc_dump.core.palette
import cc_dump.io.perf_logging


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
        )
        yield Static("Stack traces when render stages exceed thresholds", classes="field-desc")

        # Memory snapshots
        mem_enabled = bool(getattr(self._app_ref, "_memory_snapshot_enabled", False)) if self._app_ref else False
        yield ToggleChip(
            "Memory Snapshots",
            value=mem_enabled,
            id="debug-memory-snapshots",
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

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.control.id == "debug-log-level" and event.value is not None:
            level = getattr(logging, str(event.value), logging.INFO)
            logging.getLogger("cc_dump").setLevel(level)

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self._apply_toggle_states()
            self.remove()
            if self._app_ref:
                conv = self._app_ref._get_conv()
                if conv is not None:
                    conv.focus()

    def _apply_toggle_states(self) -> None:
        """Read current toggle values and apply them."""
        try:
            perf_chip = self.query_one("#debug-perf-logging", ToggleChip)
            cc_dump.io.perf_logging.set_enabled(perf_chip.value)
        except Exception:
            pass

        try:
            mem_chip = self.query_one("#debug-memory-snapshots", ToggleChip)
            if self._app_ref:
                self._app_ref._memory_snapshot_enabled = mem_chip.value
                if mem_chip.value and not tracemalloc.is_tracing():
                    tracemalloc.start(25)
                elif not mem_chip.value and tracemalloc.is_tracing():
                    tracemalloc.stop()
        except Exception:
            pass


def create_debug_settings_panel(app_ref=None) -> DebugSettingsPanel:
    """Create a new DebugSettingsPanel instance."""
    return DebugSettingsPanel(app_ref=app_ref)
