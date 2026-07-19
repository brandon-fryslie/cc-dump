# Sessions, Tmux Integration, and Launch Configurations

## Overview

Claude Code sessions are ephemeral and invisible. When a user runs `claude`, a session ID is assigned server-side and embedded in API metadata, but the user never sees it. If Claude Code crashes or the user quits, there is no built-in way to resume where they left off, and no way to know which session produced which traffic. cc-dump solves this by extracting session identity from intercepted API traffic, displaying connection status, and enabling one-click launch and resume of Claude Code sessions through tmux pane management.

From the user's perspective, sessions tie together three things: (1) knowing *which* Claude Code conversation is producing the traffic they see, (2) being able to *launch* Claude Code with the right proxy configuration without manual environment variable setup, and (3) being able to *resume* a previous session by passing the session ID back to Claude Code's `--resume` flag. The tmux integration and launch configuration system exist to make this seamless rather than requiring the user to juggle terminal windows, ports, and environment variables by hand.

## Session Identity

### Source of Truth

Session identity is extracted from the Anthropic API's `metadata.user_id` field in each request body. The field has the compound format:

```
user_<hash>_account_<uuid>_session_<uuid>
```

Parsing is done by `parse_user_id()` (in `formatting_impl.py`) and extracts three components: `user_hash`, `account_id`, and `session_id`. The `session_id` (a UUID) is the canonical session identifier used throughout cc-dump. The same parsing logic is duplicated in `stream_registry.py:_extract_session_id()`, `analytics_store.py:_extract_session_id()`, and `app.py:_extract_session_id_from_body()` -- all delegate to `parse_user_id()` for the actual regex match.

### Where Session ID Appears

- **FormattedBlock.session_id**: Every block in the IR carries the `session_id` (string) of the request that produced it. Set during `format_request_for_provider` after all blocks are constructed.
- **ProviderRuntimeState.current_session**: Per-provider mutable state (in `formatting_impl.py`) tracking the most recently seen session ID. Used to detect session transitions.
- **NewSessionBlock**: Emitted into the block stream whenever `session_id` differs from `ProviderRuntimeState.current_session`. Carries the new `session_id` string.
- **DomainStore._session_boundaries**: A list of `(session_id, turn_index)` pairs recording where each `NewSessionBlock` appeared in the completed turns list. Used for within-tab session navigation.
- **SessionPanel**: Displays the current session ID and connection status in the UI panel strip. Renders via `render_session_panel()` in `panel_renderers.py`. Observes the `panel:session_state` key in the view store.
- **StreamRegistry.RequestStreamContext**: Each active request stream records the `session_id` extracted from the request body.
- **App._session_id**: The most recently seen session ID from the default provider. Updated by `_sync_detected_session` when `ProviderRuntimeState.current_session` changes. Used as the fallback for auto-resume when no non-default session tab is active.

### Session Transition Detection

Session transitions are detected at a single enforcement point: `format_request_for_provider` in `formatting_impl.py`. The sequence is:

1. Request body arrives; `session_id` is parsed from `metadata.user_id`.
2. If `session_id` is non-empty and differs from `ProviderRuntimeState.current_session`, a `NewSessionBlock(session_id=...)` is appended to the block list for that request (after the request header blocks: `NewlineBlock`, `SeparatorBlock`, `HeaderBlock`, `SeparatorBlock`).
3. *After* formatting completes, `_update_session_id` writes the new session ID into `ProviderRuntimeState.current_session`.

The ordering matters: the formatter reads the *old* `current_session` to decide whether to emit `NewSessionBlock`, then the state is updated. This ensures the transition block appears exactly once at the boundary.

### DomainStore Streaming State

`DomainStore` (in `app/domain_store.py`) manages streaming state for in-progress turns:

