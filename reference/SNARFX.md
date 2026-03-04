# SnarfX

MobX-inspired reactive state management for Python. Zero dependencies. Automatic dependency tracking. Synchronous, glitch-free updates.

```
pip install snarfx
```

## Core Concepts

SnarfX tracks which observables a function reads and automatically re-evaluates when those observables change. There is no manual subscription wiring. Dependencies are discovered at runtime by intercepting reads during evaluation.

The reactive primitives:

| Primitive | Purpose |
|---|---|
| `Observable` | Mutable state that tracks its readers |
| `Computed` | Derived value, lazy, cached, auto-invalidated |
| `Reaction` / `autorun` | Side effect that re-runs when dependencies change |
| `action` / `transaction` | Batch mutations to prevent intermediate states |
| `Store` | Keyed observable container with lifecycle management |
| `EventStream` | Push-based stream with map/filter/debounce operators |
| `watch` | Run a function in a managed daemon thread |

## Quick Start

```python
from snarfx import Observable, computed, autorun

counter = Observable(0)

@computed
def doubled():
    return counter.get() * 2

autorun(lambda: print(f"doubled = {doubled.get()}"))
# prints: doubled = 0

counter.set(5)
# prints: doubled = 10
```

No registration. No decorator configuration. The `autorun` callback read `doubled`, which read `counter`. SnarfX recorded both edges. When `counter` changed, `doubled` was marked dirty, and the autorun re-executed.

## Observables

Reactive state containers. Read with `.get()`, write with `.set()`. Reads inside a derivation (computed or reaction) are automatically tracked.

```python
from snarfx import Observable, ObservableList, ObservableDict

# Scalar
name = Observable("Alice")
name.get()       # "Alice"
name.set("Bob")  # triggers dependents

# List — full list interface, every mutation notifies
items = ObservableList([1, 2, 3])
items.append(4)
items.pop(0)

# Dict — full dict interface, every mutation notifies
config = ObservableDict({"theme": "dark", "lang": "en"})
config["theme"] = "light"
```

## Computed Values

Derived state. Lazy evaluation: only recomputes on `.get()` when a dependency has changed. Results are cached between changes.

```python
from snarfx import Observable, computed

first = Observable("Jane")
last = Observable("Doe")

@computed
def full_name():
    return f"{first.get()} {last.get()}"

full_name.get()  # "Jane Doe" (computed, cached)
full_name.get()  # "Jane Doe" (cache hit, no recomputation)

first.set("John")
full_name.get()  # "John Doe" (recomputed)
```

Computed values can depend on other computed values. The dependency graph is arbitrary depth.

## Reactions

Side effects that run when their dependencies change.

**autorun** runs immediately, then re-runs on any dependency change:

```python
from snarfx import Observable, autorun

count = Observable(0)
log = []

r = autorun(lambda: log.append(f"count is {count.get()}"))
# log == ["count is 0"]

count.set(1)
# log == ["count is 0", "count is 1"]

r.dispose()  # stop reacting
```

**reaction** separates data selection from the side effect. The effect only fires when the selected value changes:

```python
from snarfx import Observable, reaction

first = Observable("Alice")
last = Observable("Smith")
notifications = []

r = reaction(
    lambda: first.get(),
    lambda name: notifications.append(f"first name changed to {name}"),
)

first.set("Bob")
# notifications == ["first name changed to Bob"]

last.set("Jones")
# notifications unchanged -- reaction only tracks first.get()

r.dispose()
```

## Actions and Transactions

Batch multiple mutations so reactions fire once with the final state, not on each intermediate change.

```python
from snarfx import Observable, autorun, action, transaction

a = Observable(0)
b = Observable(0)
log = []

autorun(lambda: log.append((a.get(), b.get())))
# log == [(0, 0)]

# Without batching: reaction fires twice
a.set(1)  # log == [(0, 0), (1, 0)]
b.set(1)  # log == [(0, 0), (1, 0), (1, 1)]

# With action decorator: reaction fires once
@action
def swap():
    a.set(b.get())
    b.set(a.get())

swap()
# single reaction with final state

# With transaction context manager:
with transaction():
    a.set(10)
    b.set(20)
# single reaction: (10, 20)
```

## Store

A keyed container of observables with lifecycle management. Useful when state has a known schema and reactions should be co-located with the data they operate on.

```python
from snarfx import Store, autorun

store = Store(
    schema={"count": 0, "label": "clicks"},
    initial={"count": 5},
)

store.get("count")  # 5 (from initial)
store.get("label")  # "clicks" (from schema default)

store.set("count", 10)
store.update({"count": 0, "label": "resets"})  # batched

store.dispose()  # disposes all managed reactions
```

Schema evolution via `reconcile` adds new keys without losing existing values:

```python
def setup_reactions(store):
    r = autorun(lambda: print(store.get("count")))
    return [r]

store.reconcile(
    schema={"count": 0, "label": "clicks", "enabled": True},
    setup_fn=setup_reactions,
)
# "enabled" key added, existing "count" and "label" values preserved
# old reactions disposed, new reactions registered
```

