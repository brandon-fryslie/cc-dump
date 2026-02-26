# cc-dump

Transparent HTTP proxy for monitoring Claude Code API traffic. Intercepts requests to the Anthropic API, tracks system prompt changes with diffs, and provides a real-time Textual TUI with HAR recording/replay capabilities.

## Install

```bash
uv tool install -e .
```

Requires Python 3.10+. Production dependencies: [Textual](https://github.com/Textualize/textual), [textual-serve](https://github.com/Textualize/textual-serve), tiktoken.

**Optional:** For tmux integration (split-pane Claude launching, auto-zoom):

```bash
uv tool install -e ".[tmux]"  # adds libtmux
```

## Quick Start

```bash
# Terminal 1: start cc-dump
cc-dump
# prints: Listening on: http://127.0.0.1:<PORT>

# Terminal 2: point Claude Code at cc-dump
ANTHROPIC_BASE_URL=http://127.0.0.1:<PORT> claude
```

All API traffic now flows through cc-dump and is displayed in the TUI.

## Usage Modes

### Terminal — Reverse Proxy (default)

cc-dump sits between Claude Code and the Anthropic API:

```bash
cc-dump [--port PORT] [--target URL]
# Port is OS-assigned by default; printed on startup
ANTHROPIC_BASE_URL=http://127.0.0.1:<PORT> claude
```

### Terminal — Forward Proxy

For dynamic targets (e.g., non-Anthropic APIs), pass an empty target:

```bash
cc-dump --target ""
# Port printed on startup
HTTP_PROXY=http://127.0.0.1:<PORT> ANTHROPIC_BASE_URL=http://api.minimax.com claude
```

Requests are sent as plain HTTP to cc-dump, inspected, then upgraded to HTTPS for the upstream API.

### Browser Mode

Run cc-dump in your browser via textual-serve:

```bash
cc-dump-serve          # visit http://localhost:8000
# or:
just web
```

Each browser tab runs an independent cc-dump instance.

### Recording and Replay

cc-dump automatically records all API traffic to HAR files:

```bash
# Normal operation — records to ~/.local/share/cc-dump/recordings/<session>/<provider>/
cc-dump

# Replay a previous session (proxy still runs for new traffic)
cc-dump --replay path/to/recording.har
cc-dump --replay latest

# Continue from most recent recording (replay + capture new traffic)
cc-dump --continue

# Disable recording
cc-dump --no-record

# Custom recording path base (provider subdirectories are still created)
cc-dump --record /path/to/output.har

# Organize recordings by session name
cc-dump --session my-project
```

HAR files are the source of truth for events. Replay mode loads previous data, then the proxy accepts new traffic on top.

## CLI Reference

| Option | Default | Description |
|--------|---------|-------------|
| `--host HOST` | `127.0.0.1` | Bind address |
| `--port PORT` | `0` (OS-assigned) | Listen port |
| `--target URL` | `https://api.anthropic.com` | Upstream API URL (empty string for forward proxy mode). Defaults to `ANTHROPIC_BASE_URL` env var if set |
| `--session NAME` | `unnamed-session` | Session name — recordings are organized into subdirectories by session |
| `--replay PATH` | — | Replay a HAR file (`latest` for most recent) |
| `--continue` | — | Continue from most recent recording (replay + live proxy) |
| `--record PATH` | auto | Custom HAR recording output path base (saved as `<provider>/<name>.har`) |
| `--no-record` | — | Disable HAR recording |
| `--seed-hue HUE` | `190` (cyan) | Base hue (0–360) for the color palette. Also settable via `CC_DUMP_SEED_HUE` env var |

## Features

### Real-Time Streaming Display

API responses stream into the TUI as they arrive. Request details (model, max_tokens, stream flag, tool count), message roles, and content summaries are displayed with tool correlation.

### System Prompt Tracking

System prompts are content-addressed and assigned color-coded tracking tags (`[sp-1]`, `[sp-2]`, etc.). When a tracked prompt changes between requests, unified diffs are shown inline.

### 3-Level Visibility System

Every content category has three visibility levels, cycled with number keys:

| Level | Symbol | Meaning |
|-------|--------|---------|
| EXISTENCE | `·` | Minimal (1 line) — content exists but details hidden |
| SUMMARY | `◐` | Compact (3–12 lines) — meaningful preview |
| FULL | `●` | Complete — all content visible |

Seven categories: **user** (1), **assistant** (2), **tools** (3), **system** (4), **budget** (5), **metadata** (6), **headers** (7).

**Click to expand/collapse:** Click any block with `▶`/`▼` to toggle it within the current level. Blocks that exceed their line limit show these indicators.

See [docs/VISIBILITY_SYSTEM.md](docs/VISIBILITY_SYSTEM.md) for detailed documentation.

### Tool Correlation and Summaries

Tool use/result pairs are correlated by ID. At tools level SUMMARY or below, consecutive tool runs are collapsed into a single `ToolUseSummaryBlock` showing per-tool counts.

### Token and Cost Analysis

**Cost panel** (`.` to cycle) — Per-tool token usage aggregates. Press `,` to toggle between aggregate and per-model breakdown views.

**Timeline panel** (`.` to cycle) — Context growth visualization across requests.

**Budget blocks** — Per-turn token accounting: input, output, cache creation, cache read tokens, and cost estimates.

### Search

Vim-style `/` search with incremental matching:

| Key | Action |
|-----|--------|
| `/` | Open search bar |
| `Enter` | Commit search, go to first match |
| `n` / `N` | Next / previous match |
| `Esc` | Close search, keep current filters |
| `q` | Cancel search, restore original filters |

**Mode toggles** (during editing, via `Alt+key`):
- `Alt+c` — Case sensitivity (default: insensitive)
- `Alt+w` — Word boundary matching
- `Alt+r` — Regex mode (default: on)
- `Alt+i` — Incremental search (default: on)

Search automatically raises category visibility to FULL and expands blocks containing matches.

### Content Rendering

Text content is rendered using Rich:
- **Markdown** — Prose is rendered as formatted Markdown
- **Code blocks** — Syntax-highlighted with language detection
- **XML blocks** — Detected and rendered with collapsible tag structure (click `▷`/`▽` to toggle)

### HAR Recording and Replay

All API traffic is recorded in HAR 1.2 format. Recordings are organized by session and provider under `~/.local/share/cc-dump/recordings/<session>/<provider>/`. Replay feeds saved data through the same rendering pipeline as live traffic.

### Tmux Integration

When running inside tmux with `libtmux` installed:

- `c` — Launch Claude Code in a split pane (auto-configures `ANTHROPIC_BASE_URL`). If already running, focuses the Claude pane
- `z` — Manual zoom toggle (cc-dump pane ↔ full screen)
- `Z` — Toggle auto-zoom: automatically zooms cc-dump when API requests arrive, unzooms when the turn completes

### Filterset Presets

Save and recall visibility configurations:

- `F1`–`F9` — Apply a filterset preset (F3 reserved)
- `Shift+F1`–`Shift+F9` — Save current visibility state to a slot
- `=` / `-` — Cycle forward/backward through presets

**Built-in defaults:**

| Slot | Name | Shows |
|------|------|-------|
| F1 | Conversation | User + assistant at full |
| F2 | Overview | Everything at summary |
| F4 | Tools | Tools at full, user/assistant at summary |
| F5 | System | System + metadata + headers at full |
| F6 | Cost | Budget + metadata at full |
| F7 | Full Debug | Everything at full |
| F8 | Assistant | Assistant only at full |
| F9 | Minimal | User + assistant + tools at summary |

User-saved filtersets override built-in defaults for the same slot.

### Theme Cycling

`[` / `]` cycle through Textual's built-in themes. The selected theme is persisted to settings.

### Info Panel

`i` toggles a panel showing server configuration: proxy URL, mode, target, session name, session ID, recording path, Python/Textual versions, PID. Click any row to copy its value to the clipboard.

### Logs Panel

`Ctrl+L` toggles a debug log panel with timestamped, color-coded messages (INFO, WARNING, ERROR).

### Conversation Export

Available via the command palette (`Ctrl+P` → "Dump conversation"). Exports the full conversation to a text file. On macOS, opens in `$VISUAL` if set.

### Command Palette

`Ctrl+P` opens Textual's command palette — a searchable list of all available actions (toggle panels, navigate, change themes, export, etc.).

### Economics Breakdown

`,` toggles the cost panel between aggregate view and per-model breakdown view, useful for multi-model sessions.

### Hot-Reload Development

File changes in the `cc_dump` package trigger automatic hot-reload of the rendering pipeline. The TUI re-renders without restart, preserving scroll position and conversation state.

## TUI Controls

### Category Visibility

| Key | Category | Default |
|-----|----------|---------|
| `1` | User | visible, full, expanded |
| `2` | Assistant | visible, full, expanded |
| `3` | Tools | visible, summary, collapsed |
| `4` | System | visible, summary, collapsed |
| `5` | Budget | hidden |
| `6` | Metadata | hidden |
| `7` | Headers | hidden |

Each press cycles: current → next visibility level.

**Shift+number** (`!@#$%^&`) or **Shift+letter** (`QWERTYU`) — Toggle the detail axis for the corresponding category.

**Lowercase letter** (`qwertyu`) — Toggle the expand axis for the corresponding category.

### Panels

| Key | Panel |
|-----|-------|
| `.` | Cycle panel (stats → economics → timeline) |
| `,` | Cycle panel mode (aggregate ↔ per-model breakdown) |
| `i` | Server info panel |
| `Ctrl+L` | Debug logs panel |

### Navigation

| Key | Action |
|-----|--------|
| `g` / `G` | Go to top / bottom |
| `j` / `k` | Scroll down / up one line |
| `h` / `l` | Scroll left / right one column |
| `Ctrl+D` / `Ctrl+U` | Half-page down / up |
| `Ctrl+F` / `Ctrl+B` | Full-page down / up |
| `0` | Toggle follow mode (auto-scroll to new content) |

### Search

| Key | Action |
|-----|--------|
| `/` | Start search |
| `Enter` | Commit and navigate |
| `n` / `N` | Next / previous match |
| `Esc` | Close search, keep filters |
| `q` | Cancel, restore original filters |
| `Alt+c/w/r/i` | Toggle case/word/regex/incremental |

### Filterset Presets

| Key | Action |
|-----|--------|
| `F1`–`F9` | Apply preset (F3 skipped) |
| `Shift+F1`–`Shift+F9` | Save current state to slot |
| `=` / `-` | Cycle forward / backward through presets |

### Theme

| Key | Action |
|-----|--------|
| `[` / `]` | Previous / next theme |

### Tmux

| Key | Action |
|-----|--------|
| `c` | Launch Claude in split pane (or focus if running) |
| `z` | Toggle manual zoom |
| `Z` | Toggle auto-zoom on API activity |

### Other

| Key | Action |
|-----|--------|
| `Ctrl+P` | Command palette |
| `Ctrl+C` | Quit |

## File Locations

| Path | Contents |
|------|----------|
| `~/.local/share/cc-dump/recordings/` | HAR recordings, organized by session and provider |
| `~/.config/cc-dump/settings.json` | Persisted settings (filtersets, theme) |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_BASE_URL` | Default upstream target (overridden by `--target`) |
| `CC_DUMP_SEED_HUE` | Base hue (0–360) for the color palette (overridden by `--seed-hue`) |

## Development

```bash
just run                          # Run the proxy
uv run pytest                     # All tests
uv run pytest -k "test_name"      # Single test
just lint                         # uvx ruff check src/
just fmt                          # uvx ruff format src/
just install                      # uv tool install -e .
just reinstall                    # after structural changes
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for system design and [PROJECT_SPEC.md](PROJECT_SPEC.md) for project goals.