- **`_stream_turns`**: Maps `request_id` to the list of `FormattedBlock` instances being accumulated for the current streaming turn.
- **`_stream_delta_buffers`**: Maps `request_id` to a list of delta text strings (one per `TextDeltaBlock`).
- **`_stream_delta_text`**: Maps `request_id` to the incrementally joined text (avoids repeated joins in the render path).
- **`_stream_delta_versions`**: Maps `request_id` to a monotonically incrementing version counter for change detection.
- **`_stream_meta`**: Maps `request_id` to arbitrary metadata dict passed at `begin_stream`.
- **`_stream_order`**: Ordered list of active stream `request_id`s (insertion order).
- **`_focused_stream_id`**: The currently focused stream for live rendering preview. Auto-set to the first stream when none is focused.
- **`finalize_stream(request_id)`**: Called when a streaming turn completes. Consolidation logic converts `TextDeltaBlock` instances into a single `TextContentBlock` with the accumulated text, wraps the content in a `MessageBlock`, populates `content_regions`, and adds the completed turn via `_seal_stream`. Metadata blocks (`StreamInfoBlock`, `StopReasonBlock`) are placed outside the `MessageBlock`.
- **`finalize_stream_with_blocks(request_id, final_blocks)`**: Alternative finalization path using externally assembled blocks (for complete-response assembly).
- **`finalize_stream_replacing_turn(request_id, turn_index, combined_blocks)`**: Replaces an existing completed turn with combined request+response blocks while cleaning up the stream.

### Completed Turn Retention

`DomainStore` enforces a maximum number of completed turns via `_max_completed_turns` (default 5000, configurable via `CC_DUMP_MAX_COMPLETED_TURNS` environment variable, minimum 0). When the limit is exceeded after adding a turn, `_enforce_completed_retention` prunes the oldest turns (`del self._completed[:overflow]`) and adjusts session boundary indices accordingly. The `on_turns_pruned` callback notifies the renderer of the pruned count.

### Session Boundaries in DomainStore

When `DomainStore.add_turn` receives a block list containing a `NewSessionBlock` (detected by `type(block).__name__`), it records `(session_id, turn_index)` in `_session_boundaries`. These boundaries:

- Survive hot-reload (DomainStore persists on the app object; also serialized/restored via `get_state()`/`restore_state()`).
- Are adjusted when completed-turn retention pruning removes old turns (indices shift down by the overflow count; boundaries with negative indices are dropped).
- Are exposed via `get_session_boundaries()` for navigation features.

### Connection Status

The `SessionPanel` (in `tui/session_panel.py`) derives "connected" status from `SessionPanelState`:
- **Connected**: `last_message_time` is not None AND `(time.monotonic() - last_message_time) < 120 seconds` (`_CONNECTION_TIMEOUT_S = 120.0`).
- **Disconnected**: Otherwise.

A 1-second interval timer (`set_interval(1.0, self._tick_clock)`) increments `_clock_tick`, which triggers re-evaluation of the reactive projection. The projection calls `render_session_panel()` which displays a filled/empty circle indicator, connection label, age string, and the full session ID (clickable to copy to clipboard).

The age display uses tiered formatting via `_format_age()`:
- <60s: per-second (`"42s ago"`)
- <3600s: per-minute (`"~3 min ago"`)
- <43200s: 30-min resolution (`"~2.5hr ago"`)
- >=43200s: capped (`"12+ hours ago"`)

### Session Panel State Flow

The session panel receives state through a reactive chain:

1. `_track_request_activity` records `time.monotonic()` per session key in `app_state["last_message_time_by_session"]`.
2. `_publish_session_panel_state` derives the canonical `(session_id, last_message_time)` pair from the active tab context and writes it to `view_store["panel:session_state"]`.
3. `SessionPanel._apply_store_state` observes the view store key and projects it into `SessionPanelState`.
4. The 1-second clock tick forces re-evaluation so the age display and connected/disconnected status update even when no new messages arrive.

Clicking the session ID span copies it to the system clipboard via `app.copy_to_clipboard()` and posts a notification.

## Multi-Session Model

### Per-Session Tab Architecture

cc-dump implements per-session isolation through dynamic tab creation. Each session gets its own `DomainStore`, `ConversationView`, and `TabPane`. The app maintains several parallel dictionaries keyed by session key:

