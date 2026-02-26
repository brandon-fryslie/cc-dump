#!/usr/bin/env python3
"""Create a minimal snarfx workspace member for CI.

snarfx is developed as a separate git repo and .gitignored in cc-dump.
This script creates importable stubs so uv sync succeeds and tests that
don't directly use snarfx can run in CI.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SNARFX_ROOT = REPO_ROOT / "snarfx"
SRC = SNARFX_ROOT / "src" / "snarfx"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def main() -> None:
    if (SNARFX_ROOT / "src" / "snarfx" / "observable.py").exists():
        print("snarfx already exists, skipping stub creation")
        return

    write(
        SNARFX_ROOT / "pyproject.toml",
        """\
[project]
name = "snarfx"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/snarfx"]
""",
    )

    # _anchor — global state backing store
    write(
        SRC / "_anchor.py",
        """\
_next_id = 0
values: dict[int, object] = {}
observers: dict[int, set] = {}

def new_id() -> int:
    global _next_id
    _next_id += 1
    return _next_id
""",
    )

    # _tracking — derivation tracking
    write(
        SRC / "_tracking.py",
        """\
import contextvars
import threading

current_derivation = contextvars.ContextVar("current_derivation", default=None)
_pending = 0
_lock = threading.Lock()

def schedule(derivation) -> None:
    derivation._run()

def get_pending_count() -> int:
    return _pending
""",
    )

    # observable — Observable, ObservableList, ObservableDict
    write(
        SRC / "observable.py",
        """\
from __future__ import annotations
from snarfx._tracking import current_derivation
from snarfx import _anchor

def set_scheduler(scheduler) -> None:
    pass

class Observable:
    __slots__ = ("_id",)
    def __init__(self, value=None):
        self._id = _anchor.new_id()
        _anchor.values[self._id] = value
        _anchor.observers[self._id] = set()
    def get(self):
        return _anchor.values[self._id]
    def set(self, value):
        _anchor.values[self._id] = value
        for obs in list(_anchor.observers.get(self._id, [])):
            obs._run()

class ObservableList(list):
    pass

class ObservableDict(dict):
    pass
""",
    )

    # computed
    write(
        SRC / "computed.py",
        """\
class Computed:
    def __init__(self, fn):
        self._fn = fn
        self._dependencies = set()
    def get(self):
        return self._fn()
    def _run(self):
        pass

def computed(fn):
    return Computed(fn)
""",
    )

    # reaction
    write(
        SRC / "reaction.py",
        """\
class _Disposer:
    def dispose(self): pass

class Reaction:
    def __init__(self, fn):
        self._fn = fn
        self._dependencies = set()
    def _run(self):
        self._fn()
    def dispose(self):
        pass

def autorun(fn):
    try:
        fn()
    except Exception:
        pass
    return _Disposer()

def reaction(data_fn, effect_fn, *, fire_immediately=False):
    if fire_immediately:
        try:
            effect_fn(data_fn())
        except Exception:
            pass
    return _Disposer()
""",
    )

    # action
    write(
        SRC / "action.py",
        """\
from contextlib import contextmanager

def action(fn):
    return fn

@contextmanager
def transaction():
    yield
""",
    )

    # store
    write(
        SRC / "store.py",
        """\
from snarfx.observable import Observable

class Store:
    def __init__(self, schema=None, initial=None):
        self._observables = {}
        self._reaction_disposers = []
        for key, default in (schema or {}).items():
            value = initial.get(key, default) if initial else default
            self._observables[key] = Observable(value)
    def get(self, key):
        obs = self._observables.get(key)
        return obs.get() if obs else None
    def set(self, key, value):
        obs = self._observables.get(key)
        if obs:
            obs.set(value)
    def update(self, values):
        for k, v in values.items():
            self.set(k, v)
    def reconcile(self, schema, setup_fn):
        for key, default in schema.items():
            if key not in self._observables:
                self._observables[key] = Observable(default)
        self._dispose_reactions()
        self._reaction_disposers = setup_fn(self) or []
    def _dispose_reactions(self):
        for d in self._reaction_disposers:
            d.dispose()
        self._reaction_disposers.clear()
    def dispose(self):
        self._dispose_reactions()
""",
    )

    # watch
    write(
        SRC / "watch.py",
        """\
class WatchHandle:
    def dispose(self): pass

def watch(observable, callback):
    return WatchHandle()
""",
    )

    # stream
    write(
        SRC / "stream.py",
        """\
class EventStream:
    def __init__(self):
        self._subscribers = []
        self._children = []
        self._disposed = False
    def emit(self, value):
        if self._disposed:
            return
        for cb in self._subscribers:
            cb(value)
    def subscribe(self, callback):
        self._subscribers.append(callback)
        def _unsub():
            try: self._subscribers.remove(callback)
            except ValueError: pass
        return _unsub
    def debounce(self, seconds):
        return EventStream()
    def map(self, fn):
        return EventStream()
    def filter(self, fn):
        return EventStream()
    def dispose(self):
        self._disposed = True
        self._subscribers.clear()
""",
    )

    # hot_reload
    write(
        SRC / "hot_reload.py",
        """\
from snarfx.store import Store

class HotReloadStore(Store):
    def reconcile(self, schema, setup_fn):
        super().reconcile(schema, setup_fn)
""",
    )

    # textual integration
    write(
        SRC / "textual.py",
        """\
from contextlib import contextmanager

class _Disposer:
    def dispose(self): pass

@contextmanager
def pause(app):
    yield

def is_safe(app) -> bool:
    return getattr(app, "is_running", False)

def reaction(app, data_fn, effect_fn, *, fire_immediately=False):
    return _Disposer()

def autorun(app, fn):
    return _Disposer()
""",
    )

    # __init__
    write(
        SRC / "__init__.py",
        """\
from snarfx._tracking import get_pending_count
from snarfx.observable import Observable, ObservableList, ObservableDict, set_scheduler
from snarfx.computed import Computed, computed
from snarfx.reaction import Reaction, autorun, reaction
from snarfx.action import action, transaction
from snarfx.store import Store
from snarfx.watch import watch, WatchHandle
from snarfx.stream import EventStream

__all__ = [
    "Observable", "ObservableList", "ObservableDict",
    "Computed", "computed",
    "Reaction", "autorun", "reaction",
    "action", "transaction",
    "get_pending_count", "Store", "set_scheduler",
    "watch", "WatchHandle", "EventStream",
]
""",
    )

    print("Created snarfx CI stub at", SNARFX_ROOT)


if __name__ == "__main__":
    main()
