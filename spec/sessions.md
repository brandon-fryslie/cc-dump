# Sessions, Tmux Integration, and Launch Configurations

> Status: draft
> Last verified against: not yet

## Overview

Claude Code sessions are ephemeral and invisible. When a user runs `claude`, a session ID is assigned server-side and embedded in API metadata, but the user never sees it. If Claude Code crashes or the user quits, there is no built-in way to resume where they left off, and no way to know which session produced which traffic. cc-dump solves this by extracting session identity from intercepted API traffic, displaying connection status, and enabling one-click launch and resume of Claude Code sessions through tmux pane management.

From the user's perspective, sessions tie together three things: (1) knowing *which* Claude Code conversation is producing the traffic they see, (2) being able to *launch* Claude Code with the right proxy configuration without manual environment variable setup, and (3) being able to *resume* a previous session by passing the session ID back to Claude Code's `--resume` flag. The tmux integration and launch configuration system exist to make this seamless rather than requiring the user to juggle terminal windows, ports, and environment variables by hand.

## Session Identity

### Source of Truth

Session identity is extracted from the Anthropic API's `metadata.user_id` field in each request body. The field has the compound format:

```
user_<hash>_account_<uuid>_session_<uuid>
```

Parsing extracts three components: `user_hash`, `account_id`, and `session_id`. The `session_id` (a UUID) is the canonical session identifier used throughout cc-dump.

### Where Session ID Appears

- **FormattedBlock.session_id**: Every block in the IR carries the `session_id` (string) of the request that produced it. Set during `format_request_for_provider` after all blocks are constructed.
- **ProviderRuntimeState.current_session**: Per-provider mutable state tracking the most recently seen session ID. Used to detect session transitions.
- **NewSessionBlock**: Emitted into the block stream whenever `session_id` differs from `ProviderRuntimeState.current_session`. Carries the new `session_id` string.
- **DomainStore._session_boundaries**: A list of `(session_id, turn_index)` pairs recording where each `NewSessionBlock` appeared in the completed turns list. Used for within-tab session navigation.
- **SessionPanel**: Displays the current session ID and connection status in the UI panel strip. Connection is considered active when the last message was received within 120 seconds.
- **StreamRegistry.RequestStreamContext**: Each active request stream records the `session_id` extracted from the request body.

### Session Transition Detection

Session transitions are detected at a single enforcement point: `format_request_for_provider`. The sequence is:

1. Request body arrives; `session_id` is parsed from `metadata.user_id`.
2. If `session_id` is non-empty and differs from `ProviderRuntimeState.current_session`, a `NewSessionBlock(session_id=...)` is prepended to the block list for that request.
3. *After* formatting completes, `_update_session_id` writes the new session ID into `ProviderRuntimeState.current_session`.

The ordering matters: the formatter reads the *old* `current_session` to decide whether to emit `NewSessionBlock`, then the state is updated. This ensures the transition block appears exactly once at the boundary.

### DomainStore Streaming State

`DomainStore` manages streaming state for in-progress turns:

- **`stream_turns`**: Maps request_id to the list of `FormattedBlock` instances being accumulated for the current streaming turn.
- **`stream_delta_buffers`**: Maps request_id to delta accumulation buffers for `TextDeltaBlock` content.
- **`finalize_stream(request_id)`**: Called when a streaming turn completes. Consolidation logic converts `TextDeltaBlock` instances into a single `TextContentBlock` with the accumulated text, wraps the block list in a `MessageBlock`, and adds the completed turn via `add_turn()`.

### Completed Turn Retention

`DomainStore` enforces a maximum number of completed turns via `_max_completed_turns` (default 5000, configurable via `CC_DUMP_MAX_COMPLETED_TURNS` environment variable). When the limit is exceeded, the oldest turns are pruned and session boundary indices are adjusted accordingly.

### Session Boundaries in DomainStore

When `DomainStore.add_turn` receives a block list containing a `NewSessionBlock`, it records `(session_id, turn_index)` in `_session_boundaries`. These boundaries:

- Survive hot-reload (DomainStore persists on the app object).
- Are adjusted when completed-turn retention pruning removes old turns (indices shift down by the overflow count).
- Are exposed via `get_session_boundaries()` for navigation features.

