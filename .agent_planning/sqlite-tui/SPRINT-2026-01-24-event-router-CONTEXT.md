# Implementation Context: event-router
Generated: 2026-01-24

## Files to Create
- `src/cc_dump/router.py`

## Files to Modify
- `src/cc_dump/cli.py`

## Key Implementation Details

### router.py structure

```python
import queue
import threading
from typing import Any, Protocol

Event = tuple  # event tuples from proxy

class Subscriber(Protocol):
    def on_event(self, event: Event) -> None: ...

class QueueSubscriber:
    def __init__(self):
        self.queue: queue.Queue = queue.Queue()

    def on_event(self, event: Event) -> None:
        self.queue.put(event)

class DirectSubscriber:
    def __init__(self, fn):
        self._fn = fn

    def on_event(self, event: Event) -> None:
        self._fn(event)

class EventRouter:
    def __init__(self, source: queue.Queue):
        self._source = source
        self._subscribers: list[Subscriber] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def add_subscriber(self, sub: Subscriber) -> None:
        self._subscribers.append(sub)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._source.get(timeout=0.5)
            except queue.Empty:
                continue
            for sub in self._subscribers:
                sub.on_event(event)
```

### cli.py changes

```python
from cc_dump.router import EventRouter, QueueSubscriber

def main():
    parser.add_argument("--no-tui", action="store_true", help="Legacy terminal output")
    ...

    router = EventRouter(event_q)
    display_sub = QueueSubscriber()
    router.add_subscriber(display_sub)
    router.start()

    try:
        while True:
            try:
                event = display_sub.queue.get(timeout=1.0)
            except queue.Empty:
                continue
            _check_reload()
            cc_dump.display.handle(event, state)
    except KeyboardInterrupt:
        router.stop()
        server.shutdown()
```