- **`_session_domain_stores`**: Maps session key to its `DomainStore` instance.
- **`_session_conv_ids`**: Maps session key to the CSS id of its `ConversationView` widget.
- **`_session_tab_ids`**: Maps session key to its `TabPane` id.

All three are initialized with a single entry for the `__default__` session key, which is the primary view that exists at app startup.

### Session Surface Creation

When a new session key is encountered (via `_resolve_event_session_key` during event routing), `_ensure_session_surface` creates the per-session infrastructure:

1. A new `DomainStore` is instantiated.
2. A new `ConversationView` is created (bound to the new DomainStore and the shared view store/render runtime).
3. A new `TabPane` is added to the conversation tabs widget.
4. All three mapping dictionaries are updated.

**Auto-focus behavior**: When the first non-default session appears and the default tab has no data (no completed turns and no active streams), the new tab is automatically activated.

### Session Key Resolution

Session keys are resolved differently depending on the event source:

- **Default provider requests**: The session key is derived from the session ID extracted from the request body's `metadata.user_id`. If no session ID is present, falls back to `__default__`.
- **Non-default provider requests** (e.g., Copilot): The session key is derived from the provider key, not the Anthropic session ID.
- **Request binding**: `_bind_request_session` maps `request_id` to `session_key` in `_request_session_keys`, so subsequent events for the same request (streaming deltas, response complete) route to the correct session tab.

### Active Session Tracking

The active session is determined by the currently selected tab:

- `_active_session_key_from_tabs()` inspects the tab widget's `active` attribute and reverse-maps it through `_session_tab_ids` to find the corresponding session key.
- `_active_session_key` and `_last_primary_session_key` track the current and previous active session keys.
- `_active_context_session_key()` resolves the canonical context key for the active tab.

### Session Panel Integration

The session panel shows different information based on the active tab:

- When the active tab is `__default__`, the panel shows `app._session_id` (the most recently seen Anthropic session ID).
- When a non-default tab is active, the panel shows that tab's session key and its per-session last message time.

Per-session activity times are tracked in `app_state["last_message_time_by_session"]`.

### Limitations

While per-session tab creation and data routing are implemented, some cross-session features remain incomplete:

- Session tab titles use a basic naming scheme (provider tab title for provider-keyed sessions, session ID prefix for Anthropic sessions).
- There is no UI for closing or rearranging session tabs.
- The `_session_id` on the app tracks only the default provider's most recent session; non-default provider sessions do not update this field.

## Tmux Integration

### Why Tmux

cc-dump is a TUI that occupies the terminal. Users need Claude Code running in a *separate* terminal to generate traffic. Without tmux integration, the user must manually: (1) note the proxy port, (2) open another terminal, (3) set `ANTHROPIC_BASE_URL`, and (4) launch Claude Code. Tmux pane splitting automates all of this into a single keypress.

### Availability Detection

Tmux integration is available when both conditions are met:
- `$TMUX` environment variable is set (process is inside a tmux session).
- `libtmux` Python package is importable.

`is_available()` checks both conditions. When either is missing, the controller enters a disabled state and all launch/focus operations are no-ops.

### TmuxController State Machine

```
                    +--($TMUX unset)-----> NOT_IN_TMUX
                    |
init ---------------+---(no libtmux)----> NO_LIBTMUX
                    |
                    +---(pane discovery fail)-> NOT_IN_TMUX
                    |
                    '---(success)---> READY --(launch/adopt)--> TOOL_RUNNING
                                       ^                            |
                                       '----(pane dies)-------------'
```

States (defined as `TmuxState` enum):
- **NOT_IN_TMUX**: Not running inside tmux, or pane discovery failed. Init can reach this state via multiple paths: `$TMUX` not set, `$TMUX_PANE` not set, pane not found in any session/window, or any exception during init.
- **NO_LIBTMUX**: Inside tmux but `libtmux` not importable.
- **READY**: Tmux available, no tool pane currently tracked. Launch is possible.
- **TOOL_RUNNING**: A tool pane has been launched or adopted. Focus/switch operations are available.

### Pane Management

