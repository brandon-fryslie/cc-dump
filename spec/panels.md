# Panels

**Status:** draft

## Why Panels Exist

Claude Code conversations generate structured metadata alongside the visible dialogue: token counts, cache hit ratios, cost estimates, model breakdowns, connection status, session IDs, recording paths, and runtime configuration. This information does not belong inline in the conversation stream — it is ambient context that the user consults on demand. Panels provide dedicated, persistent regions of the TUI where this metadata lives, accessible through keyboard shortcuts without disrupting the conversation view.

Panels serve three distinct roles:

1. **Cycling panels** — always-visible bottom-dock panels that share a single slot, cycled with `.` and sub-mode cycled with `,`. These show live session and analytics data.
2. **Toggle panels** — overlay or docked panels toggled on/off by dedicated keys. These include server info, keyboard shortcuts, logs, settings, launch configs, and debug controls.
3. **Data projection panels** — panels whose content is derived from a canonical view store snapshot, ensuring one source of truth for displayed values.

## Panel Categories

### Cycling Panels (Bottom Dock)

Exactly one cycling panel is visible at a time. The `panel:active` view store key holds the name of the currently active cycling panel. Cycling order is defined by `PANEL_REGISTRY` in `panel_registry.py`.

#### Session Panel

- **Name:** `session`
- **Key:** Active by default on startup (`panel:active` defaults to `"session"`)
- **Widget:** `SessionPanel` (Static subclass)
- **CSS ID:** `session-panel`
- **Shows:** Connection indicator (filled/hollow circle), Connected/Disconnected label, time since last message (tiered formatting: seconds, minutes, hours, 12+ hours), session UUID (full, click-to-copy)
- **Data source:** `panel:session_state` view store key, containing `session_id` and `last_message_time`
- **Auto-refresh:** 1-second interval timer re-evaluates connection status (connected = last message within 120 seconds)
- **Sub-modes:** None. `cycle_mode()` is a no-op.
- **Interaction:** Clicking on the session ID span copies it to clipboard with a notification.

#### Stats Panel (Analytics Dashboard)

- **Name:** `stats`
- **Widget:** `StatsPanel` (Static subclass)
- **CSS ID:** `stats-panel`
- **Shows:** Token usage analytics from the current session
- **Data source:** `panel:stats_snapshot` view store key, containing `summary`, `timeline`, and `models` dicts
- **Sub-modes:** Three views cycled with `,`:
  1. **Summary** — Turn count, total tokens, cost, input/output/cache breakdown, cache hit %, cache savings, active model count, latest model, lane counts (main/subagent), capacity usage
  2. **Timeline** — Per-turn table (last 12 turns) showing turn number, model, input tokens, output tokens, cache %, delta input, plus a sparkline trend of input totals
  3. **Models** — Per-model breakdown table: turns, input total, output total, cache %, token share %, cost

Each view displays a tab bar (`SUMMARY | timeline | models`) with the active view uppercased. The tab bar includes a `(Tab/, cycle)` hint.

### Toggle Panels

Toggle panels are shown/hidden by dedicated keys. Their visibility is managed through `panel:<name>` boolean keys in the view store. All default to hidden (`false`) on startup.

#### Info Panel

- **Key:** `i`
- **Store key:** `panel:info`
- **Widget:** `InfoPanel` (Static subclass, docked bottom)
- **CSS:** `max-height: 20`, border, padding
- **Shows:** Server configuration in a labeled-row format:
  - Provider proxy URLs (one per configured provider, with env var name)
  - Session ID
  - Recording path (or "disabled")
  - Recordings directory
  - Replay source file (or "--")
  - Python version
  - Textual version
  - PID
  - Usage hints at bottom showing the `ENV_VAR=url tool` invocation pattern
- **Interaction:** Click any row to copy its value to clipboard. Proxy rows copy `ENV_VAR=url` format; other rows copy the display value.

#### Keys Panel

