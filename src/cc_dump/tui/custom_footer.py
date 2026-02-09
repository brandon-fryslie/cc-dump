"""Custom Footer widget with styled keybinding descriptions."""

from collections import defaultdict
from itertools import groupby

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Footer
from textual.widgets._footer import FooterKey, KeyGroup, FooterLabel

import cc_dump.palette


class StyledFooterKey(FooterKey):
    """FooterKey that supports Rich markup in the description."""

    def render(self) -> Text:
        """Render the footer key with markup support in description."""
        key_style = self.get_component_rich_style("footer-key--key")
        key_display = self.key_display
        key_padding = self.get_component_styles("footer-key--key").padding
        description_padding = self.get_component_styles(
            "footer-key--description"
        ).padding

        description = self.description
        if description:
            # Parse Rich markup in description using Text.from_markup
            description_text = Text.from_markup(description)

            # Build the full text with key and description
            label_text = Text()
            if key_display:
                label_text.append(
                    " " * key_padding.left + key_display + " " * key_padding.right,
                    style=key_style,
                )
            label_text.append(" " * description_padding.left)
            label_text.append_text(description_text)  # Append the styled text
            label_text.append(" " * description_padding.right)
        else:
            # No description, just show key
            label_text = Text.assemble(
                (
                    " " * key_padding.left + key_display + " " * key_padding.right,
                    key_style,
                )
            )

        return label_text