**Our pane**: Identified at init by `$TMUX_PANE` environment variable. The controller iterates all sessions/windows/panes on the tmux server to find the matching `pane_id`.

**Tool pane**: The pane where the launched tool (Claude Code, Copilot, etc.) runs. Managed through these operations:

- **Launch** (`launch_tool`): Splits the current window below (`PaneDirection.Below`), runs the assembled command with configured environment variables prefixed as `KEY=VALUE` pairs, selects the new pane. Transitions to `TOOL_RUNNING`.
- **Adopt** (`_try_adopt_existing`): On init and before launches, `_find_tool_pane` scans sibling panes (same window, excluding our pane) for a process matching configured `_process_names` via `pane_current_command`. If found, adopts it as the tool pane without launching.
- **Focus** (`focus_tool` / `focus_self`): Switches tmux selection between cc-dump pane and tool pane using `pane.select()`.

**Pane liveness**: `_validate_tool_pane()` is the single enforcement point for checking whether the tool pane is still alive. It calls `self._tool_pane.refresh()` (libtmux fetches fresh state from tmux server). On failure (any exception), it clears the reference and transitions back to `READY`.

**Exit monitoring**: After launch, `_monitor_exit()` sets `pane_alive` Observable to `True`, then starts a background thread via `watch(_poll)` that polls `_validate_tool_pane()` every 2 seconds. When the pane dies, `pane_alive` is set to `False`, which reactive consumers can observe.

### LaunchResult Model

Every `launch_tool` call returns a `LaunchResult` with:
- `action`: `LAUNCHED` (new pane split), `FOCUSED` (existing pane selected), or `BLOCKED` (precondition failed).
- `detail`: Human-readable explanation.
- `success`: Boolean.
- `command`: The shell command string (when launched).

All preconditions are evaluated unconditionally before deriving the action. The decision flow:
1. State must be `READY` or `TOOL_RUNNING`.
2. If pane validation fails, attempt adoption (`_try_adopt_existing`).
3. If an existing tool pane is alive (or adopted), action = `FOCUSED` (re-select it).
4. If no launch environment is configured (`_launch_env` is empty), action = `BLOCKED`.
5. Otherwise, action = `LAUNCHED` (split and run).

### Log Tail

`open_log_tail(log_file)` opens a `tail -f` pane for the runtime log file. Routing policy:
1. **cc-dump alone in window** (1 pane): Split below (`PaneDirection.Below`).
2. **cc-dump + tool pane only** (2 panes, tool pane alive): Split the tool pane in the opposite orientation from the existing split. Direction is derived from pane coordinates: if panes share `pane_left` but differ in `pane_top`, they're stacked vertically, so split right; otherwise split below.
3. **Any other layout** (3+ panes, or 2 panes without tool): Create a new tmux window named `cc-dump-logs` via `session.cmd("new-window", ...)`.

Returns a `LogTailResult` with analogous structure to `LaunchResult`. Possible actions: `SPLIT_BELOW`, `SPLIT_RIGHT`, `NEW_WINDOW`, `BLOCKED`.

### Cleanup

`cleanup()` is called on app shutdown. It intentionally does *nothing* -- it does not kill the launched tool pane. The user's Claude Code session continues running independently.

### Event Subscription

`TmuxController.on_event()` accepts `PipelineEvent` but is a no-op. The docstring notes "Zoom behavior was intentionally removed; tmux zoom is user-driven."

## Launch Configurations

### Why Launch Configs

Different users have different workflows. Some want to launch Claude Code with `--dangerously-bypass-permissions`. Some use custom model flags. Some need a shell wrapper to source their `.zshrc` first. Launch configs make these repeatable without re-typing flags.

### LaunchConfig Data Model

```python
@dataclass
class LaunchConfig:
    name: str          # Display name, unique within config list (e.g., "claude", "haiku")
    launcher: str      # Launcher key (e.g., "claude", "copilot")
    command: str       # Executable command override; empty = launcher default
    model: str         # Model flag value (e.g., "haiku"); empty = no --model flag
    shell: str         # Shell wrapper: "", "bash", or "zsh" (validated against SHELL_OPTIONS)
    options: dict      # Typed option values (see option definitions below)
```

