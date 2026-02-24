"""Custom conversation tabs with owned underline rendering."""

from itertools import zip_longest
from typing import TypeVar, cast

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import ContentSwitcher
from textual.widgets._tabbed_content import ContentTab, ContentTabs, TabPane, TabbedContent
from textual.widgets._tabs import Underline

ExpectType = TypeVar("ExpectType", bound=Widget)


class CustomUnderline(Underline):
    """Underline renderer with app-specific endcap rules."""

    DEFAULT_CSS = """
    CustomUnderline {
        width: 1fr;
        height: 1;
        & > .underline--bar {
            /* Solid colors (no alpha) for stable border appearance. */
            color: $primary;
            background: $border;
        }
    }
    """

    _LINE = "─"
    _START_CAP = "┌"
    _END_CAP = "┐"

    def render(self):
        # [LAW:dataflow-not-control-flow] Always render base line and active span;
        # variability is encoded in start/end values only.
        bar_style = self.get_component_rich_style("underline--bar")
        highlight_style = Style.from_color(bar_style.color)
        # Keep baseline underline as a solid (non-gray) stroke.
        background_style = Style.from_color(bar_style.color)
        width = max(0, int(self.size.width))
        if width <= 0:
            return Text("", end="")

        start_f, end_f = self._highlight_range
        start = max(0, min(width, int(round(start_f)) - 1))
        end = max(start, min(width, int(round(end_f)) + 1))

        if end <= start:
            return Text(self._LINE * width, style=background_style, end="")

        segment = end - start
        highlight_chars = [self._LINE] * segment
        highlight_chars[0] = self._START_CAP if start <= 0 else self._LINE
        highlight_chars[-1] = self._END_CAP if end >= width else self._LINE

        output = Text("", end="")
        if start > 0:
            # Keep a left elbow visible even when the leftmost tab is not active.
            output.append(
                self._START_CAP + (self._LINE * (start - 1)),
                style=background_style,
            )
        output.append("".join(highlight_chars), style=highlight_style)
        if end < width:
            output.append(self._LINE * (width - end), style=background_style)
        return output


class CustomContentTabs(ContentTabs):
    """ContentTabs variant that uses CustomUnderline."""

    DEFAULT_CSS = """
    CustomContentTabs {
        width: 100%;
        height: 2;
    }
    CustomContentTabs Tab.-active {
        /* Active tab fill should be a clear variant lighten swatch. */
        background: $primary-lighten-3;
        color: $text;
        text-style: bold;
    }
    CustomContentTabs:focus Tab.-active {
        background: $primary-lighten-3;
        color: $text;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="tabs-scroll"):
            with Vertical(id="tabs-list-bar"):
                with Horizontal(id="tabs-list"):
                    yield from self._tabs
                yield CustomUnderline()


class CustomTabbedContent(TabbedContent):
    """TabbedContent variant that owns tab widget/underline rendering."""

    def get_child_by_type(self, expect_type: type[ExpectType]) -> ExpectType:
        # [LAW:locality-or-seam] Seam to keep Textual internals (which request
        # exact ContentTabs type) compatible with CustomContentTabs.
        if expect_type is ContentTabs:
            try:
                custom_tabs = self.query_one(CustomContentTabs)
            except NoMatches as exc:
                raise NoMatches(f"No immediate child of type {expect_type}; {self._nodes}") from exc
            return cast(ExpectType, custom_tabs)
        return super().get_child_by_type(expect_type)

    def compose(self) -> ComposeResult:
        # [LAW:one-source-of-truth] Preserve canonical TabbedContent pane/tab derivation.
        pane_content = [
            self._set_id(
                (
                    content
                    if isinstance(content, TabPane)
                    else TabPane(title or self.render_str(f"Tab {index}"), content)
                ),
                self._generate_tab_id(),
            )
            for index, (title, content) in enumerate(
                zip_longest(self.titles, self._tab_content), 1
            )
        ]
        tabs = [
            ContentTab(
                content._title,
                content.id or "",
                disabled=content.disabled,
            )
            for content in pane_content
        ]

        yield CustomContentTabs(*tabs, active=self._initial or None, tabbed_content=self)
        with ContentSwitcher(initial=self._initial or None):
            yield from pane_content