### Connection Status

The `SessionPanel` derives "connected" status from `last_message_time`:
- **Connected**: `last_message_time` is not None AND `(monotonic_now - last_message_time) < 120 seconds`.
- **Disconnected**: Otherwise.

A 1-second interval timer re-evaluates this condition, so the panel transitions to "disconnected" automatically after 120 seconds of silence.

## Multi-Session Model

### Current State: Single Active Session

At present, cc-dump runs with a single `DomainStore` and a single `ConversationView`. All API traffic from all providers feeds into one stream. Session transitions within that stream are marked by `NewSessionBlock` boundaries, but there is no per-session isolation of block data.

The `_session_id` on the app tracks the most recently seen session ID (from the default provider). This is used for the auto-resume feature when launching Claude Code.

### Proposed Future: Multi-Session Isolation

A multi-session architecture has been designed (see `docs/multi-session-architecture.md`) but is not yet implemented. The key planned concepts:

- **Session key format**: `{source}:{session_id}` where source is `live` or `replay`.
- **SessionRuntime aggregate**: Per-session `DomainStore` + `StreamRegistry` + view state.
- **Session switcher UI**: Tab/chip strip above `ConversationView` for switching between sessions.
- **Side-channel lanes**: Separate `live:side-channel:<source-session-id>` keys for sub-agent traffic.

[UNVERIFIED] The multi-session architecture document appears to be a proposal. No `SessionRuntime` class or session registry exists in current source code. The app currently has early scaffolding for multiple conversation tabs (`TabbedContent` with a main "Claude" tab and a `_session_conv_ids` mapping) but full per-session isolation is not implemented.

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
                    ┌──($TMUX unset)──► NOT_IN_TMUX
                    │
init ───────────────┼──(no libtmux)──► NO_LIBTMUX
                    │
                    ├──(pane discovery fail)──► NOT_IN_TMUX
                    │
                    └──(success)──► READY ──(launch/adopt)──► TOOL_RUNNING
                                      ▲                            │
                                      └───(pane dies)─────────────┘
```

States:
- **NOT_IN_TMUX**: Not running inside tmux, or pane discovery failed. Init can reach this state via multiple paths: `$TMUX` not set, or tmux pane discovery failure.
- **NO_LIBTMUX**: Inside tmux but `libtmux` not installed.
- **READY**: Tmux available, no tool pane currently tracked. Launch is possible.
- **TOOL_RUNNING**: A tool pane has been launched or adopted. Focus/switch operations are available.

### Pane Management

**Our pane**: Identified at init by `$TMUX_PANE` environment variable. The controller scans all sessions/windows/panes to find the matching `pane_id`.

**Tool pane**: The pane where the launched tool (Claude Code, Copilot, etc.) runs. Managed through these operations:

- **Launch** (`launch_tool`): Splits the current window below, runs the assembled command with configured environment variables, selects the new pane. Transitions to `TOOL_RUNNING`.
- **Adopt** (`_try_adopt_existing`): On init and before launches, scans sibling panes for a process matching configured `process_names`. If found, adopts it as the tool pane without launching.
- **Focus** (`focus_tool` / `focus_self`): Switches tmux selection between cc-dump pane and tool pane.

**Pane liveness**: `_validate_tool_pane()` is the single enforcement point for checking whether the tool pane is still alive. It calls `libtmux.Pane.refresh()`. On failure, it clears the reference and transitions back to `READY`.

**Exit monitoring**: After launch, a background thread polls `_validate_tool_pane()` every 2 seconds. When the pane dies, the `pane_alive` Observable is set to `False`, which reactive consumers can observe.

### LaunchResult Model

Every `launch_tool` call returns a `LaunchResult` with:
- `action`: `LAUNCHED` (new pane split), `FOCUSED` (existing pane selected), or `BLOCKED` (precondition failed).
- `detail`: Human-readable explanation.
- `success`: Boolean.
- `command`: The shell command string (when launched).

All preconditions are evaluated unconditionally before deriving the action. The decision flow:
1. State must be READY or TOOL_RUNNING.
2. If an existing tool pane is alive, action = FOCUSED (re-select it).
3. If no launch environment is configured, action = BLOCKED.
4. Otherwise, action = LAUNCHED (split and run).

### Log Tail

`open_log_tail(log_file)` opens a `tail -f` pane for the runtime log file. Routing policy:
1. **cc-dump alone in window**: Split below (horizontal).
2. **cc-dump + tool pane only**: Split the tool pane in the opposite orientation from the existing split (if they're stacked vertically, split right; if side-by-side, split below).
3. **Any other layout** (3+ panes): Create a new tmux window named `cc-dump-logs`.

Returns a `LogTailResult` with analogous structure to `LaunchResult`.

### Cleanup

`cleanup()` is called on app shutdown. It intentionally does *not* kill the launched tool pane. The user's Claude Code session continues running independently.

## Launch Configurations

### Why Launch Configs

Different users have different workflows. Some want to launch Claude Code with `--dangerously-bypass-permissions`. Some use custom model flags. Some need a shell wrapper to source their `.zshrc` first. Launch configs make these repeatable without re-typing flags.

### LaunchConfig Data Model

```
LaunchConfig:
  name: str          # Display name, unique within config list (e.g., "claude", "haiku")
  launcher: str      # Launcher key (e.g., "claude", "copilot")
  command: str       # Executable command override; empty = launcher default
  model: str         # Model flag value (e.g., "haiku"); empty = no --model flag
  shell: str         # Shell wrapper: "", "bash", or "zsh"
  options: dict      # Typed option values (see option definitions below)