`resolved_command` property returns `config.command` if non-empty, otherwise the launcher spec's `default_command`.

### Launcher Registry

The launcher registry (`launcher_registry.py`) defines supported CLI tools with their metadata via `LauncherSpec`:

| Key | Display Name | Default Command | Process Names | Provider Key | Supports --model | Supports --resume |
|-----|-------------|-----------------|---------------|--------------|------------------|-------------------|
| `claude` | Claude | `claude` | `("claude", "clod")` | `"anthropic"` (the value of `DEFAULT_PROVIDER_KEY`) | Yes | Yes |
| `copilot` | Copilot | `copilot` | `("copilot", "github-copilot-cli")` | `"copilot"` | No | No |

`process_names` are used for pane adoption: when `TmuxController._find_tool_pane` scans sibling panes, it checks `os.path.basename(pane_current_command)` against these names.

The default launcher is `"claude"` (`DEFAULT_LAUNCHER_KEY`). `normalize_launcher_key(value)` normalizes to lowercase and falls back to the default for unknown keys.

### Launch Options

Options are defined declaratively per launcher. Each option has a schema (`LaunchOptionDef`) specifying:
- `key`, `label`, `description`: Identity and display.
- `kind`: `"text"` or `"bool"`.
- `default`: Default value.
- `cli_mode`: How it maps to CLI arguments:
  - `"raw"`: Value is appended directly (for `extra_args`).
  - `"flag"`: Boolean -- when true, emits `cli_flag` (e.g., `--dangerously-bypass-permissions`).
  - `"resume"`: Boolean -- when true AND a `session_id` is available AND the launcher supports resume, emits `cli_flag session_id` (e.g., `--resume <uuid>`).

**Common options** (all launchers):
| Key | Label | Kind | Default | CLI Mode |
|-----|-------|------|---------|----------|
| `extra_args` | Extra Args | text | `""` | raw |

**Claude-specific options**:
| Key | Label | Kind | Default | CLI Mode | CLI Flag |
|-----|-------|------|---------|----------|----------|
| `auto_resume` | Auto Resume | bool | `True` | resume | `--resume` |
| `bypass` | Bypass Permissions | bool | `False` | flag | `--dangerously-bypass-permissions` |
| `continue` | Continue | bool | `False` | flag | `--continue` |

**Copilot-specific options**:
| Key | Label | Kind | Default | CLI Mode | CLI Flag |
|-----|-------|------|---------|----------|----------|
| `yolo` | YOLO | bool | `False` | flag | `--yolo` |

### Command Assembly

`build_full_command(config, session_id)` is the single place where the complete command string is assembled:

1. Resolve the base command (`config.resolved_command`).
2. Append `--model <model>` if model is set and launcher supports it (`spec.supports_model_flag`).
3. Collect option-derived CLI args in launcher option schema order via `_collect_option_args`.
4. Join into a single command string: `" ".join([resolved_command, *args])`.
5. If `shell` is set (e.g., `"zsh"`), wrap via `_wrap_with_shell`: `zsh -c <shlex-quoted 'source ~/.zshrc; <command> <args>'>`.

### Launch Profile

`build_launch_profile(config, provider_endpoints, session_id)` produces a `LaunchProfile` -- the runtime-ready launch descriptor:

```python
@dataclass(frozen=True)
class LaunchProfile:
    launcher_key: str              # e.g., "claude"
    launcher_label: str            # e.g., "Claude"
    command: str                   # Fully assembled command string
    process_names: tuple[str, ...]  # For pane adoption matching
    environment: dict[str, str]    # Proxy env vars (e.g., ANTHROPIC_BASE_URL)
```

`process_names` are derived by `_derive_process_names`: basename of the resolved command + launcher spec's `process_names`, deduplicated preserving order.

The environment dict is built by `build_proxy_env(spec, provider_endpoints)` which delegates to `providers.build_provider_proxy_env(endpoint)` for the launcher's `provider_key`.

