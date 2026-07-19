# cc-dump

A live viewer for everything Claude Code sends to and receives from the Anthropic API. Run it, point Claude Code at it, and watch the full conversation — system prompts, tool calls, token costs, streaming responses — in a terminal UI.

## Quickstart

```bash
# 1. Install (pulls all dependencies, including snarfx, from PyPI)
uv tool install "git+https://github.com/brandon-fryslie/cc-dump.git"

# 2. Start cc-dump — it prints the port it's listening on
cc-dump
# → Listening on: http://127.0.0.1:<PORT>

# 3. In another terminal, launch Claude Code pointed at cc-dump
ANTHROPIC_BASE_URL=http://127.0.0.1:<PORT> claude
```

That's it. Every request Claude Code makes now streams into the cc-dump UI, and is recorded to disk automatically so you can replay it later.

To replay a past session instead of proxying live traffic:

```bash
cc-dump --replay latest
```

## Requirements

- **[uv](https://docs.astral.sh/uv/)** — the installer used above. Install it with `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **Python 3.10+** — `uv` will fetch a suitable Python for you if you don't have one.
- **[Claude Code](https://github.com/anthropics/claude-code)** — the thing you're monitoring.
- A terminal that renders 256 colors / truecolor (any modern terminal: iTerm2, Ghostty, Kitty, Windows Terminal, etc.).

No API keys, certificates, or config files are needed. cc-dump sits between Claude Code and Anthropic as a plain reverse proxy — Claude Code still uses your normal auth.

**Optional:** running inside `tmux` unlocks split-pane launching and auto-zoom (see the Tmux keys below).

## Using it

cc-dump is keyboard-driven. The conversation scrolls in the main pane; every content type can be shown at three levels of detail, and panels along the side show cost and timeline analysis.

### The core idea: 3 levels of detail

Each **category** of content (your messages, the assistant's, tool calls, etc.) can be displayed at one of three levels. Press a category's number key to cycle it:

| Level | Symbol | Shows |
|-------|--------|-------|
| Existence | `·` | One line — "this exists," details hidden |
| Summary | `◐` | A short preview |
| Full | `●` | Everything |

You can also **click any block** marked `▶`/`▼` to expand or collapse just that one block.

### Category keys

| Key | Category | Starts at |
|-----|----------|-----------|
| `1` | Your messages | Full |
| `2` | Assistant | Full |
| `3` | Tool calls & results | Summary |
| `4` | System prompt | Summary |
| `5` | Metadata | Hidden |
| `6` | Thinking | Summary |

Hold **Shift** with a number to toggle its detail axis; the matching lowercase letter (`q w e r t y` → categories 1–6) toggles expansion.

### Navigation

| Key | Action |
|-----|--------|
| `j` / `k` | Scroll down / up a line |
| `h` / `l` | Scroll left / right a column |
| `Ctrl+D` / `Ctrl+U` | Half page down / up |
| `Ctrl+F` / `Ctrl+B` | Full page down / up |
| `g` / `G` | Jump to top / bottom |
| `0` | Follow mode — auto-scroll to newest content |

### Search

| Key | Action |
|-----|--------|
| `/` | Open search (regex, case-insensitive by default) |
| `Enter` | Jump to first match |
| `n` / `N` | Next / previous match |
| `Alt+c` / `Alt+w` / `Alt+r` / `Alt+i` | Toggle case / word / regex / incremental |
| `Esc` | Close search, keep the view it opened |
| `q` | Cancel and restore the view you had before |

Searching automatically reveals matching content in full, even if that category was collapsed.

### Panels & views

| Key | Action |
|-----|--------|
| `.` | Cycle side panel: stats → cost → timeline |
| `,` | Toggle cost panel between totals and per-model breakdown |
| `i` | Server info (URL, mode, session, versions) — click a row to copy it |
| `Ctrl+L` | Debug log panel |

### Presets & themes

| Key | Action |
|-----|--------|
| `F1`–`F9` | Apply a visibility preset (Conversation, Overview, Tools, Cost, Full Debug, …) |
| `=` / `-` | Cycle presets forward / backward |
| `[` / `]` | Previous / next color theme (remembered across runs) |

### Tmux (only when running inside tmux)

| Key | Action |
|-----|--------|
| `c` | Launch Claude Code in a split pane (or focus it if already running) |
| `z` | Toggle zoom on the cc-dump pane |
| `Z` | Auto-zoom cc-dump whenever a request is in flight |

### Everything else

| Key | Action |
|-----|--------|
| `Ctrl+P` | Command palette — searchable list of every action, including "Dump conversation" to export |
| `Ctrl+C` | Quit |

---

Contributing or want the full CLI reference? Run `cc-dump --help`, and see [ARCHITECTURE.md](ARCHITECTURE.md) and [CLAUDE.md](CLAUDE.md).