```

### Launcher Registry

The launcher registry defines supported CLI tools with their metadata:

| Key | Display Name | Default Command | Process Names | Supports --model | Supports --resume |
|-----|-------------|-----------------|---------------|------------------|-------------------|
| `claude` | Claude | `claude` | `claude`, `clod` | Yes | Yes |
| `copilot` | Copilot | `copilot` | `copilot`, `github-copilot-cli` | No | No |

`process_names` are used for pane adoption: when TmuxController scans sibling panes, it checks `pane_current_command` against these names.

The default launcher is `claude`.

### Launch Options

Options are defined declaratively per launcher. Each option has a schema (`LaunchOptionDef`) specifying:
- `key`, `label`, `description`: Identity and display.
- `kind`: `"text"` or `"bool"`.
- `default`: Default value.
- `cli_mode`: How it maps to CLI arguments:
  - `"raw"`: Value is appended directly (for `extra_args`).
  - `"flag"`: Boolean — when true, emits `cli_flag` (e.g., `--dangerously-bypass-permissions`).
  - `"resume"`: Boolean — when true AND a session_id is available AND the launcher supports resume, emits `cli_flag session_id` (e.g., `--resume <uuid>`).

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

1. Resolve the base command (`config.command` or launcher default).
2. Append `--model <model>` if model is set and launcher supports it.
3. Append option-derived CLI args in schema order.
4. If `shell` is set (e.g., `"zsh"`), wrap the entire command using `shlex.quote` for proper shell quoting: `zsh -c <shlex-quoted 'source ~/.zshrc; <command> <args>'>`.

### Launch Profile

`build_launch_profile(config, provider_endpoints, session_id)` produces a `LaunchProfile` — the runtime-ready launch descriptor:

```
LaunchProfile:
  launcher_key: str              # e.g., "claude"
  launcher_label: str            # e.g., "Claude"
  command: str                   # Fully assembled command string
  process_names: tuple[str, ...] # For pane adoption matching
  environment: dict[str, str]    # Proxy env vars (e.g., ANTHROPIC_BASE_URL)