### Persistence

Launch configs are persisted in `~/.config/cc-dump/settings.json` (via `cc_dump.io.settings`) under the `launch_configs` key (list of config dicts) and `active_launch_config` key (string name of the active config).

On load (`load_configs()`), configs go through normalization:
1. Deserialize from settings.
2. Deduplicate names via `_dedupe_config_names` (append `-2`, `-3`, etc. for collisions).
3. Ensure default configs exist for all registered launchers via `_ensure_default_tool_configs`.
4. Re-deduplicate after adding defaults.

If no configs exist in settings (or the list is empty), `default_configs()` creates one default config per registered launcher.

`save_configs(configs)` normalizes and persists, returning the post-normalization list so callers can reconcile names.

`get_active_config()` loads all configs, loads the active name, and looks up by name (falling back to the first config).

### Transient Config for Extra Args

`config_with_extra_args(config, extra_args)` creates a copy with CLI extra args merged into the `extra_args` option using `dataclasses.replace`. The returned config is transient and never persisted.

### Session ID for Auto-Resume

When launching with `auto_resume` enabled (the default for Claude), the session ID is resolved from the app's active context via `_active_resume_session_id()`:

1. Check the active tab's context key via `_active_context_session_key()`. If the active tab is a non-default session, use that session's key as the resume ID.
2. Otherwise, fall back to `app._session_id` -- the most recently seen session ID from the default provider.

This session ID is passed to `build_full_command`, which emits `--resume <session_id>` in the final command. This means re-launching Claude Code from cc-dump automatically resumes the conversation it was monitoring.

### Launch Orchestration

`settings_launch_controller.launch_with_config(app, config)` is the entry point for all launch operations (both manual and auto-launch). It:

1. Resolves the session ID for auto-resume via `_resume_session_id(app, config)`.
2. Builds the `LaunchProfile` from the config, provider endpoints, and session ID.
3. Calls `tmux.configure_launcher()` with the profile's command, process names, environment, and label.
4. Calls `tmux.launch_tool(command=profile.command)` and notifies the user of the result.
5. Updates the view store with `launch:active_name` and `launch:active_tool`.

If tmux is unavailable, a "Tmux not available" warning notification is shown.

### Launch Config Panel

The `LaunchConfigPanel` (in `tui/launch_config_panel.py`) is a docked side panel for managing launch configurations. It supports:

- **Preset selector**: A dropdown listing all saved configs by name.
- **Base fields**: Name, Tool (launcher), Command, Model, Shell -- rendered as text inputs or select widgets.
- **Tool options**: Dynamically shown/hidden per-launcher. Common options (like `extra_args`) are always visible; launcher-specific options (like Claude's `auto_resume`, `bypass`, `continue`, or Copilot's `yolo`) appear only when the corresponding launcher is selected.
- **Actions**: New, Delete, Activate, Launch, Save, Close -- implemented as `Chip` widgets.

The panel posts messages (`Saved`, `Cancelled`, `QuickLaunch`, `Activated`) for the app to handle. Form state is local to the panel (deep-copied on init) and only persisted when the user explicitly saves.

Panel visibility is controlled by `view_store["panel:launch_config"]`, toggled by `settings_launch_controller.open_launch_config()` / `close_launch_config()`. Opening the launch config panel closes the settings panel and vice versa.

## The `run` Subcommand

### Purpose

`cc-dump run <config-name>` combines starting the proxy and launching a tool into one command. Without it, the user starts cc-dump, waits for it to bind a port, then presses `c` to launch. The `run` subcommand eliminates that second step.

### Syntax

```
cc-dump run <config-name> [cc-dump-flags...] [-- tool-extra-args...]
```

- `<config-name>`: Required. Must match a saved launch config name (e.g., `claude`, `copilot`, `haiku`).
- `cc-dump-flags`: Optional. Standard cc-dump flags like `--port 5000` placed before `--`.
- `tool-extra-args`: Optional. Arguments after `--` are merged into the config's `extra_args` option for this launch only (not persisted).

### Examples