class StyledFooter(Footer):
    """Footer widget that styles keybinding letters using | markers.

    Format: "x|yz" means render as "xyz" with "x" in bold orange
    Format: "ab|c|de" means render as "abcde" with "c" in bold orange

    This footer ONLY shows the description (with bold styling), NOT the key prefix.
    """

    # Maps cycle action -> (filter key, CSS class suffix)
    # Built dynamically at class load time from palette
    ACTION_TO_FILTER: dict = {}
    DEFAULT_CSS: str = ""

    # Level display icons: · (existence), ◐ (summary), ● (full)
    _LEVEL_ICONS = {1: "\u00b7", 2: "\u25d0", 3: "\u25cf"}

    @classmethod
    def _init_palette_colors(cls):
        """Initialize ACTION_TO_FILTER and DEFAULT_CSS from palette."""
        p = cc_dump.palette.PALETTE

        _filter_names = [
            ("toggle_vis('headers')", "headers"),
            ("toggle_vis('user')", "user"),
            ("toggle_vis('assistant')", "assistant"),
            ("toggle_vis('tools')", "tools"),
            ("toggle_vis('system')", "system"),
            ("toggle_vis('budget')", "budget"),
            ("toggle_vis('metadata')", "metadata"),
            ("toggle_economics", "economics"),
            ("toggle_timeline", "timeline"),
        ]
        action_map = {}
        css_parts = []
        for action, filter_key in _filter_names:
            action_map[action] = (filter_key, filter_key)
            fg_hex = p.filter_color(filter_key)
            css_parts.append(
                f"    StyledFooterKey.-active-{filter_key} {{\n"
                f"        color: {fg_hex};\n"
                f"    }}"
            )
        cls.ACTION_TO_FILTER = action_map
        cls.DEFAULT_CSS = "\n".join(css_parts)

    def __init__(
        self,
        *children,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
        show_command_palette: bool = True,
        compact: bool = False,
    ):
        super().__init__(
            *children,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
            show_command_palette=show_command_palette,
            compact=compact,
        )
        self._active_filters = {}
        self._base_descriptions = {}  # Store original descriptions for icon updates

    def update_active_state(self, filters: dict):
        """Update the active state of bindings based on filter levels.

        For category filters (Level values): active when level > EXISTENCE (1).
        For panel toggles (bool values): active when True.
        Updates descriptions with level icons (·/◐/●).
        """
        self._active_filters = filters

        for key_widget in self.query(StyledFooterKey):
            action = key_widget.action
            if action in self.ACTION_TO_FILTER:
                filter_key, color = self.ACTION_TO_FILTER[action]
                value = filters.get(filter_key, False)
                # Level int (1-3) or bool
                if isinstance(value, int):
                    is_active = value > 1  # active at SUMMARY or FULL
                    icon = self._LEVEL_ICONS.get(value, "")
                    # Update description with icon
                    base = self._base_descriptions.get(action, "")
                    if base:
                        key_widget.description = f"{icon}{base}"
                else:
                    is_active = bool(value)
                key_widget.set_class(is_active, f"-active-{color}")

    def compose(self) -> ComposeResult:
        """Compose footer with styled bindings (no key prefix shown)."""
        if not self._bindings_ready:
            return

        active_bindings = self.screen.active_bindings
        bindings = [
            (binding, enabled, tooltip)
            for (_, binding, enabled, tooltip) in active_bindings.values()
            if binding.show
        ]

        action_to_bindings: defaultdict[str, list[tuple]] = defaultdict(list)
        for binding, enabled, tooltip in bindings:
            action_to_bindings[binding.action].append((binding, enabled, tooltip))

        self.styles.grid_size_columns = len(action_to_bindings)

        for group, multi_bindings_iterable in groupby(
            action_to_bindings.values(),
            lambda multi_bindings_: multi_bindings_[0][0].group,
        ):
            multi_bindings = list(multi_bindings_iterable)
            if group is not None and len(multi_bindings) > 1:
                with KeyGroup(classes="-compact" if group.compact else ""):
                    for multi_bindings in multi_bindings:
                        binding, enabled, tooltip = multi_bindings[0]
                        styled_desc = self._style_description(binding.description)
                        # Store base description for icon updates
                        self._base_descriptions[binding.action] = styled_desc

                        # Check if this binding is active
                        filter_key, color = self.ACTION_TO_FILTER.get(
                            binding.action, (None, None)
                        )
                        is_active = self._is_filter_active(filter_key)

                        classes = "-grouped"
                        if is_active and color:
                            classes += f" -active-{color}"

                        yield StyledFooterKey(
                            binding.key,
                            "",  # Don't show key display separately
                            styled_desc,  # Show styled description only
                            binding.action,
                            disabled=not enabled,
                            tooltip=tooltip or binding.description,
                            classes=classes,
                        ).data_bind(compact=Footer.compact)
                yield FooterLabel(group.description)
            else:
                for multi_bindings in multi_bindings:
                    binding, enabled, tooltip = multi_bindings[0]
                    styled_desc = self._style_description(binding.description)
                    # Store base description for icon updates
                    self._base_descriptions[binding.action] = styled_desc

                    # Check if this binding is active
                    filter_key, color = self.ACTION_TO_FILTER.get(
                        binding.action, (None, None)
                    )
                    is_active = self._is_filter_active(filter_key)

                    classes = ""
                    if is_active and color:
                        classes = f"-active-{color}"

                    yield StyledFooterKey(
                        binding.key,
                        "",  # Don't show key display separately
                        styled_desc,  # Show styled description only
                        binding.action,
                        disabled=not enabled,
                        tooltip=tooltip,
                        classes=classes,
                    ).data_bind(compact=Footer.compact)

        # Command palette binding
        if self.show_command_palette and self.app.ENABLE_COMMAND_PALETTE:
            try:
                _node, binding, enabled, tooltip = active_bindings[
                    self.app.COMMAND_PALETTE_BINDING
                ]
            except KeyError:
                pass
            else:
                yield FooterKey(
                    binding.key,
                    self.app.get_key_display(binding),
                    binding.description,
                    binding.action,
                    classes="-command-palette",
                    disabled=not enabled,
                    tooltip=binding.tooltip or binding.description,
                )

    def _is_filter_active(self, filter_key: str | None) -> bool:
        """Check if a filter is active (Level > EXISTENCE or bool True)."""
        if filter_key is None:
            return False
        value = self._active_filters.get(filter_key, False)
        if isinstance(value, int):
            return value > 1  # active at SUMMARY or FULL
        return bool(value)

    def _get_accent_color(self) -> str:
        """Get the accent color hex from palette."""
        return cc_dump.palette.PALETTE.accent

    def _style_description(self, description: str) -> str:
        """Convert pipe markers to rich markup for bold orange styling.

        "x|yz" -> "[bold <accent>]x[/bold <accent>]yz"
        "ab|c|de" -> "ab[bold <accent>]c[/bold <accent>]de"
        """
        parts = description.split("|")

        if len(parts) == 1:
            # No markers
            return description
        elif len(parts) == 2:
            # Simple case: "x|yz"
            return f"[bold {self._get_accent_color()}]{parts[0]}[/bold {self._get_accent_color()}]{parts[1]}"
        elif len(parts) == 3:
            # Middle marker: "ab|c|de"
            return f"{parts[0]}[bold {self._get_accent_color()}]{parts[1]}[/bold {self._get_accent_color()}]{parts[2]}"
        else:
            # Fallback: remove all markers
            return "".join(parts)


# Initialize palette colors at module load time
StyledFooter._init_palette_colors()
