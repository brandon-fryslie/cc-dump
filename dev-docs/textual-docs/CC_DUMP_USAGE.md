# Textual Usage in cc-dump

This file documents the specific Textual APIs and widgets used in cc-dump.
For detailed documentation, see the corresponding files in this directory.

## Core APIs We Use

### App (`core/app.xml`)
- `App` - Base application class
- `ComposeResult` - Type for compose() return values
- App lifecycle and event handling

### Reactive (`core/reactive.xml`)
- `reactive` - Reactive variables that trigger UI updates
- Used for: visibility levels (vis_headers, vis_user, etc.)

### Binding (`core/binding.xml`)
- `Binding` - Keyboard shortcut definitions
- Used for: h/u/a/t/s/m/e visibility toggles, r reload, q quit

### Widget (`core/widget.xml`)
- Base widget class
- `ScrollView` - Scrollable viewport base class
- Widget composition patterns

### Events (`core/events.xml`)
- Mount/unmount lifecycle

#### Mouse Events — available fields on `Click` (and all `MouseEvent` subclasses)

| Field | Type | Notes |
|-------|------|-------|
| `event.button` | `int` | `1`=left, `2`=middle, `3`=right |
| `event.shift` | `bool` | Shift held |
| `event.ctrl` | `bool` | Ctrl held |
| `event.meta` | `bool` | Meta/Option held — unreliable, avoid |
| `event.chain` | `int` | `1`=single, `2`=double, `3`=triple |
| `event.x` / `event.y` | `int` | Widget-relative coordinates |
| `event.screen_x` / `event.screen_y` | `int` | Screen-absolute coordinates |

Usage pattern in `on_click`:
```python
def on_click(self, event: Click) -> None:
    if event.button == 3:       # right-click
        ...
    if event.shift:             # shift+click
        ...
    if event.ctrl:              # ctrl+click
        ...
    if event.chain == 2:        # double-click
        ...
```

**Terminal reliability:**
- `shift`, `ctrl`, `chain` (double-click): reliable across terminals
- `button` (right-click): works in most modern terminals
- `meta`: often intercepted by OS/terminal — avoid

**Other mouse event types** (all share the same fields above):
- `MouseDown` / `MouseUp` — press/release before `Click` fires
- `MouseMove` — hover, with same modifier fields
- `MouseScrollDown` / `MouseScrollUp` — scroll wheel

### Geometry (`support/geometry.xml`)
- `Size` - Width/height dimensions
- Layout calculations

## Widgets We Use

### Header (`widgets/header.xml`)
- Standard app header with title
- Clock display

### Footer (`widgets/footer.xml`)
- Key binding display at bottom of screen
- Custom footer implementation: `custom_footer.py`
- We access private APIs: `FooterKey`, `KeyGroup`, `FooterLabel`

### RichLog (`widgets/log.xml`)
- Logging/debug output widget
- Not currently in main UI, but available

### Static (`widgets/static.xml`)
- Simple static text widget
- Used for labels and text display

## Rendering System

### Strip (`support/geometry.xml` or internal)
- `Strip` - Pre-rendered text lines with styling
- Core of our virtual rendering system
- Used in `TurnData` for cached render output

### Cache
- `LRUCache` - Least-recently-used cache
- Used for turn data caching

### CSS Query (`support/css.xml`)
- `NoMatches` - Exception when CSS query finds nothing
- Used for safe widget lookup

## Our Custom Implementation

### ConversationView (widget_factory.py)
- Custom ScrollView subclass
- Virtual rendering using `render_line()` API
- Stores pre-rendered `Strip` objects per turn
- O(log n) binary search for line-to-turn mapping

### Custom Footer (custom_footer.py)
- Extends Footer widget
- Custom key grouping and display
- Accesses private Footer internals

## Key Patterns We Follow

1. **Virtual Rendering**: Store pre-rendered `Strip` objects, render on-demand
2. **Reactive State**: Use `reactive` for UI state that triggers re-renders
3. **Binding Actions**: Map keys to `action_*` methods on App/Widget
4. **Compose Pattern**: Build UI hierarchy via `compose()` method
5. **Event Handling**: Override `on_*` methods for event processing

## Files to Reference

When working on cc-dump Textual code, refer to:

**Core functionality:**
- `core/app.xml` - App class, lifecycle
- `core/widget.xml` - Widget base, ScrollView
- `core/reactive.xml` - Reactive variables
- `core/binding.xml` - Key bindings

**Rendering:**
- `support/geometry.xml` - Strip, Size, geometry types

**Widgets:**
- `widgets/header.xml` - Header widget
- `widgets/footer.xml` - Footer widget (we customize this)
- `widgets/static.xml` - Static text widget

**Advanced:**
- `core/events.xml` - Event system for click handling
- `support/css.xml` - Widget queries and selectors
