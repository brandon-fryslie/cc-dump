# PROJECT_SPEC.md

## What cc-dump Is

cc-dump is a transparent HTTP proxy that sits between Claude Code and the Anthropic API, capturing and displaying all API traffic in a real-time TUI. It is a debugging and observability tool for understanding what Claude Code is actually sending and receiving.

## Why It Exists

Claude Code is opaque by design — you see the assistant's text output, but not the full API payloads: the system prompts, tool definitions, tool use/result blocks, token counts, caching behavior, or how the context window fills up over a session. cc-dump makes all of this visible.

## Core Goals

### 1. Full Transparency

Every API request and response is captured and displayed. Everything is available for inspection — simple filters let users control what they see, when they want to see it.

### 2. System Prompt Tracking

System prompts are the most interesting part of Claude Code's behavior and the hardest to observe. cc-dump assigns color-coded tags to each distinct prompt section, and allows you to visualize how your personal configuration is represented in the actual requests and responses underlying CC's functionality.

### 3. Real-Time Streaming

Responses stream into the TUI as they arrive, giving users full insight into what Claude Code is doing behind the scenes. Not only the main chat, but subagents, tool use, skills, and MCP.  The display updates incrementally — no waiting for the full response before showing anything.

### 4. Session-Level Analysis

Beyond individual requests, cc-dump provides aggregate views: total token usage, per-tool cost breakdowns, and context growth over time. These help answer questions like "how fast is the context window filling up?" and "which tools are using the most tokens?"

### 5. Hot-Reloadable Development

The TUI supports hot-reloading of formatting, rendering, and widget code without restarting the proxy or losing captured data. This makes development fast — save a file, see the change immediately.

### 6. Zero Configuration

cc-dump should work out of the box with a single command. Point Claude Code at it and go. No config files, no setup, no accounts.

## What It Is Not

- **Not a proxy for production use.** It's a development tool.
- **Not an API client.** It doesn't make API calls — it observes them.
- **Not a security tool.** It strips auth headers from display but doesn't provide security guarantees (except that we don't do anything Claude doesn't do).

## Key Design Decisions

**Two-stage pipeline (IR separation):** API JSON is first parsed into a backend-agnostic intermediate representation (`FormattedBlock` types in `formatting.py`), then rendered to Rich Text for display (`tui/rendering.py`). This means the formatting logic can be tested and reused independently of the TUI.

**Virtual rendering:** The conversation view uses Textual's Line API rather than appending widgets. This gives O(log n) line lookup and O(viewport) rendering cost, so performance doesn't degrade over long sessions.

(no longer true, I nixed this) **Database as source of truth for aggregates:** Token counts and tool statistics come from SQLite queries, not in-memory accumulation. This avoids drift between what's displayed and what was actually captured.

**Filter-based progressive disclosure:** The default view shows a compact summary. Keybindings progressively reveal more detail (headers, tool I/O, system prompts, expanded content, metadata). Each filter has a colored indicator so users can see at a glance what's shown.

## Target Users

Developers who use Claude Code and want to understand its API behavior — what prompts it sends, how tools are invoked, how the context window is managed, and where tokens are being spent.