- **Key:** `?`
- **Store key:** `panel:keys`
- **Widget:** `KeysPanel` (VerticalScroll, docked right, 28% width, 24-36 columns)
- **Shows:** All keyboard shortcuts grouped by category (Nav, Categories, Panels, Search, Other), sourced from `KEY_GROUPS` in `input_modes.py`
- **Stateless:** No persisted state. Re-renders from `KEY_GROUPS` on hot-reload.
- **Also accessible via:** Textual's built-in help command (overridden to use this panel)

#### Logs Panel

- **Key:** `Ctrl+L`
- **Store key:** `panel:logs`
- **Widget:** `LogsPanel` (RichLog, docked bottom)
- **Shows:** cc-dump application logs (debug, errors, internal messages) with level-colored styling
- **Capacity:** 1000 lines max

#### Settings Panel

- **Key:** `S`
- **Store key:** `panel:settings`
- **Widget:** `SettingsPanel` (VerticalScroll, docked right, 35% width, 30-50 columns)
- **Shows:** Editable application settings defined by `SETTINGS_FIELDS` registry
- **Field types:** text (Input), bool (ToggleChip), select (Select dropdown)
- **Interaction model:**
  - `Tab` cycles between fields
  - `Enter` saves and posts `Saved` message to app
  - `Escape` cancels and posts `Cancelled` message to app
- **Creation:** On-demand — widget is created when first opened and persists (display toggled). Survives hot-reload via sidebar sync.
- **Note:** `SETTINGS_FIELDS` is currently empty. The panel infrastructure exists but has no configured fields. [UNVERIFIED — fields may be populated dynamically or planned for future use]

#### Launch Config Panel

- **Key:** `C`
- **Store key:** `panel:launch_config`
- **Widget:** `LaunchConfigPanel` (VerticalScroll, docked right, 35% width, 34-55 columns)
- **Shows:** Launch configuration editor for tmux-based tool launching
- **Content:**
  - Preset selector (Select dropdown of named configs)
  - Action chips: New, Delete, Activate, Launch, Save, Close
  - Active preset indicator
  - Base fields: Name, Tool (launcher), Command, Model, Shell
  - Tool-specific options: Common options shared by all launchers, plus launcher-specific options shown/hidden based on selected launcher
- **Interaction model:**
  - `Tab`/`Shift+Tab` navigate fields
  - `Enter`/`Space` activate focused control
  - `Escape` closes panel
  - Action chips trigger messages: `Saved`, `Cancelled`, `QuickLaunch`, `Activated`
- **Creation:** On-demand, persists while open. Survives hot-reload via sidebar sync.

#### Debug Settings Panel

- **Key:** `D`
- **Store key:** `panel:debug_settings`
- **Widget:** `DebugSettingsPanel` (VerticalScroll, docked right, 35% width, 30-50 columns)
- **Shows:** Runtime debug toggles (changes apply immediately, session-only):
  - Log level selector (DEBUG/INFO/WARNING/ERROR)
  - Perf logging toggle (stack traces on slow render stages)
  - Memory snapshots toggle (tracemalloc at startup/shutdown)
- **Interaction:** Changes apply immediately on toggle. `Escape` closes the panel.

## Panel Cycling

### Cycling Bottom Panels (`.` key)

The `.` key advances `panel:active` through `PANEL_ORDER`:

```
session → stats → session → ...
```

The `_sync_panel_display` watcher sets `widget.display = (name == active)` for every registered cycling panel, so exactly one is visible at a time.

### Cycling Sub-Modes (`,` key)

The `,` key calls `cycle_mode()` on the currently active cycling panel:

- **Session panel:** No-op (single mode)
- **Stats panel:** Cycles `summary → timeline → models → summary`

The sub-mode is tracked internally by `_view_index` on the StatsPanel widget.

## Panel Coordination Architecture

### View Store as Source of Truth

All panel visibility is driven by keys in the view store (`app/view_store.py`). The store schema defines defaults:

