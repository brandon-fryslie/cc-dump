# Panels

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
- **State model:** `SessionPanelState` frozen dataclass with `session_id: str | None` and `last_message_time: float | None`, wrapped in an `Observable`. A `reaction` on `(_clock_tick, _state)` drives rendering.
- **Auto-refresh:** 1-second interval timer increments `_clock_tick` Observable, triggering re-evaluation of connection status (connected = last message within 120 seconds, defined by `_CONNECTION_TIMEOUT_S`).
- **Sub-modes:** None. `cycle_mode()` is a no-op.
- **Interaction:** Clicking on the session ID span copies it to clipboard with a notification. Span boundaries are tracked as `(start, end)` character offsets returned by `render_session_panel()`.
- **Age formatting tiers** (from `_format_age` in `panel_renderers.py`):
  - `<60s`: per-second (`"42s ago"`)
  - `<3600s`: per-minute (`"~3 min ago"`)
  - `<43200s`: 30-min resolution (`"~2.5hr ago"`)
  - `>=43200s`: capped (`"12+ hours ago"`)

**Source:** `src/cc_dump/tui/session_panel.py`, `src/cc_dump/tui/panel_renderers.py`

#### Stats Panel (Analytics Dashboard)

- **Name:** `stats`
- **Widget:** `StatsPanel` (Static subclass)
- **CSS ID:** `stats-panel`
- **Factory:** `cc_dump.tui.widget_factory.create_stats_panel`
- **Shows:** Token usage analytics from the current session
- **Data source:** `panel:stats_snapshot` view store key, containing `summary`, `timeline`, and `models` dicts
- **Sub-modes:** Three views cycled with `,`, tracked internally by `_view_index`:
  1. **Summary** — Turn count, total tokens, cost, input/output/cache breakdown, cache hit %, cache savings, active model count, latest model, lane counts (main/subagent active and all), capacity usage (requires `CC_DUMP_TOKEN_CAPACITY` env var)
  2. **Timeline** — Per-turn table (last 12 turns) showing turn number, model, input tokens, output tokens, cache %, delta input, plus a sparkline trend of input totals
  3. **Models** — Per-model breakdown table: turns, input total, output total, cache %, token share %, cost

Each view displays a tab bar (`SUMMARY | timeline | models`) with the active view uppercased. The tab bar includes a `(Tab/, cycle)` hint.

- **Rendering dispatch:** `_ANALYTICS_VIEW_RENDERERS` dict maps mode name to pure render function (`render_analytics_summary`, `render_analytics_timeline`, `render_analytics_models`). `render_analytics_panel()` is the unified entry point.

**Source:** `src/cc_dump/tui/panel_renderers.py`, `src/cc_dump/tui/widget_factory.py`

### Toggle Panels

Toggle panels are shown/hidden by dedicated keys. Their visibility is managed through `panel:<name>` boolean keys in the view store. All default to hidden (`false`) on startup.

#### Info Panel

- **Key:** `i`
- **Store key:** `panel:info`
- **Widget:** `InfoPanel` (Static subclass, docked bottom)
- **CSS:** `max-height: 20`, `dock: bottom`, `border: solid $accent`, `padding: 0 1`, `overflow-y: auto`
- **Visibility mechanism:** Dual — both the app's `_sync_chrome_panels` reaction and the widget's own `_visibility_reaction` watch `panel:info` and set `self.display`. Both converge to the same value.
- **State model:** `_info` Observable dict, with a `reaction` driving `_render_info()`.
- **Shows:** Server configuration in a labeled-row format:
  - Provider proxy URLs (one per configured provider, with env var name). Supports multi-provider configuration with per-provider hints.
  - Session ID
  - Recording path (or "disabled")
  - Recordings directory
  - Replay source file (or "--")
  - Python version
  - Textual version
  - PID
  - Usage hints at bottom showing the `ENV_VAR=url tool` invocation pattern per provider
- **Row data source:** `info_panel_rows()` in `panel_renderers.py` returns `list[tuple[str, str, str]]` — `(label, display_value, copy_value)`. The `copy_value` differs from `display_value` for proxy rows (formatted as `ENV_VAR=url`).
- **Interaction:** Click any row to copy its `copy_value` to clipboard. Row index is determined by `event.y - 1` (subtracting the "Server Info" title row).

