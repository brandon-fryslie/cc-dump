"""Launch config panel — docked side panel for managing run configurations.

This module is RELOADABLE. When it reloads, any mounted panel is
removed during hot-reload (stateless, user can re-open with C).

// [LAW:one-source-of-truth] Launch schema is consumed from app.launch_config.
// [LAW:locality-or-seam] Panel owns all launch-config editing interactions.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Literal

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Input, Label, Static

import cc_dump.app.launch_config
import cc_dump.app.launcher_registry
import cc_dump.core.palette
from cc_dump.app.launch_config import SHELL_OPTIONS
from cc_dump.tui.chip import Chip, ToggleChip
from cc_dump.tui.cycle_selector import CycleSelector


@dataclass(frozen=True)
class BaseFieldDef:
    key: str
    label: str
    description: str
    kind: Literal["text", "select"]
    default: str
    options: tuple[str, ...] = ()


_SHELL_NONE_LABEL = "(none)"
_SHELL_DISPLAY_VALUES: tuple[str, ...] = (_SHELL_NONE_LABEL, "bash", "zsh")


def _shell_to_display(value: object) -> str:
    shell = str(value or "")
    return shell if shell in SHELL_OPTIONS and shell else _SHELL_NONE_LABEL


def _shell_from_display(value: str) -> str:
    return "" if value == _SHELL_NONE_LABEL else value


# [LAW:one-source-of-truth] Shared base config fields rendered in this order.
_BASE_FIELDS: tuple[BaseFieldDef, ...] = (
    BaseFieldDef(
        key="name",
        label="Name",
        kind="text",
        default=cc_dump.app.launcher_registry.DEFAULT_LAUNCHER_KEY,
        description="Config identifier",
    ),
    BaseFieldDef(
        key="launcher",
        label="Tool",
        kind="select",
        default=cc_dump.app.launcher_registry.DEFAULT_LAUNCHER_KEY,
        options=cc_dump.app.launcher_registry.launcher_keys(),
        description="Launcher profile",
    ),
    BaseFieldDef(
        key="command",
        label="Command",
        kind="text",
        default="",
        description="Executable command (blank uses tool default)",
    ),
    BaseFieldDef(
        key="model",
        label="Model",
        kind="text",
        default="",
        description="--model flag (empty = none)",
    ),
    BaseFieldDef(
        key="shell",
        label="Shell",
        kind="select",
        default=_SHELL_NONE_LABEL,
        options=_SHELL_DISPLAY_VALUES,
        description="Wrap command in shell -c 'source rc; ...'",
    ),
)


def _make_base_widget(field: BaseFieldDef, value: object) -> Input | CycleSelector:
    widget_id = "lc-field-{}".format(field.key)
    if field.kind == "text":
        return Input(value=str(value or ""), id=widget_id)

    selected = str(value or field.default)
    if selected not in field.options:
        selected = field.default if field.default in field.options else field.options[0]
    return CycleSelector(field.options, value=selected, id=widget_id)


class LaunchActionChip(Chip):
    """Focusable chip that posts a local action message on click/Enter/Space."""

    can_focus = True

    class Pressed(Message):
        def __init__(self, action_key: str) -> None:
            self.action_key = action_key
            super().__init__()

    def __init__(self, label: str, *, action_key: str, **kwargs) -> None:
        super().__init__(label, **kwargs)
        self._action_key = action_key

    def _emit(self) -> None:
        self.post_message(self.Pressed(self._action_key))

    async def on_click(self, event) -> None:
        event.stop()
        self._emit()

    def on_key(self, event) -> None:
        if event.key in ("enter", "space"):
            event.stop()
            event.prevent_default()
            self._emit()


class LaunchConfigPanel(VerticalScroll):
    """Side panel for managing launch configurations.

    Posts messages for app.py to handle: Saved, Cancelled, QuickLaunch, Activated.
    """

    DEFAULT_CSS = """
    LaunchConfigPanel {
        dock: right;
        width: 35%;
        min-width: 34;
        max-width: 55;
        border-left: solid $accent;
        padding: 0 1;
        height: 1fr;
        overflow-y: auto;
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
    LaunchConfigPanel .chip-row {
        margin-top: 1;
        height: auto;
    }
    LaunchConfigPanel .panel-footer {
        margin-top: 1;
        color: $text-muted;
    }
    LaunchConfigPanel LaunchActionChip {
        margin-right: 1;
    }
    LaunchConfigPanel ToggleChip {
        margin-top: 1;
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
    LaunchConfigPanel CycleSelector {
        width: 1fr;
    }
    LaunchConfigPanel #lc-tool-fields {
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
        """Posted when user launches selected config immediately."""

        def __init__(self, config, configs: list, active_name: str) -> None:
            self.config = config
            self.configs = configs
            self.active_name = active_name
            super().__init__()

    class Activated(Message):
        """Posted when user marks selected config as active."""

        def __init__(self, name: str, configs: list) -> None:
            self.name = name
            self.configs = configs
            super().__init__()

    def __init__(
        self,
        configs: list,
        active_config_name: str = cc_dump.app.launcher_registry.DEFAULT_LAUNCHER_KEY,
    ) -> None:
        super().__init__()
        # [LAW:one-source-of-truth] Local copy isolates edits until Saved.
        incoming = copy.deepcopy(configs)
        self._configs = incoming or cc_dump.app.launch_config.default_configs()
        self._active_name = active_config_name
        self._selected_idx = 0

    def compose(self) -> ComposeResult:
        p = cc_dump.core.palette.PALETTE
        yield Static("Launch Configs", classes="panel-title")

        with Horizontal(classes="field-row"):
            yield Label("Preset", classes="field-label")
            preset_options = tuple(config.name for config in self._configs) or (
                cc_dump.app.launcher_registry.DEFAULT_LAUNCHER_KEY,
            )
            yield CycleSelector(preset_options, value=preset_options[0], id="lc-config-selector")

        with Horizontal(classes="chip-row"):
            yield LaunchActionChip(" New ", action_key="new")
            yield LaunchActionChip(" Delete ", action_key="delete")
            yield LaunchActionChip(" Activate ", action_key="activate")
            yield LaunchActionChip(" Launch ", action_key="launch")

        yield Static("", id="lc-active", classes="field-desc")

        with Vertical(id="lc-form"):
            for field in _BASE_FIELDS:
                with Horizontal(classes="field-row"):
                    yield Label(field.label, classes="field-label")
                    value = field.default
                    if field.key == "shell":
                        value = _SHELL_NONE_LABEL
                    yield _make_base_widget(field, value)
                yield Static(field.description, classes="field-desc")

            yield Static("Tool Options", classes="section-title")
            yield Vertical(id="lc-tool-fields")

        yield Static(
            "[bold {info}]Tab[/] next  [bold {info}]Shift+Tab[/] prev\n"
            "[bold {info}]n[/] new  [bold {info}]d[/] delete  [bold {info}]a[/] activate  [bold {info}]l[/] launch\n"
            "[bold {info}]Enter[/] save  [bold {info}]Esc[/] close".format(info=p.info),
            classes="panel-footer",
        )

    def on_mount(self) -> None:
        target_name = self._active_name or (self._configs[0].name if self._configs else "")
        self._refresh_config_selector(preferred_name=target_name)
        self._populate_form(self._selected_config())
        self._refresh_active_display()

        focusable = self.query("Input, CycleSelector, ToggleChip")
        if focusable:
            focusable.first().focus()

    def _selected_config(self):
        if not self._configs:
            return None
        self._selected_idx = max(0, min(self._selected_idx, len(self._configs) - 1))
        return self._configs[self._selected_idx]

    def _refresh_active_display(self) -> None:
        try:
            widget = self.query_one("#lc-active", Static)
        except NoMatches:
            return
        widget.update("Active preset: {}".format(self._active_name or "(none)"))

    def _refresh_config_selector(self, preferred_name: str = "") -> None:
        if not self._configs:
            self._configs = cc_dump.app.launch_config.default_configs()

        names = [config.name for config in self._configs]
        selected_name = preferred_name or names[min(self._selected_idx, len(names) - 1)]
        if selected_name not in names:
            selected_name = names[0]

        self._selected_idx = names.index(selected_name)
        try:
            selector = self.query_one("#lc-config-selector", CycleSelector)
        except NoMatches:
            return
        selector.set_options(names, value=selected_name)

    def _read_launcher_value(self) -> str:
        try:
            launcher_widget = self.query_one("#lc-field-launcher", CycleSelector)
        except NoMatches:
            return cc_dump.app.launcher_registry.DEFAULT_LAUNCHER_KEY
        return cc_dump.app.launcher_registry.normalize_launcher_key(launcher_widget.value)

    def _read_shell_value(self) -> str:
        try:
            shell_widget = self.query_one("#lc-field-shell", CycleSelector)
        except NoMatches:
            return ""
        return _shell_from_display(shell_widget.value)

    def _collect_option_values(self, launcher: str) -> dict[str, str | bool]:
        values: dict[str, str | bool] = {}
        for option in cc_dump.app.launch_config.launcher_option_defs(launcher):
            widget_id = "#lc-option-{}".format(option.key)
            try:
                widget = self.query_one(widget_id)
            except NoMatches:
                values[option.key] = option.default
                continue
            if option.kind == "bool":
                values[option.key] = bool(widget.value)
            else:
                values[option.key] = str(widget.value)
        return values

    def _apply_form_to_selected(
        self,
        *,
        option_launcher: str | None = None,
        launcher_value: str | None = None,
    ) -> None:
        config = self._selected_config()
        if config is None:
            return

        name_value = config.name
        try:
            name_widget = self.query_one("#lc-field-name", Input)
            typed_name = name_widget.value.strip()
            name_value = typed_name or name_value
        except NoMatches:
            pass

        # Enforce unique names: auto-suffix if another config already has this name.
        taken = {c.name for i, c in enumerate(self._configs) if i != self._selected_idx}
        if name_value in taken:
            name_value = self._next_config_name(name_value)

        try:
            command_widget = self.query_one("#lc-field-command", Input)
            command_value = command_widget.value
        except NoMatches:
            command_value = config.command

        try:
            model_widget = self.query_one("#lc-field-model", Input)
            model_value = model_widget.value
        except NoMatches:
            model_value = config.model

        launcher = launcher_value or self._read_launcher_value()
        options_launcher = option_launcher or launcher

        merged_options = cc_dump.app.launch_config.normalize_options(config.options)
        merged_options.update(self._collect_option_values(options_launcher))

        config.name = name_value
        config.launcher = cc_dump.app.launcher_registry.normalize_launcher_key(launcher)
        config.command = command_value
        config.model = model_value
        config.shell = self._read_shell_value()
        config.options = merged_options

    def _rebuild_tool_option_fields(self, config) -> None:
        try:
            container = self.query_one("#lc-tool-fields", Vertical)
        except NoMatches:
            return

        for child in tuple(container.children):
            child.remove()

        option_values = cc_dump.app.launch_config.normalize_options(config.options)
        for option in cc_dump.app.launch_config.launcher_option_defs(config.launcher):
            value = option_values.get(option.key, option.default)
            if option.kind == "bool":
                container.mount(
                    ToggleChip(
                        option.label,
                        value=bool(value),
                        id="lc-option-{}".format(option.key),
                    )
                )
            else:
                row = Horizontal(
                    Label(option.label, classes="field-label"),
                    Input(
                        value=str(value or ""),
                        id="lc-option-{}".format(option.key),
                    ),
                    classes="field-row",
                )
                container.mount(row)
            container.mount(Static(option.description, classes="field-desc"))

    def _populate_form(self, config) -> None:
        if config is None:
            return

        for field in _BASE_FIELDS:
            widget_id = "#lc-field-{}".format(field.key)
            try:
                widget = self.query_one(widget_id)
            except NoMatches:
                continue

            if field.key == "name":
                widget.value = config.name
            elif field.key == "launcher":
                widget.value = config.launcher
            elif field.key == "command":
                widget.value = config.command
            elif field.key == "model":
                widget.value = config.model
            elif field.key == "shell":
                widget.value = _shell_to_display(config.shell)

        self._rebuild_tool_option_fields(config)

    def _switch_to_config(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._configs):
            return
        self._apply_form_to_selected()
        self._selected_idx = idx
        self._populate_form(self._configs[idx])

    def _next_config_name(self, base_name: str) -> str:
        taken = {config.name for config in self._configs}
        candidate = base_name
        suffix = 2
        while candidate in taken:
            candidate = "{}-{}".format(base_name, suffix)
            suffix += 1
        return candidate

    def create_new_config(self) -> None:
        self._apply_form_to_selected()
        selected = self._selected_config()
        base_launcher = selected.launcher if selected is not None else cc_dump.app.launcher_registry.DEFAULT_LAUNCHER_KEY
        new_config = cc_dump.app.launch_config.default_config_for_launcher(base_launcher)
        new_config.name = self._next_config_name(base_launcher)
        self._configs.append(new_config)
        self._selected_idx = len(self._configs) - 1
        self._refresh_config_selector(preferred_name=new_config.name)
        self._populate_form(new_config)

    def delete_selected_config(self) -> None:
        if len(self._configs) <= 1:
            self.notify("Cannot delete last config", severity="warning")
            return

        selected = self._selected_config()
        removed_name = selected.name if selected is not None else ""
        self._configs.pop(self._selected_idx)

        if removed_name == self._active_name:
            self._active_name = self._configs[0].name

        self._selected_idx = min(self._selected_idx, len(self._configs) - 1)
        current = self._selected_config()
        preferred = current.name if current is not None else ""
        self._refresh_config_selector(preferred_name=preferred)
        self._populate_form(current)
        self._refresh_active_display()

    def activate_selected_config(self) -> None:
        self._apply_form_to_selected()
        selected = self._selected_config()
        if selected is None:
            return
        self._active_name = selected.name
        self._refresh_config_selector(preferred_name=selected.name)
        self._refresh_active_display()
        self.post_message(self.Activated(self._active_name, self._configs))

    def quick_launch_selected_config(self) -> None:
        self._apply_form_to_selected()
        selected = self._selected_config()
        if selected is None:
            return
        self.post_message(self.QuickLaunch(selected, self._configs, self._active_name))

    def _do_save(self) -> None:
        self._apply_form_to_selected()
        selected = self._selected_config()
        preferred = selected.name if selected is not None else ""
        self._refresh_config_selector(preferred_name=preferred)
        self.post_message(self.Saved(self._configs, self._active_name))

    def on_launch_action_chip_pressed(self, event: LaunchActionChip.Pressed) -> None:
        event.stop()
        action = event.action_key
        if action == "new":
            self.create_new_config()
        elif action == "delete":
            self.delete_selected_config()
        elif action == "activate":
            self.activate_selected_config()
        elif action == "launch":
            self.quick_launch_selected_config()

    def on_cycle_selector_changed(self, event: CycleSelector.Changed) -> None:
        event.stop()

        control_id = event.cycle_selector.id or ""
        if control_id == "lc-config-selector":
            names = [config.name for config in self._configs]
            if event.value in names:
                idx = names.index(event.value)
                if idx != self._selected_idx:
                    self._switch_to_config(idx)
            return

        if control_id == "lc-field-launcher":
            selected = self._selected_config()
            if selected is None:
                return
            old_launcher = selected.launcher
            new_launcher = cc_dump.app.launcher_registry.normalize_launcher_key(event.value)
            self._apply_form_to_selected(
                option_launcher=old_launcher,
                launcher_value=new_launcher,
            )
            self._rebuild_tool_option_fields(selected)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._do_save()

    def on_key(self, event) -> None:
        key = event.key

        if key == "escape":
            event.stop()
            event.prevent_default()
            self.post_message(self.Cancelled())
            return

        if key == "enter" and not isinstance(self.screen.focused, Input):
            event.stop()
            event.prevent_default()
            self._do_save()
            return

        if isinstance(self.screen.focused, Input):
            return

        if key == "n":
            event.stop()
            event.prevent_default()
            self.create_new_config()
            return

        if key == "d":
            event.stop()
            event.prevent_default()
            self.delete_selected_config()
            return

        if key == "a":
            event.stop()
            event.prevent_default()
            self.activate_selected_config()
            return

        if key == "l":
            event.stop()
            event.prevent_default()
            self.quick_launch_selected_config()
            return

    def get_state(self) -> dict:
        return {}

    def restore_state(self, state: dict) -> None:
        pass


def create_launch_config_panel(
    configs: list,
    active_config_name: str = cc_dump.app.launcher_registry.DEFAULT_LAUNCHER_KEY,
) -> LaunchConfigPanel:
    """Create a new LaunchConfigPanel instance."""
    return LaunchConfigPanel(configs=configs, active_config_name=active_config_name)
