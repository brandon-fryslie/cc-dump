"""Custom Footer widget with styled keybinding descriptions."""

from collections import defaultdict
from itertools import groupby

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Footer
from textual.widgets._footer import FooterKey, KeyGroup, FooterLabel


class StyledFooterKey(FooterKey):
    """FooterKey that supports Rich markup in the description."""

    def render(self) -> Text:
        """Render the footer key with markup support in description."""
        key_style = self.get_component_rich_style("footer-key--key")
        description_style = self.get_component_rich_style("footer-key--description")
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
            label_text.append(" " * description_padding.right, style=description_style)
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

    def update_active_state(self, filters: dict):
        """Update the active state of bindings and recompose if needed."""
        if filters != self._active_filters:
            self._active_filters = filters
            # Recompose to update styling
            self.recompose()

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

        # Map actions to filter states and colors
        action_to_state = {
            "toggle_headers": ("headers", "cyan"),
            "toggle_tools": ("tools", "blue"),
            "toggle_system": ("system", "yellow"),
            "toggle_expand": ("expand", "green"),
            "toggle_metadata": ("metadata", "magenta"),
            "toggle_stats": ("stats", "bright_cyan"),
            "toggle_economics": ("economics", "bright_magenta"),
            "toggle_timeline": ("timeline", "bright_yellow"),
        }

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

                        # Check if this binding is active
                        filter_key, color = action_to_state.get(binding.action, (None, None))
                        is_active = self._active_filters.get(filter_key, False) if filter_key else False

                        classes = "-grouped"
                        if is_active:
                            classes += f" -active-{color}" if color else " -active"

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

                    # Check if this binding is active
                    filter_key, color = action_to_state.get(binding.action, (None, None))
                    is_active = self._active_filters.get(filter_key, False) if filter_key else False

                    classes = ""
                    if is_active:
                        classes = f"-active-{color}" if color else "-active"

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

    def _style_description(self, description: str) -> str:
        """Convert pipe markers to rich markup for bold orange styling.

        "x|yz" -> "[bold #FF8800]x[/bold #FF8800]yz"
        "ab|c|de" -> "ab[bold #FF8800]c[/bold #FF8800]de"
        """
        parts = description.split("|")

        if len(parts) == 1:
            # No markers
            return description
        elif len(parts) == 2:
            # Simple case: "x|yz"
            return f"[bold #FF8800]{parts[0]}[/bold #FF8800]{parts[1]}"
        elif len(parts) == 3:
            # Middle marker: "ab|c|de"
            return f"{parts[0]}[bold #FF8800]{parts[1]}[/bold #FF8800]{parts[2]}"
        else:
            # Fallback: remove all markers
            return "".join(parts)