**Source:** `src/cc_dump/tui/info_panel.py`, `src/cc_dump/tui/panel_renderers.py`

#### Keys Panel

- **Key:** `?`
- **Store key:** `panel:keys`
- **Widget:** `KeysPanel` (VerticalScroll, docked right)
- **CSS:** `width: 28%`, `min-width: 24`, `max-width: 36`, `border-left: solid $accent`, `padding: 1`
- **Shows:** All keyboard shortcuts grouped by category, sourced from `KEY_GROUPS` in `input_modes.py`:
  - **Nav:** `g/G`, `j/k`, `h/l`, `^D/^U`, `^F/^B`
  - **Categories:** `1-6`, `Q-Y`, `q-y`
  - **Panels:** `.`, `,`, `f`, `^L`, `i`, `?`
  - **Search:** `/`, `=/-`, `M-n/M-p`, `F1-9`
  - **Other:** `[/]`, `{/}`, `c`, `C`, `D`, `L`, `S`, `^C ^C`
- **Stateless:** `get_state()` returns `{}`. `restore_state()` re-renders from `KEY_GROUPS`.
- **Rendering:** `render_keys_panel()` in `panel_renderers.py` builds a `Rich.Text` with bold underline group titles and right-aligned key labels.

**Source:** `src/cc_dump/tui/keys_panel.py`, `src/cc_dump/tui/panel_renderers.py`

#### Logs Panel

- **Key:** `Ctrl+L`
- **Store key:** `panel:logs`
- **Widget:** `LogsPanel` (RichLog subclass, docked bottom)
- **Shows:** cc-dump application logs (debug, errors, internal messages) with level-colored styling
- **Capacity:** 1000 lines max (`max_lines=1000`)

**Source:** `src/cc_dump/tui/widget_factory.py`

#### Settings Panel

- **Key:** `S`
- **Store key:** `panel:settings`
- **Widget:** `SettingsPanel` (VerticalScroll, docked right)
- **CSS:** `width: 35%`, `min-width: 30`, `max-width: 50`, `border-left: solid $accent`
- **Shows:** Editable application settings defined by `SETTINGS_FIELDS` registry
- **Field types:** `FieldDef` dataclass with `kind` discriminator: `text` (Input), `bool` (ToggleChip), `select` (Select dropdown)
- **SETTINGS_FIELDS is empty.** The list is defined but contains zero entries. The panel infrastructure (field rendering, save/cancel messaging, value collection) exists but has no configured fields.
- **Messages posted:**
  - `SettingsPanel.Saved(values: dict)` — posted on `Enter`
  - `SettingsPanel.Cancelled()` — posted on `Escape`
- **Interaction model:**
  - `Tab` cycles between fields
  - `Enter` saves (posts `Saved` with collected values)
  - `Escape` cancels (posts `Cancelled`)
- **Toggle mechanism:** Settings and launch config use custom open/close handlers (`_open_settings`/`_close_settings` in app.py) rather than simple store boolean flips, because they have additional setup (loading config values, initializing widgets).
- **Creation:** On-demand — widget is created when first opened. Survives hot-reload via sidebar sync.

**Source:** `src/cc_dump/tui/settings_panel.py`

#### Launch Config Panel

- **Key:** `C`
- **Store key:** `panel:launch_config`
- **Widget:** `LaunchConfigPanel` (VerticalScroll, docked right)
- **CSS:** `width: 35%`, `min-width: 34`, `max-width: 55`, `border-left: solid $accent`
- **Shows:** Launch configuration editor for tmux-based tool launching
- **State model:** Three `Observable` instances:
  - `_panel_state` (`LaunchConfigPanelViewState`: `active_name`, `selected_idx`, `revision`) — drives selector/active/form sync
  - `_tool_option_values_state` (`ToolOptionValuesViewState`) — drives tool option widget hydration
  - `_active_tool_option_set` (str) — drives tool-specific option set visibility
