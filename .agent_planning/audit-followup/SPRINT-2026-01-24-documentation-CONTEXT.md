# Implementation Context: documentation

## ARCHITECTURE.md Template

```markdown
# cc-dump Architecture

## Overview

cc-dump is a transparent HTTP proxy that monitors Claude Code API traffic. It captures requests and responses, transforms them into a structured intermediate representation, and distributes them to multiple consumers (TUI display, SQLite storage).

## System Architecture

```
                                    ┌─────────────────┐
                                    │   Claude Code   │
                                    │     Client      │
                                    └────────┬────────┘
                                             │
                                    HTTP Request (ANTHROPIC_BASE_URL)
                                             │
                                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│                          cc-dump Proxy                                │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐ │
│  │  proxy.py    │────▶│  queue.Queue │────▶│    router.py         │ │
│  │ HTTP Handler │     │ Event Buffer │     │   EventRouter        │ │
│  └──────────────┘     └──────────────┘     └──────────┬───────────┘ │
│         │                                              │             │
│         │ Forward                         Fan-out to subscribers     │
│         ▼                                              │             │
│  ┌──────────────┐                    ┌─────────────────┼─────────┐  │
│  │ Anthropic API│                    │                 │         │  │
│  └──────────────┘                    ▼                 ▼         │  │
│                              ┌────────────┐    ┌────────────┐    │  │
│                              │ TUI (app)  │    │ SQLite     │    │  │
│                              │ Display    │    │ Writer     │    │  │
│                              └────────────┘    └────────────┘    │  │
└──────────────────────────────────────────────────────────────────────┘
```

## Data Flow

1. **Capture**: proxy.py intercepts HTTP requests, parses JSON bodies
2. **Event Generation**: Proxy emits event tuples: `("request", body)`, `("response_event", type, data)`
3. **Distribution**: EventRouter fans out events to all subscribers
4. **Transformation**: formatting.py converts events to FormattedBlock IR
5. **Rendering**: tui/rendering.py converts blocks to Rich Text
6. **Persistence**: store.py writes turns to SQLite

## Key Design Decisions

### Event-Driven Architecture
- **Why**: Decouples data source (proxy) from consumers (display, storage)
- **Benefit**: Add new consumers without modifying proxy
- **Pattern**: Observer/pub-sub via EventRouter

### Structured IR (FormattedBlock)
- **Why**: Separates data structure from presentation
- **Benefit**: Same blocks can render to different outputs
- **Pattern**: Intermediate representation like compiler IRs

### Hot-Reload Support
- **Why**: Fast iteration during development
- **How**: Module-level imports reloaded on file change
- **Boundary**: proxy.py is stable; everything else reloads

### Local-First with SQLite
- **Why**: No external dependencies, queryable history
- **Benefit**: Works offline, fast, simple deployment

## Module Responsibilities

| Module | Single Responsibility |
|--------|----------------------|
| cli.py | Entry point, wire up components |
| proxy.py | HTTP interception, event emission |
| router.py | Event fan-out to subscribers |
| formatting.py | Event → FormattedBlock conversion |
| analysis.py | Token estimation, budget computation |
| store.py | SQLite persistence |
| hot_reload.py | File watching, module reloading |
| tui/app.py | Textual application, event loop |
| tui/widgets.py | Custom Textual widgets |
| tui/rendering.py | FormattedBlock → Rich Text |

## Threading Model

- **Main Thread**: TUI event loop (Textual)
- **Router Thread**: Drains event queue, fans out to subscribers
- **Proxy Threads**: One per HTTP request (HTTPServer default)
- **Synchronization**: thread-safe Queue for event passing

## Extension Points

### Adding a New Block Type
1. Define dataclass in formatting.py inheriting FormattedBlock
2. Add render function in tui/rendering.py
3. Add to BLOCK_RENDERERS registry

### Adding a New Subscriber
1. Implement Subscriber protocol (on_event method)
2. Add to router via router.add_subscriber()
```

## PROJECT_SPEC.md Template

```markdown
# cc-dump Project Specification

## Purpose

cc-dump is a transparent HTTP proxy for monitoring and analyzing Claude Code API traffic during development.

## Target Users

- **Claude Code Developers**: Debug prompts, inspect tool usage, understand context flow
- **API Integration Developers**: Test Claude API integrations locally
- **Prompt Engineers**: Analyze token budgets, cache hit rates, system prompt changes

## Core Features

1. **Transparent Proxying**: Intercepts API traffic without client modification
2. **Real-time TUI**: Live display with keyboard-driven filtering
3. **System Prompt Tracking**: Hash-based deduplication with change detection and diffs
4. **Token Budget Analysis**: Per-turn breakdown of context usage
5. **Tool Economics**: Track input/output tokens per tool invocation
6. **SQLite Persistence**: Query conversation history across sessions
7. **Hot-Reload**: Modify display code without restarting

## Non-Goals

1. **Not for Production**: Local development tool only, no auth/security
2. **Not Multi-User**: Single-user, localhost binding
3. **Not a Proxy for Other APIs**: Claude/Anthropic API specific
4. **Not a Modification Proxy**: Read-only; no request/response tampering
5. **Not a Testing Framework**: Monitoring only, no assertions or validation

## Success Criteria

1. Proxy starts with `cc-dump` and accepts traffic on port 3344
2. TUI displays requests/responses with <100ms latency
3. System prompts are tracked and diffed across turns
4. Token budgets are computed and displayed
5. Conversation history is queryable via SQLite

## Terminology

| Term | Definition |
|------|------------|
| **Turn** | A complete request-response exchange |
| **FormattedBlock** | Structured IR for display content |
| **Subscriber** | Consumer of proxy events |
| **Content Tracking** | Hash-based deduplication of repeated content |
```

## Notes

- These templates are starting points; adjust based on what's actually in the code
- Keep documents stable - they're strategic, not tactical
- Link from README.md to these docs for discoverability
