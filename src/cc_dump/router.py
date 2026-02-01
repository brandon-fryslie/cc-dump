"""Event router for fan-out distribution of proxy events.

Routes events from a single source queue to multiple subscribers.
Each subscriber can choose how to receive events (queue-based or direct callback).
"""

import queue
import threading
from typing import Protocol

Event = tuple  # event tuples from proxy: ("request", ...), ("response_event", ...), etc.


class Subscriber(Protocol):
    """Protocol for event subscribers. Any object with on_event(event) can subscribe."""

    def on_event(self, event: Event) -> None:
        ...


class QueueSubscriber:
    """Subscriber that puts events into its own queue for async consumption."""

    def __init__(self):
        self.queue: queue.Queue = queue.Queue()

    def on_event(self, event: Event) -> None:
        self.queue.put(event)


class DirectSubscriber:
    """Subscriber that calls a function inline in the router thread."""

    def __init__(self, fn):
        self._fn = fn

    def on_event(self, event: Event) -> None:
        self._fn(event)


class EventRouter:
    """Router that drains a source queue and fans out to subscribers."""

    def __init__(self, source: queue.Queue):
        self._source = source
        self._subscribers: list[Subscriber] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def add_subscriber(self, sub: Subscriber) -> None:
        """Add a subscriber to receive events."""
        self._subscribers.append(sub)

    def start(self) -> None:
        """Start the router thread."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the router thread gracefully."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        """Router thread main loop: drain source, fan out to subscribers."""
        while not self._stop.is_set():
            try:
                event = self._source.get(timeout=0.5)
            except queue.Empty:
                continue

            # Fan out to all subscribers
            for sub in self._subscribers:
                try:
                    sub.on_event(event)
                except Exception as e:
                    # Don't let one subscriber's error kill the router
                    import sys
                    import traceback
                    sys.stderr.write("[router] subscriber error: {}\n".format(e))
                    traceback.print_exc(file=sys.stderr)
                    sys.stderr.flush()