For applications with hot-reload (development servers, notebook environments), `HotReloadStore` adds exception safety and logging:

```python
from snarfx.hot_reload import HotReloadStore

store = HotReloadStore(schema={"status": "idle"})
# reconcile() catches and logs reaction setup failures
# store continues in degraded mode (values intact, no reactions)
```

## EventStream

Push-based event stream for values that don't have "current state" semantics -- notifications, clicks, messages. Operator chaining creates new streams; `dispose()` tears down the chain.

```python
from snarfx import EventStream

clicks = EventStream()

# Subscribe directly
clicks.subscribe(lambda coords: print(f"clicked at {coords}"))

# Operator chaining
clicks.filter(lambda c: c[0] > 100).map(lambda c: f"right-side click at {c}").subscribe(print)

# Debounce rapid events (fires after quiet period)
search_input = EventStream()
search_input.debounce(0.3).subscribe(lambda query: run_search(query))

# Emit values
clicks.emit((50, 120))
clicks.emit((200, 80))

# Teardown
clicks.dispose()  # disposes this stream and all downstream children
```

## Background Threads

`watch()` runs a function in a daemon thread. Combined with `set_scheduler()`, observable mutations from background threads are automatically marshaled to the main thread.

```python
from snarfx import Observable, autorun, watch, set_scheduler
import time

# In a UI application, set the scheduler once at startup:
# set_scheduler(app.call_from_thread)

status = Observable("idle")

def poll_service():
    while True:
        result = check_health()  # blocking I/O
        status.set(result)       # auto-marshaled if scheduler is set
        time.sleep(5)

handle = watch(poll_service)

# Reactions on the main thread fire when status changes
autorun(lambda: update_status_indicator(status.get()))

# Later: stop the background thread
handle.dispose()
```

## Framework Integration

SnarfX is framework-agnostic. The core library has zero dependencies and works anywhere Python runs.

For Textual TUI applications, an integration module handles thread marshaling, widget lifecycle guards, and `NoMatches` safety. See [docs/textual.md](docs/textual.md).

## Architecture

All reactive state lives in a single internal module (`_anchor`) as plain Python dicts. Observable, Computed, and Reaction instances are thin handles holding only an integer ID. This separation means:

- State survives module reloads (the data outlives the behavior code)
- Memory layout is cache-friendly (contiguous dict storage)
- No reference cycles between observables and their observers

Dependency tracking uses `contextvars` to record which observables are read during a derivation's evaluation. This is the same mechanism MobX uses, adapted for Python's threading model.

## API Reference

### Observable[T]

| Method | Description |
|---|---|
| `Observable(value)` | Create with initial value |
| `.get() -> T` | Read value, track dependency |
| `.set(value)` | Write value, notify observers |

### ObservableList[T]

Full `list` interface. All reads track, all mutations notify.

### ObservableDict[KT, VT]

Full `dict` interface. All reads track, all mutations notify.

### Computed[T]

| Method | Description |
|---|---|
| `Computed(fn)` | Create from zero-arg function |
| `@computed` | Decorator form |
| `.get() -> T` | Read cached value, recompute if dirty |
| `.dispose()` | Disconnect from dependencies |

### Reaction

| Method | Description |
|---|---|
| `autorun(fn) -> Reaction` | Run fn now, re-run on changes |
| `reaction(data_fn, effect_fn) -> Reaction` | Track data_fn, call effect_fn on value change |
| `.dispose()` | Stop reacting |

### Batching

| Method | Description |
|---|---|
| `@action` | Decorator: batch mutations in function body |
| `transaction()` | Context manager: batch mutations in block |

### Store

| Method | Description |
|---|---|
| `Store(schema, initial=None)` | Create with schema dict and optional initial values |
| `.get(key) -> object` | Read observable by key |
| `.set(key, value)` | Write observable by key |
| `.update(values)` | Batch-set multiple keys |
| `.reconcile(schema, setup_fn)` | Evolve schema, re-register reactions |
| `.dispose()` | Dispose all managed reactions |

### EventStream[T]

| Method | Description |
|---|---|
| `EventStream()` | Create a new stream |
| `.emit(value)` | Push value to subscribers |
| `.subscribe(callback) -> disposer` | Register callback, returns unsubscribe function |
| `.map(fn) -> EventStream` | Transform values |
| `.filter(fn) -> EventStream` | Pass values where fn returns True |
| `.debounce(seconds) -> EventStream` | Coalesce rapid events |
| `.dispose()` | Tear down stream and all children |

### Threading

| Method | Description |
|---|---|
| `set_scheduler(fn)` | Set cross-thread marshal function (call once from main thread) |
| `watch(fn) -> WatchHandle` | Run fn in daemon thread |
| `WatchHandle.dispose()` | Signal thread to stop |

## Requirements

- Python 3.10+
- Zero runtime dependencies

## License

MIT