```bash
cc-dump run claude                                    # Launch with default claude config
cc-dump run claude --port 5000                        # Fixed port + auto-launch
cc-dump run claude -- --dangerously-bypass-permissions # Append tool flags
cc-dump run haiku --port 5000 -- --continue           # Custom config + port + tool flags
```

### Execution Flow

1. **Argv parsing**: `_detect_run_subcommand` splits `sys.argv[1:]` into `(config_name, cc_dump_flags, tool_extra_args)`. If `argv[0]` is not `"run"`, returns `(None, original_argv, [])` -- normal mode. Separator is `--`. If the first argument after `run` is `-h` or `--help`, a usage message is printed and the process exits with code 0.
2. **Config validation**: `_resolve_auto_launch_config_name` loads saved configs and verifies the name exists. On mismatch, prints available configs to stderr and exits with code 2.
3. **Normal startup**: cc-dump boots normally with `cc_dump_flags` as the argument list (proxy starts, TUI launches).
4. **Auto-launch on mount**: In `CcDumpApp.on_mount`, `_execute_auto_launch` fires. It looks up the config by name, merges `tool_extra_args` into the config's `extra_args` option (creating a transient config via `config_with_extra_args` that is never persisted), and calls `launch_with_config` (in `settings_launch_controller`).
5. **Launch via tmux**: The standard launch path runs -- `build_launch_profile`, `tmux.configure_launcher`, `tmux.launch_tool`.

### Error Handling

- Unknown config name: Exits immediately (before TUI starts) with error message listing available configs and exit code 2.
- Config found but tmux unavailable: TUI starts, auto-launch fires, user sees a "Tmux not available" notification in the UI.
- Config found but launch fails: TUI starts, user sees a "Launch failed: ..." notification.
- Config found but name resolves to None at mount time (race with settings change): Error notification with available config names and timeout of 10 seconds.

## Recordings and Session Storage

### Recording Directory

HAR recordings are stored in `~/.local/share/cc-dump/recordings/` (`get_recordings_dir()`) as flat `.har` files.

Filename format: `ccdump-<provider>-<YYYYMMDD>-<HHMMSS>Z-<8-char-hash>.har`

The hash is derived from `SHA1(provider:timestamp:pid:uuid4)[:8]` to avoid collisions.

### Recording Management

- **List**: `list_recordings()` scans the recordings directory for `.har` files (sorted by path), parses metadata from each. `RecordingInfo` contains: `path`, `filename`, `provider` (from filename or first HAR entry), `created` (from first entry's `startedDateTime` or file mtime), `entry_count`, `size_bytes`. Malformed files are logged and skipped.
- **Latest**: `get_latest_recording()` sorts recordings by `created` timestamp and returns the path of the newest.
- **Cleanup**: `cleanup_recordings(keep=20, dry_run=False)` sorts by creation time descending, keeps the newest N, deletes the rest. Returns a `CleanupResult` with `kept`, `removed`, `bytes_freed`, `removed_paths`, `dry_run` fields.
- **Size formatting**: `format_size(size_bytes)` formats with B/KB/MB/GB suffixes.

### Provider Detection

Provider identity for a recording is determined by:
1. Filename parsing: extract the provider segment from `ccdump-<provider>-...` (second hyphen-delimited field, splitting on `-` with limit 4) and validate against the canonical provider registry (`_provider_keys()`).
2. Fallback: inspect the first HAR entry via `providers.detect_provider_from_har_entry`.

### Resume and Continue Modes

- `--resume [path]`: Loads and replays the specified HAR file. If the value is `"latest"`, resolves to the most recent recording. The replayed data appears as historical turns in the TUI, then continues in live proxy mode.
- `--continue`: Equivalent to `--resume latest`. Loads the most recent recording and continues live.

On shutdown, cc-dump logs a resume command via `logger.info`: `<argv[0]> --port <port> --resume <recording-path>`. The resume path is the current session's recording if it exists, falling back to the replay path if the session was started from a replay. SIGINT is masked during this log line to prevent Ctrl+C from suppressing it.
