# Sprint: textual-tui - Textual TUI Application
Generated: 2026-01-24
Confidence: HIGH: 4, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Create a Textual-based TUI that displays conversation turns with togglable filters, expandable messages, live stats panel, and hot-reload support.

## Scope
**Deliverables:**
- `tui/__init__.py` — package marker
- `tui/app.py` — Textual App with bindings, reactive filters, worker-based event consumption
- `tui/widgets.py` — ConversationView (scrollable), StatsPanel
- `tui/rendering.py` — FormattedBlock → Rich renderables
- `tui/styles.css` — Textual CSS for layout
- Updated `pyproject.toml` — textual dependency
- Updated `cli.py` — TUI as default mode, --no-tui for legacy

## Work Items

### P0: Add textual dependency and create package structure
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] `textual>=0.80.0` added to pyproject.toml dependencies
- [ ] `src/cc_dump/tui/__init__.py` exists
- [ ] Package imports successfully

### P1: Create tui/rendering.py
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] Converts every FormattedBlock subclass to Rich Text/renderable objects
- [ ] Uses Rich markup for colors (maps ANSI color intent to Rich styles)
- [ ] TrackedContentBlock renders with colored tags and content/diff
- [ ] TextDeltaBlock returns raw Rich Text for inline streaming display
- [ ] Produces visually equivalent output to ANSI renderer but using Rich

**Technical Notes:**
- Rich Text objects with styled spans
- DiffBlock: green for adds, red for dels, dim for hunks
- Tag rendering: Rich markup `[bold on blue]` style

### P2: Create tui/widgets.py
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] `ConversationView(ScrollableContainer)` — displays rendered turns
- [ ] Supports appending new content (auto-scrolls to bottom if at bottom)
- [ ] Supports re-rendering existing content when filters change
- [ ] `StatsPanel(Static)` — shows request count, token totals, model, session duration
- [ ] StatsPanel updates reactively when new data arrives
- [ ] Filters control which block types are visible (system, tools, metadata, etc.)

**Technical Notes:**
- ConversationView stores list of (turn_blocks, rendered_widget) pairs
- On filter change: re-render all stored turns with new filter set
- StatsPanel: request_count, total_input_tokens, total_output_tokens, models_seen, duration
- Auto-scroll: check if scroll position is at bottom before appending

### P3: Create tui/app.py with bindings and worker
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] `CcDumpApp(App)` with CSS loaded from styles.css
- [ ] Keyboard bindings: h(headers), t(tools), a(agents), s(system), e(expand), m(metadata), p(stats panel), q(quit)
- [ ] Reactive filter booleans that trigger re-render on toggle
- [ ] Textual worker drains QueueSubscriber, processes events on main thread
- [ ] Hot-reload timer: watches formatting module files, reloads on change
- [ ] Layout: ConversationView (main area) + StatsPanel (bottom or side)
- [ ] Footer shows current filter states
- [ ] Graceful shutdown: stops worker, signals CLI to stop router

**Technical Notes:**
- Worker pattern: `self.run_worker(self._drain_events, thread=True)`
- Event processing: worker puts events into app message queue, app handles on main thread
- Filter reactives: `show_system = reactive(True)`, etc.
- On filter change: watcher method re-renders conversation
- Hot-reload: `set_interval(1.0, self._check_reload)`
- CSS layout: vertical split, conversation takes most space, stats panel fixed height at bottom

### P4: Wire TUI into cli.py as default mode
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] TUI mode is default (no flags needed)
- [ ] `--no-tui` selects legacy display loop
- [ ] TUI receives events via QueueSubscriber (same as legacy mode)
- [ ] Router + SQLiteWriter + TUI all work together
- [ ] Ctrl+C / q key both exit cleanly

## Dependencies
- Sprint 1 (formatting-ir): FormattedBlock types for rendering
- Sprint 2 (event-router): QueueSubscriber for TUI event feed
- Sprint 3 (sqlite-persistence): Optional but should coexist

## Risks
- Textual version compatibility: pin to >=0.80.0 for stable API
- Rich rendering vs ANSI: minor visual differences acceptable
- Hot-reload in TUI: may need to re-import rendering module