| Store Key | Default | Purpose |
|-----------|---------|---------|
| `panel:active` | `"session"` | Which cycling panel is shown |
| `panel:settings` | `false` | Settings sidebar open |
| `panel:launch_config` | `false` | Launch config sidebar open |
| `panel:logs` | `false` | Logs panel visible |
| `panel:info` | `false` | Info panel visible |
| `panel:keys` | `false` | Keys panel visible |
| `panel:debug_settings` | `false` | Debug settings visible |
| `panel:stats_snapshot` | `{}` | Analytics data for stats panel |
| `panel:session_state` | `{}` | Session data for session panel |

### Sync Watchers

Four reactive watchers project store state into widget visibility:

1. **`_sync_panel_display`** — Watches `panel:active`. Shows matching cycling panel, hides others.
2. **`_sync_chrome_panels`** — Watches `(panel:logs, panel:info)`. Toggles display on existing bottom-dock widgets.
3. **`_sync_sidebar_panels`** — Watches `(panel:settings, panel:launch_config)`. Creates widgets on-demand if missing. Manages focus: open sidebar gets `focus_default_control()`, closing returns focus to conversation.
4. **`_sync_aux_panels`** — Watches `(panel:keys, panel:debug_settings)`. Keys panel is mounted once and display-toggled. Debug panel is fully mounted/unmounted on toggle.

### Toggle Dispatch

Non-cycling panels use `_toggle_panel()` which flips the boolean at the panel's store key via `PANEL_TOGGLE_CONFIG`:

```python
PANEL_TOGGLE_CONFIG = {
    "logs": "panel:logs",
    "info": "panel:info",
    "keys": "panel:keys",
    "debug_settings": "panel:debug_settings",
}
```

Settings and launch config use custom open/close handlers because they have additional setup (loading configs, initializing values).

### Docking Positions

- **Bottom dock:** Session panel, stats panel, info panel, logs panel
- **Right dock:** Keys panel, settings panel, launch config panel, debug settings panel

### Panel Registry

The cycling panel registry (`panel_registry.py`) is the single source of truth for cycling panel ordering:

```python
PANEL_REGISTRY = [
    PanelSpec("session", "session-panel", "cc_dump.tui.session_panel.create_session_panel"),
    PanelSpec("stats", "stats-panel", "cc_dump.tui.widget_factory.create_stats_panel"),
]
```

Each `PanelSpec` carries a dotted factory path that is resolved dynamically (supporting hot-reload). `PANEL_ORDER` and `PANEL_CSS_IDS` are derived automatically.

## Hot-Reload Behavior

All panel modules are reloadable. On hot-reload:

- **Cycling panels:** Widgets are replaced via the factory path in the registry. State is transferred via `get_state()`/`restore_state()` (e.g., StatsPanel preserves `view_index`; SessionPanel preserves `session_id` and `last_message_time`).
- **Sidebar panels (settings, launch config):** Survive hot-reload because `_sync_sidebar_panels` recreates them on-demand when the store says visible but no widget exists.
- **Aux panels (keys, debug):** Keys panel is re-mounted if missing. Debug panel is mounted/unmounted based on store flag.
- **Rendering logic:** `panel_renderers.py` contains pure rendering functions that are hot-reloaded independently of widget instances.

## Keyboard Reference

| Key | Action | Panel |
|-----|--------|-------|
| `.` | Cycle active cycling panel | session/stats |
| `,` | Cycle sub-mode within active panel | stats views |
| `i` | Toggle info panel | InfoPanel |
| `?` | Toggle keys panel | KeysPanel |
| `Ctrl+L` | Toggle logs panel | LogsPanel |
| `S` | Toggle settings panel | SettingsPanel |
| `C` | Toggle launch config panel | LaunchConfigPanel |
| `D` | Toggle debug settings panel | DebugSettingsPanel |
| `c` | Quick-launch active config | (via tmux, not a panel) |

## Command Palette

Panels are also accessible from Textual's command palette (`Ctrl+P`):
- "Keys" — toggles keys panel
- "Cycle panel" — cycles session/analytics
- "Toggle logs" — toggles logs panel
- "Toggle info" — toggles info panel