- **Content:**
  - Preset selector (Select dropdown of named configs)
  - Action chips: New, Delete, Activate, Launch, Save, Close
  - Active preset indicator label
  - Base fields: Name (text), Tool/launcher (select), Command (text), Model (text), Shell (select with `(none)` + shell options)
  - Tool-specific options: Common options shared by all launchers, plus launcher-specific options shown/hidden based on selected launcher
- **Tool option architecture:** Options are organized into:
  - `_COMMON_TOOL_OPTION_DEFS` — options present in all launcher profiles
  - `_TOOL_SPECIFIC_OPTION_DEFS_BY_LAUNCHER` — options unique to specific launchers
  - All option widgets are pre-composed; visibility is toggled by `_apply_active_tool_option_set()`
- **Messages posted:**
  - `LaunchConfigPanel.Saved(configs, active_name)` — on Save action
  - `LaunchConfigPanel.Cancelled()` — on Close action or Escape
  - `LaunchConfigPanel.QuickLaunch(config, configs, active_name)` — on Launch action
  - `LaunchConfigPanel.Activated(name, configs)` — on Activate action
- **Interaction model:**
  - `Tab`/`Shift+Tab` navigate fields
  - `Enter`/`Space` activate focused control
  - `Escape` closes panel (not handled directly; Close chip posts `Cancelled`)
  - Config switching: selecting a different preset in the dropdown calls `_switch_to_config()` which saves current form to model, then populates form from new config
  - Name deduplication: `_dedupe_name_for_selected()` ensures unique names across configs
  - Select event gating: `_suspend_select_events()` context manager prevents programmatic Select mutations from being treated as user input
- **Creation:** On-demand, persists while open. Survives hot-reload via sidebar sync.

**Source:** `src/cc_dump/tui/launch_config_panel.py`

#### Debug Settings Panel

- **Key:** `D`
- **Store key:** `panel:debug_settings`
- **Widget:** `DebugSettingsPanel` (VerticalScroll, docked right)
- **CSS:** `width: 35%`, `min-width: 30`, `max-width: 50`, `border-left: solid $accent`
- **Shows:** Runtime debug toggles (changes apply immediately, session-only):
  - **Log level** — Select dropdown: DEBUG/INFO/WARNING/ERROR. Changes `cc_dump` logger level immediately via `logging.getLogger("cc_dump").setLevel()`.
  - **Perf logging** — ToggleChip. Enables stack traces on slow render stages via `cc_dump.io.perf_logging`.
  - **Memory snapshots** — ToggleChip. Enables tracemalloc at runtime. Starting/stopping tracing is managed reactively via `_apply_toggle_state()`.
- **State model:** `_toggle_state` Observable `tuple[bool, bool]` for perf/memory toggles. A `reaction` applies side effects.
- **Interaction:** Changes apply immediately on toggle. `Escape` closes the panel (sets `panel:debug_settings` to `False` directly on store). Focus auto-advances to first focusable child on open.

**Source:** `src/cc_dump/tui/debug_settings_panel.py`

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

Four view store computeds project store state into grouped tuples, and four reactions in `setup_reactions()` sync widget visibility:

1. **`_sync_panel_display`** — Watches `panel:active`. Shows matching cycling panel, hides others.
2. **`_sync_chrome_panels`** — Watches `chrome_panel_state` computed (tuple of `panel:logs`, `panel:info`). Toggles display on existing bottom-dock widgets. Note: InfoPanel also has its own internal `_visibility_reaction` watching `panel:info` — both set `self.display` to the same value.
3. **`_sync_sidebar_panels`** — Watches `sidebar_panel_state` computed (tuple of `panel:settings`, `panel:launch_config`). Creates widgets on-demand if missing. Manages focus: open sidebar gets `focus_default_control()`, closing returns focus to conversation.
4. **`_sync_aux_panels`** — Watches `aux_panel_state` computed (tuple of `panel:keys`, `panel:debug_settings`). Keys panel is mounted once and display-toggled. Debug panel is fully mounted/unmounted on toggle.

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

**Source:** `src/cc_dump/tui/action_config.py`, `src/cc_dump/tui/action_handlers.py`

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

**Source:** `src/cc_dump/tui/panel_registry.py`

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
