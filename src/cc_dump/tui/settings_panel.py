"""Application settings panel (non-proxy settings only).

This module is RELOADABLE.

// [LAW:locality-or-seam] Proxy settings are intentionally split into proxy_settings_panel.py.
"""

from __future__ import annotations

import cc_dump.app.settings_store
from cc_dump.tui.settings_form_panel import FieldDef, SettingsFormPanel


def build_settings_fields() -> list[FieldDef]:
    return [
        FieldDef(
            key="auto_zoom_default",
            label="Auto-Zoom Default",
            description="Start with tmux auto-zoom enabled",
            kind="bool",
            default=bool(cc_dump.app.settings_store.SCHEMA["auto_zoom_default"]),
        ),
        FieldDef(
            key="side_channel_enabled",
            label="AI Summaries",
            description="Enable AI-powered summaries via claude -p",
            kind="bool",
            default=bool(cc_dump.app.settings_store.SCHEMA["side_channel_enabled"]),
        ),
    ]


SETTINGS_FIELDS: tuple[FieldDef, ...] = tuple(build_settings_fields())


class SettingsPanel(SettingsFormPanel):
    def __init__(self, initial_values: dict | None = None) -> None:
        super().__init__(
            panel_key="settings",
            title="Settings",
            fields=SETTINGS_FIELDS,
            initial_values=initial_values,
        )


def create_settings_panel(initial_values: dict | None = None) -> SettingsPanel:
    return SettingsPanel(initial_values=initial_values)