```

The environment dict is built from `provider_endpoints` — it maps the launcher's provider to the proxy URL so launched tools route traffic through cc-dump.

### Persistence

Launch configs are persisted in `~/.config/cc-dump/settings.json` under the `launch_configs` key (list of config dicts) and `active_launch_config` key (string name of the active config).

On load, configs go through normalization:
1. Deserialize from settings.
2. Deduplicate names (append `-2`, `-3`, etc. for collisions).
3. Ensure default configs exist for all registered launchers.
4. Re-deduplicate after adding defaults.

If no configs exist in settings, `default_configs()` creates one default config per registered launcher.

### Session ID for Auto-Resume

When launching with `auto_resume` enabled (the default for Claude), the session ID is resolved from the app's active context:

1. Check if a non-default session tab is active; if so, use that session's key.
2. Otherwise, fall back to the most recently seen `_session_id` from the default provider.

This session ID is passed to `build_full_command`, which emits `--resume <session_id>` in the final command. This means re-launching Claude Code from cc-dump automatically resumes the conversation it was monitoring.

## The `run` Subcommand

### Purpose

`cc-dump run <config-name>` combines starting the proxy and launching a tool into one command. Without it, the user starts cc-dump, waits for it to bind a port, then presses `c` to launch. The `run` subcommand eliminates that second step.

### Syntax

```
cc-dump run <config-name> [cc-dump-flags...] [-- tool-extra-args...]
```

- `<config-name>`: Required. Must match a saved launch config name (e.g., `claude`, `copilot`, `haiku`).
- `cc-dump-flags`: Optional. Standard cc-dump flags like `--port 5000` placed before `--`.
- `tool-extra-args`: Optional. Arguments after `--` are appended to the config's `extra_args` option for this launch only (not persisted).

### Examples

```bash
cc-dump run claude                                    # Launch with default claude config
cc-dump run claude --port 5000                        # Fixed port + auto-launch
cc-dump run claude -- --dangerously-bypass-permissions # Append tool flags
cc-dump run haiku --port 5000 -- --continue           # Custom config + port + tool flags
```

### Execution Flow

1. **Argv parsing**: `_detect_run_subcommand` splits `sys.argv[1:]` into `(config_name, cc_dump_flags, tool_extra_args)`. If `argv[0]` is not `"run"`, returns `(None, original_argv, [])` — normal mode.
2. **Config validation**: `_resolve_auto_launch_config_name` loads saved configs and verifies the name exists. On mismatch, prints available configs to stderr and exits with code 2.
3. **Normal startup**: cc-dump boots normally with `cc_dump_flags` as the argument list (proxy starts, TUI launches).
4. **Auto-launch on mount**: In `CcDumpApp.on_mount`, `_execute_auto_launch` fires. It looks up the config by name, merges `tool_extra_args` into the config's `extra_args` option (creating a transient config that is never persisted), and calls `_launch_with_config`.
5. **Launch via tmux**: The standard launch path runs — `build_launch_profile`, `tmux.configure_launcher`, `tmux.launch_tool`.

### Error Handling

- Unknown config name: Exits immediately (before TUI starts) with error message listing available configs and exit code 2.
- Config found but tmux unavailable: TUI starts, auto-launch fires, user sees a "Tmux not available" notification in the UI.
- Config found but launch fails: TUI starts, user sees a "Launch failed: ..." notification.

## Recordings and Session Storage

### Recording Directory

HAR recordings are stored in `~/.local/share/cc-dump/recordings/` as flat `.har` files.

Filename format: `ccdump-<provider>-<YYYYMMDD>-<HHMMSS>Z-<8-char-hash>.har`

The hash is derived from `SHA1(provider:timestamp:pid:uuid4)[:8]` to avoid collisions.

### Recording Management

- **List**: `list_recordings()` scans the recordings directory for `.har` files, parses metadata from each (provider from filename or first HAR entry, creation time from first entry's `startedDateTime` or file mtime, entry count).
- **Latest**: `get_latest_recording()` returns the path to the most recently created recording.
- **Cleanup**: `cleanup_recordings(keep=20, dry_run=False)` sorts by creation time and deletes all but the newest N. Returns a `CleanupResult` with counts and paths.

### Provider Detection

Provider identity for a recording is determined by:
1. Filename parsing: extract the provider segment from `ccdump-<provider>-...` and validate against the canonical provider registry.
2. Fallback: inspect the first HAR entry and use `detect_provider_from_har_entry`.

### Resume and Continue Modes

- `--resume [path]`: Loads and replays the specified HAR file (or latest if no path), then continues in live proxy mode. The replayed data appears as historical turns in the TUI.
- `--continue`: Equivalent to `--resume latest`. Loads the most recent recording and continues live.

On shutdown, cc-dump prints a resume command: `cc-dump --port <port> --resume <recording-path>` so the user can restart where they left off.
