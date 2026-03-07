"""Launch config panel — docked side panel for managing run configurations.

This module is RELOADABLE. When it reloads, any mounted panel is
removed during hot-reload (stateless, user can re-open with C).

// [LAW:one-source-of-truth] Launch schema is consumed from app.launch_config.
// [LAW:locality-or-seam] Panel owns all launch-config editing interactions.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

from snarfx import Observable, reaction
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Input, Label, Select, Static

import cc_dump.app.launch_config
import cc_dump.app.launcher_registry
import cc_dump.core.palette
from cc_dump.app.launch_config import SHELL_OPTIONS
from cc_dump.tui.chip import Chip, ToggleChip


@dataclass(frozen=True)
class BaseFieldDef:
    key: str
    label: str
    description: str
    kind: Literal["text", "select"]
    default: str
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class LaunchConfigPanelViewState:
    """Reactive projection trigger for selector/active/form rendering."""

    active_name: str
    selected_idx: int
    revision: int


@dataclass(frozen=True)
class ToolOptionValueViewState:
    key: str
    kind: Literal["text", "bool"]
    text_value: str = ""
    bool_value: bool = False


@dataclass(frozen=True)
class ToolOptionValuesViewState:
    """Reactive projection for stable tool option values."""

    values: tuple[ToolOptionValueViewState, ...]


_SHELL_NONE_LABEL = "(none)"
_SHELL_DISPLAY_VALUES: tuple[str, ...] = (
    _SHELL_NONE_LABEL,
    *tuple(shell for shell in SHELL_OPTIONS if shell),
)


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


def _tool_option_defs_by_launcher() -> dict[str, tuple[cc_dump.app.launch_config.LaunchOptionDef, ...]]:
    return {
        launcher: cc_dump.app.launch_config.launcher_option_defs(launcher)
        for launcher in cc_dump.app.launcher_registry.launcher_keys()
    }


_TOOL_OPTION_DEFS_BY_LAUNCHER = _tool_option_defs_by_launcher()


def _all_tool_option_defs() -> tuple[cc_dump.app.launch_config.LaunchOptionDef, ...]:
    defs_by_key: dict[str, cc_dump.app.launch_config.LaunchOptionDef] = {}
    ordered_keys: list[str] = []
    for option_defs in _TOOL_OPTION_DEFS_BY_LAUNCHER.values():
        for option in option_defs:
            if option.key in defs_by_key:
                continue
            defs_by_key[option.key] = option
            ordered_keys.append(option.key)
    return tuple(defs_by_key[key] for key in ordered_keys)


_TOOL_OPTION_DEFS = _all_tool_option_defs()


def _common_tool_option_defs() -> tuple[cc_dump.app.launch_config.LaunchOptionDef, ...]:
    launcher_keys = tuple(_TOOL_OPTION_DEFS_BY_LAUNCHER)
    if not launcher_keys:
        return ()
    common_keys = set(option.key for option in _TOOL_OPTION_DEFS_BY_LAUNCHER[launcher_keys[0]])
    for launcher in launcher_keys[1:]:
        common_keys &= {
            option.key for option in _TOOL_OPTION_DEFS_BY_LAUNCHER[launcher]
        }
    return tuple(option for option in _TOOL_OPTION_DEFS if option.key in common_keys)


_COMMON_TOOL_OPTION_DEFS = _common_tool_option_defs()


def _tool_specific_option_defs_by_launcher() -> dict[str, tuple[cc_dump.app.launch_config.LaunchOptionDef, ...]]:
    common_keys = {option.key for option in _COMMON_TOOL_OPTION_DEFS}
    return {
        launcher: tuple(
            option for option in option_defs if option.key not in common_keys
        )
        for launcher, option_defs in _TOOL_OPTION_DEFS_BY_LAUNCHER.items()
    }


_TOOL_SPECIFIC_OPTION_DEFS_BY_LAUNCHER = _tool_specific_option_defs_by_launcher()


def _empty_tool_option_values_state() -> ToolOptionValuesViewState:
    return ToolOptionValuesViewState(
        values=tuple(
            ToolOptionValueViewState(
                key=option.key,
                kind=option.kind,
                text_value=str(option.default or ""),
                bool_value=bool(option.default),
            )
            for option in _TOOL_OPTION_DEFS
        )
    )


def _compose_tool_option_widgets(
    option_defs: tuple[cc_dump.app.launch_config.LaunchOptionDef, ...],
) -> ComposeResult:
    for option in option_defs:
        if option.kind == "bool":
            with Horizontal(
                classes="field-row",
                id="lc-option-row-{}".format(option.key),
            ):
                yield ToggleChip(
                    option.label,
                    value=bool(option.default),
                    id="lc-option-{}".format(option.key),
                )
        else:
            with Horizontal(
                classes="field-row",
                id="lc-option-row-{}".format(option.key),
            ):
                yield Label(option.label, classes="field-label")
                yield Input(
                    value=str(option.default or ""),
                    id="lc-option-{}".format(option.key),
                )
        yield Static(
            option.description,
            classes="field-desc",
            id="lc-option-desc-{}".format(option.key),
        )


def _compose_tool_option_sets() -> ComposeResult:
    if _COMMON_TOOL_OPTION_DEFS:
        yield Static("Common", classes="field-desc", id="lc-toolset-common-title")
        with Vertical(id="lc-toolset-common"):
            yield from _compose_tool_option_widgets(_COMMON_TOOL_OPTION_DEFS)
    for launcher, option_defs in _TOOL_SPECIFIC_OPTION_DEFS_BY_LAUNCHER.items():
        if not option_defs:
            continue
        title = cc_dump.app.launcher_registry.get_launcher_spec(launcher).display_name
        yield Static(
            title,
            classes="field-desc",
            id="lc-toolset-title-{}".format(launcher),
        )
        with Vertical(id="lc-toolset-{}".format(launcher)):
            yield from _compose_tool_option_widgets(option_defs)

def _select_widget(options: Sequence[str], selected: str, widget_id: str) -> Select[str]:
    return Select[str](
        [(option, option) for option in options],
        value=selected,
        allow_blank=False,
        compact=True,
        type_to_search=False,
        id=widget_id,
    )


def _make_base_widget(field: BaseFieldDef, value: object) -> Input | Select[str]:
    widget_id = "lc-field-{}".format(field.key)
    if field.kind == "text":
        return Input(value=str(value or ""), id=widget_id)

    selected = str(value or field.default)
    if selected not in field.options:
        selected = field.default if field.default in field.options else field.options[0]
    return _select_widget(field.options, selected, widget_id)


def _select_values(selector: Select[str]) -> tuple[str, ...]:
    return tuple(
        str(value)
        for _prompt, value in getattr(selector, "_options", [])
        if value is not selector.BLANK
    )


def _base_field_display_value(field: BaseFieldDef, config) -> str:
    if field.key == "name":
        return config.name
    if field.key == "launcher":
        return config.launcher
    if field.key == "command":
        return config.command
    if field.key == "model":
        return config.model
    if field.key == "shell":
        return _shell_to_display(config.shell)
    return str(getattr(config, field.key, "") or "")


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

    def on_click(self, event) -> None:
        event.stop()
        self._emit()

    def on_key(self, event) -> None:
        if event.key in ("enter", "space"):
            event.stop()
            event.prevent_default()
            self._emit()


def _action_chip(label: str, action_key: str) -> LaunchActionChip:
    return LaunchActionChip(
        label,
        action_key=action_key,
        id="lc-action-{}".format(action_key),
    )


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
        width: 20;
        height: 1;
        border: none;
        padding: 0;
        background: $panel-lighten-2;
        color: $text;
    }
    LaunchConfigPanel Input:focus {
        border: none;
        background: $surface-lighten-3;
        color: $accent;
    }
    LaunchConfigPanel Select {
        width: 20;
        height: auto;
    }
    LaunchConfigPanel Select > SelectCurrent {
        height: 1;
        min-height: 1;
        border: none !important;
        padding: 0 1;
        background: $panel-lighten-2;
        color: $text;
        text-style: bold;
        content-align: center middle;
    }
    LaunchConfigPanel Select:focus > SelectCurrent {
        border: none !important;
        background: $surface-lighten-3;
        color: $accent;
    }
    LaunchConfigPanel Select.-expanded > SelectCurrent {
        border: none !important;
        background: $accent;
        color: $text;
    }
    LaunchConfigPanel Select > SelectOverlay {
        border: none !important;
        padding: 0;
        background: $surface-darken-1;
        max-height: 8;
    }
    LaunchConfigPanel Select > SelectOverlay > .option-list--option {
        padding: 0 1;
        content-align: center middle;
    }
    LaunchConfigPanel Select > SelectOverlay > .option-list--option-highlighted {
        background: $accent;
        color: $text;
        text-style: bold;
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
        self._view_revision = 0
        self._panel_state: Observable[LaunchConfigPanelViewState] = Observable(
            LaunchConfigPanelViewState(
                active_name=self._active_name,
                selected_idx=self._selected_idx,
                revision=self._view_revision,
            )
        )
        self._tool_option_values_state: Observable[ToolOptionValuesViewState] = Observable(
            _empty_tool_option_values_state()
        )
        self._active_tool_option_set: Observable[str] = Observable(
            cc_dump.app.launcher_registry.DEFAULT_LAUNCHER_KEY
        )
        self._select_sync_depth = 0
        # [LAW:single-enforcer] One reactive projection owns selector/active/form sync.
        self._panel_reaction = reaction(
            lambda: self._panel_state.get(),
            self._apply_panel_state,
            fire_immediately=False,
        )
        self._tool_option_values_reaction = reaction(
            lambda: self._tool_option_values_state.get(),
            self._apply_tool_option_values_state,
            fire_immediately=False,
        )
        self._active_tool_option_set_reaction = reaction(
            lambda: self._active_tool_option_set.get(),
            self._apply_active_tool_option_set,
            fire_immediately=False,
        )

    def compose(self) -> ComposeResult:
        p = cc_dump.core.palette.PALETTE
        yield Static("Launch Configs", classes="panel-title")

        with Horizontal(classes="field-row"):
            yield Label("Preset", classes="field-label")
            preset_options = tuple(config.name for config in self._configs) or (
                cc_dump.app.launcher_registry.DEFAULT_LAUNCHER_KEY,
            )
            yield _select_widget(preset_options, preset_options[0], "lc-config-selector")

        with Horizontal(classes="chip-row"):
            yield _action_chip(" New ", "new")
            yield _action_chip(" Delete ", "delete")
            yield _action_chip(" Activate ", "activate")
            yield _action_chip(" Launch ", "launch")

        with Horizontal(classes="chip-row"):
            yield _action_chip(" Save ", "save")
            yield _action_chip(" Close ", "close")

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
            with Vertical(id="lc-tool-fields"):
                yield from _compose_tool_option_sets()

        yield Static(
            "[bold {info}]Tab[/] next  [bold {info}]Shift+Tab[/] prev\n"
            "[bold {info}]Enter[/]/[bold {info}]Space[/] activate focused control  [bold {info}]Esc[/] close".format(
                info=p.info
            ),
            classes="panel-footer",
        )

    def on_mount(self) -> None:
        if not self.display:
            return
        self._apply_panel_state(self._panel_state.get())
        self.focus_default_control()

    def on_unmount(self) -> None:
        self._panel_reaction.dispose()
        self._tool_option_values_reaction.dispose()
        self._active_tool_option_set_reaction.dispose()

    def _emit_panel_state(self) -> None:
        """Trigger reactive selector/active/form projection after model mutation."""
        self._view_revision += 1
        self._panel_state.set(
            LaunchConfigPanelViewState(
                active_name=self._active_name,
                selected_idx=self._selected_idx,
                revision=self._view_revision,
            )
        )

    @contextmanager
    def _suspend_select_events(self) -> Iterator[None]:
        # [LAW:single-enforcer] Programmatic Select mutations are silenced at one boundary.
        self._select_sync_depth += 1
        try:
            yield
        finally:
            self._select_sync_depth -= 1

    def _sync_select_widget(
        self,
        selector: Select[str],
        *,
        options: tuple[str, ...] | None = None,
        value: str,
    ) -> None:
        with self._suspend_select_events():
            if options is not None and _select_values(selector) != options:
                selector.set_options([(option, option) for option in options])
            if selector.value != value:
                selector.value = value

    def _sync_active_label(self) -> None:
        try:
            active_widget = self.query_one("#lc-active", Static)
        except NoMatches:
            return
        active_widget.update("Active preset: {}".format(self._active_name or "(none)"))

    def _sync_preset_selector(self, names: tuple[str, ...], selected_name: str) -> None:
        try:
            selector = self.query_one("#lc-config-selector", Select)
        except NoMatches:
            return
        self._sync_select_widget(selector, options=names, value=selected_name)

    def _sync_base_field_widget(self, field: BaseFieldDef, value: str) -> None:
        widget_id = "#lc-field-{}".format(field.key)
        try:
            widget = self.query_one(widget_id)
        except NoMatches:
            return
        if field.kind == "select":
            self._sync_select_widget(widget, value=value)
            return
        if widget.value != value:
            widget.value = value

    def _apply_panel_state(self, panel_state: LaunchConfigPanelViewState) -> None:
        # [LAW:dataflow-not-control-flow] exception: widget mutations require mounted children.
        if not self.is_attached:
            return
        if not self._configs:
            self._configs = cc_dump.app.launch_config.default_configs()

        names = [config.name for config in self._configs]
        # [LAW:one-source-of-truth] _selected_idx/_active_name are canonical panel selection state.
        selected_idx = max(0, min(panel_state.selected_idx, len(names) - 1))
        self._selected_idx = selected_idx
        self._active_name = (
            panel_state.active_name
            if panel_state.active_name in names
            else names[0]
        )
        selected_name = names[self._selected_idx]
        self._sync_preset_selector(tuple(names), selected_name)
        self._sync_active_label()
        self._populate_form(self._selected_config())

    def _build_tool_option_values_state(self, config) -> ToolOptionValuesViewState:
        if config is None:
            return _empty_tool_option_values_state()
        option_values = cc_dump.app.launch_config.normalize_options(config.options)
        return ToolOptionValuesViewState(
            values=tuple(
                ToolOptionValueViewState(
                    key=option.key,
                    kind=option.kind,
                    text_value=str(option_values.get(option.key, "") or ""),
                    bool_value=bool(option_values.get(option.key, False)),
                )
                for option in _TOOL_OPTION_DEFS
            )
        )

    def _apply_tool_option_values_state(self, state: ToolOptionValuesViewState) -> None:
        # [LAW:dataflow-not-control-flow] Stable tool option widgets always receive value hydration.
        for field_state in state.values:
            widget_id = "#lc-option-{}".format(field_state.key)
            try:
                widget = self.query_one(widget_id)
            except NoMatches:
                continue
            if field_state.kind == "bool":
                widget.value = field_state.bool_value
            else:
                widget.value = field_state.text_value

    def _apply_active_tool_option_set(self, active_launcher: str) -> None:
        try:
            common_set = self.query_one("#lc-toolset-common")
            common_title = self.query_one("#lc-toolset-common-title", Static)
            common_visible = bool(_COMMON_TOOL_OPTION_DEFS)
            common_set.display = common_visible
            common_title.display = common_visible
        except NoMatches:
            pass
        for launcher, option_defs in _TOOL_SPECIFIC_OPTION_DEFS_BY_LAUNCHER.items():
            visible = launcher == active_launcher and bool(option_defs)
            try:
                title = self.query_one("#lc-toolset-title-{}".format(launcher), Static)
                toolset = self.query_one("#lc-toolset-{}".format(launcher))
            except NoMatches:
                continue
            title.display = visible
            toolset.display = visible

    def reset_configs(self, configs: list, active_config_name: str) -> None:
        """Reset panel state from persisted launch configs."""
        incoming = copy.deepcopy(configs)
        self._configs = incoming or cc_dump.app.launch_config.default_configs()
        self._active_name = active_config_name
        names = [config.name for config in self._configs]
        target_name = self._active_name if self._active_name in names else (names[0] if names else "")
        self._selected_idx = names.index(target_name) if target_name in names else 0
        self._emit_panel_state()

    def focus_default_control(self) -> None:
        focusable = self.query("Input, Select, ToggleChip")
        if focusable:
            focusable.first().focus()

    def _selected_config(self):
        if not self._configs:
            return None
        self._selected_idx = max(0, min(self._selected_idx, len(self._configs) - 1))
        return self._configs[self._selected_idx]

    def _read_launcher_value(self) -> str:
        try:
            launcher_widget = self.query_one("#lc-field-launcher", Select)
        except NoMatches:
            return cc_dump.app.launcher_registry.DEFAULT_LAUNCHER_KEY
        return cc_dump.app.launcher_registry.normalize_launcher_key(launcher_widget.value)

    def _read_shell_value(self) -> str:
        try:
            shell_widget = self.query_one("#lc-field-shell", Select)
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

    def _read_input_with_fallback(self, widget_id: str, fallback: str) -> str:
        """Read input value or return fallback when widget is absent."""
        try:
            widget = self.query_one(widget_id, Input)
        except NoMatches:
            return fallback
        return widget.value

    def _resolve_name_field(self, fallback_name: str) -> tuple[str, Input | None]:
        """Resolve current config name from form field, falling back to existing name."""
        try:
            name_widget = self.query_one("#lc-field-name", Input)
        except NoMatches:
            return fallback_name, None
        typed_name = name_widget.value.strip()
        return typed_name or fallback_name, name_widget

    def _dedupe_name_for_selected(self, name_value: str, name_widget: Input | None) -> str:
        """Ensure selected config name is unique across all other configs."""
        taken = {c.name for i, c in enumerate(self._configs) if i != self._selected_idx}
        if name_value not in taken:
            return name_value
        deduped_name = self._next_config_name(name_value)
        if deduped_name != name_value and name_widget is not None:
            name_widget.value = deduped_name
        return deduped_name

    def _resolve_launchers(
        self,
        *,
        option_launcher: str | None,
        launcher_value: str | None,
    ) -> tuple[str, str]:
        """Resolve launcher values used for config + option widgets."""
        launcher = launcher_value or self._read_launcher_value()
        options_launcher = option_launcher or launcher
        return launcher, options_launcher

    def _resolve_merged_options(self, config, options_launcher: str) -> dict[str, str | bool]:
        """Merge current persisted options with values from option widgets."""
        merged_options = cc_dump.app.launch_config.normalize_options(config.options)
        merged_options.update(self._collect_option_values(options_launcher))
        return merged_options

    def _apply_form_to_selected(
        self,
        *,
        option_launcher: str | None = None,
        launcher_value: str | None = None,
    ) -> None:
        config = self._selected_config()
        if config is None:
            return

        name_value, name_widget = self._resolve_name_field(config.name)
        name_value = self._dedupe_name_for_selected(name_value, name_widget)
        command_value = self._read_input_with_fallback("#lc-field-command", config.command)
        model_value = self._read_input_with_fallback("#lc-field-model", config.model)
        launcher, options_launcher = self._resolve_launchers(
            option_launcher=option_launcher,
            launcher_value=launcher_value,
        )
        merged_options = self._resolve_merged_options(config, options_launcher)

        config.name = name_value
        config.launcher = cc_dump.app.launcher_registry.normalize_launcher_key(launcher)
        config.command = command_value
        config.model = model_value
        config.shell = self._read_shell_value()
        config.options = merged_options

    def _populate_form(self, config) -> None:
        if config is None:
            return

        for field in _BASE_FIELDS:
            self._sync_base_field_widget(field, _base_field_display_value(field, config))
        self._tool_option_values_state.set(self._build_tool_option_values_state(config))
        self._active_tool_option_set.set(config.launcher)

    def _switch_to_config(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._configs):
            return
        self._apply_form_to_selected()
        self._selected_idx = idx
        self._emit_panel_state()

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
        self._emit_panel_state()

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
        self._emit_panel_state()

    def activate_selected_config(self) -> None:
        self._apply_form_to_selected()
        selected = self._selected_config()
        if selected is None:
            return
        self._active_name = selected.name
        self._emit_panel_state()
        self.post_message(self.Activated(self._active_name, self._configs))

    def quick_launch_selected_config(self) -> None:
        self._apply_form_to_selected()
        selected = self._selected_config()
        if selected is None:
            return
        self.post_message(self.QuickLaunch(selected, self._configs, self._active_name))

    def _do_save(self) -> None:
        self._apply_form_to_selected()
        self._emit_panel_state()
        self.post_message(self.Saved(self._configs, self._active_name))

    def _apply_launcher_selection(self, launcher_value: object) -> None:
        selected = self._selected_config()
        if selected is None:
            return
        old_launcher = selected.launcher
        new_launcher = cc_dump.app.launcher_registry.normalize_launcher_key(
            str(launcher_value)
        )
        if new_launcher == old_launcher:
            return
        self._apply_form_to_selected(
            option_launcher=old_launcher,
            launcher_value=new_launcher,
        )
        self._active_tool_option_set.set(selected.launcher)

    def _action_handlers(self) -> dict[str, Callable[[], object]]:
        return {
            "new": self.create_new_config,
            "delete": self.delete_selected_config,
            "activate": self.activate_selected_config,
            "launch": self.quick_launch_selected_config,
            "save": self._do_save,
            "close": lambda: self.post_message(self.Cancelled()),
        }

    def on_launch_action_chip_pressed(self, event: LaunchActionChip.Pressed) -> None:
        event.stop()
        handler = self._action_handlers().get(event.action_key)
        if handler is not None:
            handler()

    def on_select_changed(self, event: Select.Changed) -> None:
        if self._select_sync_depth > 0:
            event.stop()
            return

        event.stop()

        control = event.select
        control_id = control.id or ""
        if control_id == "lc-config-selector":
            names = [config.name for config in self._configs]
            if event.value in names:
                idx = names.index(event.value)
                if idx != self._selected_idx:
                    self._switch_to_config(idx)
            return

        if control_id == "lc-field-launcher":
            self._apply_launcher_selection(event.value)

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
