"""Launch config panel — docked side panel for managing run configurations.

This module is RELOADABLE. When it reloads, any mounted panel is
removed during hot-reload (stateless, user can re-open with C).

// [LAW:one-type-per-behavior] Reuses FieldDef from settings_panel.
// [LAW:locality-or-seam] Panel handles its own keys and messages — app.py
//   just listens for Saved/Cancelled/QuickLaunch/Activated.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Input, Label, OptionList, Select, Static, Switch

import cc_dump.palette
from cc_dump.launch_config import SHELL_OPTIONS
from cc_dump.tui.settings_panel import FieldDef


# [LAW:one-source-of-truth] Field definitions for a LaunchConfig.
CONFIG_FIELDS: list[FieldDef] = [
    FieldDef(
        key="claude_command",
        label="Command",
        kind="text",
        default="claude",
        description="Claude binary (e.g. claude, clod)",
    ),
    FieldDef(
        key="name",
        label="Name",
        kind="text",
        default="default",
        description="Config identifier",
    ),
    FieldDef(
        key="model",
        label="Model",
        kind="text",
        default="",
        description="--model flag (empty = none)",
    ),
    FieldDef(
        key="auto_resume",
        label="Auto-Resume",
        kind="bool",
        default=True,
        description="Pass --resume <session_id>",
    ),
    FieldDef(
        key="shell",
        label="Shell",
        kind="select",
        description="Wrap command in shell -c 'source rc; ...'",
        options=SHELL_OPTIONS,
        default="",
    ),
    FieldDef(
        key="extra_flags",
        label="Extra Flags",
        kind="text",
        default="",
        description="Appended to command",
    ),
]


def _make_widget(field: FieldDef, value: object) -> Input | Switch | Select:
    """Create the appropriate Textual widget for a FieldDef."""
    widget_id = "lc-field-{}".format(field.key)
    if field.kind == "text":
        return Input(value=str(value), id=widget_id)
    elif field.kind == "bool":
        return Switch(value=bool(value), id=widget_id)
    else:  # select
        s = str(value) if value else field.default
        options = [(opt or "(none)", opt) for opt in field.options]
        return Select(options, value=s, allow_blank=False, id=widget_id)


class LaunchConfigPanel(VerticalScroll):
    """Side panel for managing launch configurations.

    Posts messages for app.py to handle: Saved, Cancelled, QuickLaunch, Activated.
    """

    DEFAULT_CSS = """
    LaunchConfigPanel {
        dock: right;
        width: 35%;
        min-width: 30;
        max-width: 50;
        border-left: solid $accent;
        padding: 0 1;
        height: 1fr;
    }
    LaunchConfigPanel .panel-title {
        text-style: bold;
        margin-bottom: 0;
    }
    LaunchConfigPanel .section-title {
        text-style: bold;
        margin-top: 1;
    }
    LaunchConfigPanel .field-row {
        height: auto;
        width: 100%;
        margin-top: 1;
    }
    LaunchConfigPanel .field-label {
        width: 1fr;
        text-style: bold;
        content-align-vertical: middle;
    }
    LaunchConfigPanel .field-desc {
        color: $text-muted;
        text-style: italic;
        padding-left: 2;
        margin-bottom: 0;
    }
    LaunchConfigPanel .panel-footer {
        margin-top: 1;
        color: $text-muted;
    }
    LaunchConfigPanel OptionList {
        height: auto;
        max-height: 10;
    }
    LaunchConfigPanel Switch {
        width: auto;
        height: auto;
        border: none;
        padding: 0 1;
    }
    LaunchConfigPanel Input {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0;
    }
    LaunchConfigPanel Input:focus {
        border: none;
    }
    LaunchConfigPanel Select {
        width: 1fr;
    }
    LaunchConfigPanel #lc-edit-section {
        height: auto;
    }
    """

    class Saved(Message):
        """Posted when user saves configs (Enter)."""

        def __init__(self, configs: list, active_name: str) -> None:
            self.configs = configs
            self.active_name = active_name
            super().__init__()

    class Cancelled(Message):
        """Posted when user cancels (Escape)."""

    class QuickLaunch(Message):
        """Posted when user quick-launches a config (1-9)."""

        def __init__(self, config, configs: list, active_name: str) -> None:
            self.config = config
            self.configs = configs
            self.active_name = active_name
            super().__init__()

    class Activated(Message):
        """Posted when user activates a config (a)."""

        def __init__(self, name: str, configs: list) -> None:
            self.name = name
            self.configs = configs
            super().__init__()

    def __init__(
        self,
        configs: list,
        active_config_name: str = "default",
    ) -> None:
        super().__init__()
        # Deep-copy configs so edits don't mutate originals until save
        import copy
        self._configs = copy.deepcopy(configs)
        self._active_name = active_config_name
        self._selected_idx = 0

    def compose(self) -> ComposeResult:
        p = cc_dump.palette.PALETTE
        yield Static("Launch Configs", classes="panel-title")

        # Config list
        option_list = OptionList(id="lc-config-list")
        yield option_list

        # Edit section
        with Vertical(id="lc-edit-section"):
            yield Static("", id="lc-edit-title", classes="section-title")
            for field in CONFIG_FIELDS:
                with Horizontal(classes="field-row"):
                    yield Label(field.label, classes="field-label")
                    yield _make_widget(field, field.default)
                yield Static(field.description, classes="field-desc")

        yield Static(
            "[bold {info}]1-9[/] launch  [bold {info}]a[/] activate  [bold {info}]n[/] new\n"
            "[bold {info}]d[/] delete  [bold {info}]enter[/] save  [bold {info}]esc[/] close".format(
                info=p.info
            ),
            classes="panel-footer",
        )

    def on_mount(self) -> None:
        """Populate the config list and form after mount, then focus first widget."""
        self._refresh_config_list()
        self._populate_form(self._configs[0] if self._configs else None)
        # Focus the OptionList so keyboard commands (a/n/d/1-9) work immediately
        focusable = self.query("OptionList")
        if focusable:
            focusable.first().focus()

    def _refresh_config_list(self) -> None:
        """Rebuild OptionList options from config list."""
        try:
            option_list = self.query_one("#lc-config-list", OptionList)
        except NoMatches:
            return
        option_list.clear_options()
        for i, config in enumerate(self._configs):
            marker = "[*]" if config.name == self._active_name else "   "
            option_list.add_option("{:d}. {} {}".format(i + 1, marker, config.name))
        if self._selected_idx < option_list.option_count:
            option_list.highlighted = self._selected_idx

    def _populate_form(self, config) -> None:
        """Set widget values from a config object."""
        if config is None:
            return
        try:
            title = self.query_one("#lc-edit-title", Static)
        except NoMatches:
            return
        title.update("-- Edit: {} --".format(config.name))
        for field in CONFIG_FIELDS:
            value = getattr(config, field.key, field.default)
            widget_id = "#lc-field-{}".format(field.key)
            try:
                widget = self.query_one(widget_id)
            except NoMatches:
                continue
            if field.kind == "text":
                widget.value = str(value)
            elif field.kind == "bool":
                widget.value = bool(value)
            else:  # select
                widget.value = str(value) if value else field.default

    def _collect_form(self) -> dict:
        """Read widget values into a dict."""
        result = {}
        for field in CONFIG_FIELDS:
            widget_id = "#lc-field-{}".format(field.key)
            try:
                widget = self.query_one(widget_id)
            except NoMatches:
                result[field.key] = field.default
                continue
            result[field.key] = widget.value
        return result

    def _apply_form_to_selected(self) -> None:
        """Write form values back to the selected config."""
        if not self._configs:
            return
        config = self._configs[self._selected_idx]
        values = self._collect_form()
        for key, value in values.items():
            setattr(config, key, value)

    def _switch_to_config(self, idx: int) -> None:
        """Save current form, switch to new config, populate form."""
        self._apply_form_to_selected()
        self._selected_idx = idx
        self._populate_form(self._configs[idx])

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """When user navigates config list, switch the edit form."""
        event.stop()
        new_idx = event.option_index
        if new_idx != self._selected_idx and new_idx < len(self._configs):
            self._switch_to_config(new_idx)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in any Input triggers save."""
        event.stop()
        self._do_save()

    def _do_save(self) -> None:
        """Apply form edits and post Saved message."""
        self._apply_form_to_selected()
        self.post_message(self.Saved(self._configs, self._active_name))

    def _is_option_list_focused(self) -> bool:
        """Check if the OptionList currently has focus."""
        try:
            option_list = self.query_one("#lc-config-list", OptionList)
            return option_list.has_focus
        except NoMatches:
            return False

    def on_key(self, event) -> None:
        """Handle panel-level keys.

        Single-letter commands (a/n/d/1-9) only fire when OptionList is focused,
        preventing conflicts with typing in Input widgets.
        """
        key = event.key

        # Escape always cancels
        if key == "escape":
            event.stop()
            event.prevent_default()
            self.post_message(self.Cancelled())
            return

        # Enter always saves (unless from Input — handled by on_input_submitted)
        if key == "enter" and not isinstance(self.screen.focused, Input):
            event.stop()
            event.prevent_default()
            self._do_save()
            return

        # Commands only active when OptionList focused (not typing in Input)
        if not self._is_option_list_focused():
            return

        configs = self._configs

        # Quick-launch by number (1-9)
        if key in "123456789":
            num = int(key) - 1
            if num < len(configs):
                event.stop()
                event.prevent_default()
                self._apply_form_to_selected()
                self.post_message(
                    self.QuickLaunch(
                        configs[num], self._configs, self._active_name
                    )
                )
            return

        # Activate selected config
        if key == "a":
            event.stop()
            event.prevent_default()
            self._apply_form_to_selected()
            self._active_name = configs[self._selected_idx].name
            self._refresh_config_list()
            self.post_message(self.Activated(self._active_name, self._configs))
            return

        # New config
        if key == "n":
            event.stop()
            event.prevent_default()
            self._apply_form_to_selected()
            import cc_dump.launch_config
            new_config = cc_dump.launch_config.LaunchConfig(
                name="config-{}".format(len(configs) + 1)
            )
            configs.append(new_config)
            self._selected_idx = len(configs) - 1
            self._refresh_config_list()
            self._populate_form(new_config)
            return

        # Delete selected (prevent deleting last)
        if key == "d":
            event.stop()
            event.prevent_default()
            if len(configs) <= 1:
                self.notify("Cannot delete last config", severity="warning")
                return
            configs.pop(self._selected_idx)
            self._selected_idx = min(self._selected_idx, len(configs) - 1)
            self._refresh_config_list()
            self._populate_form(configs[self._selected_idx])
            return

    def get_state(self) -> dict:
        return {}

    def restore_state(self, state: dict) -> None:
        pass


def create_launch_config_panel(
    configs: list, active_config_name: str = "default"
) -> LaunchConfigPanel:
    """Create a new LaunchConfigPanel instance."""
    return LaunchConfigPanel(configs=configs, active_config_name=active_config_name)
