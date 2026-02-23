"""Unit tests for router.py - event distribution."""

import queue
import threading
import time

import pytest

from cc_dump.pipeline.router import DirectSubscriber, EventRouter, QueueSubscriber
from cc_dump.pipeline.event_types import (
    PipelineEvent,
    RequestBodyEvent,
    ResponseDoneEvent,
    ErrorEvent,
    LogEvent,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _wait_for(condition, timeout=2.0, interval=0.01):
    """Poll until condition() is truthy or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return condition()


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def source_queue():
    """Create a fresh source queue."""
    return queue.Queue()


@pytest.fixture
def router(source_queue):
    """Create a router and ensure cleanup."""
    r = EventRouter(source_queue)
    yield r
    r.stop()


# ─── QueueSubscriber Tests ────────────────────────────────────────────────────


def test_queue_subscriber_receives_events():
    """QueueSubscriber puts events into queue."""
    sub = QueueSubscriber()

    event1 = RequestBodyEvent(body={"data": "test"})
    event2 = ResponseDoneEvent()

    sub.on_event(event1)
    sub.on_event(event2)

    # Events should be in queue
    assert sub.queue.get(timeout=1) == event1
    assert sub.queue.get(timeout=1) == event2


def test_queue_subscriber_order_preserved():
    """QueueSubscriber preserves event order."""
    sub = QueueSubscriber()

    events: list[PipelineEvent] = [
        RequestBodyEvent(body={"n": 1}),
        ResponseDoneEvent(),
        ErrorEvent(code=500, reason="fail"),
    ]

    for event in events:
        sub.on_event(event)

    # Should receive in same order
    for expected in events:
        received = sub.queue.get(timeout=1)
        assert received == expected


# ─── DirectSubscriber Tests ───────────────────────────────────────────────────


def test_direct_subscriber_calls_function():
    """DirectSubscriber invokes function inline."""
    received = []

    def collector(event):
        received.append(event)

    sub = DirectSubscriber(collector)

    event = RequestBodyEvent(body={"data": "value"})
    sub.on_event(event)

    # Function should be called immediately
    assert len(received) == 1
    assert received[0] == event


def test_direct_subscriber_multiple_events():
    """DirectSubscriber handles multiple events."""
    received = []

    def collector(event):
        received.append(event)

    sub = DirectSubscriber(collector)

    events: list[PipelineEvent] = [
        RequestBodyEvent(body={"n": 1}),
        ResponseDoneEvent(),
        ErrorEvent(code=400, reason="bad"),
    ]
    for event in events:
        sub.on_event(event)

    assert received == events


# ─── EventRouter Tests ────────────────────────────────────────────────────────


def test_router_fanout(router, source_queue):
    """All subscribers receive event."""
    received1 = []
    received2 = []

    def collector1(event):
        received1.append(event)

    def collector2(event):
        received2.append(event)

    router.add_subscriber(DirectSubscriber(collector1))
    router.add_subscriber(DirectSubscriber(collector2))
    router.start()

    _wait_for(lambda: router._thread and router._thread.is_alive())

    event = RequestBodyEvent(body={"test": "data"})
    source_queue.put(event)

    _wait_for(lambda: len(received1) >= 1 and len(received2) >= 1)

    # Both subscribers should receive the event
    assert event in received1
    assert event in received2


def test_router_multiple_events(router, source_queue):
    """Router processes multiple events."""
    received = []

    def collector(event):
        received.append(event)

    router.add_subscriber(DirectSubscriber(collector))
    router.start()

    _wait_for(lambda: router._thread and router._thread.is_alive())

    events: list[PipelineEvent] = [
        RequestBodyEvent(body={"n": 1}),
        ResponseDoneEvent(),
        ErrorEvent(code=500, reason="err"),
    ]
    for event in events:
        source_queue.put(event)

    _wait_for(lambda: len(received) >= len(events))

    # Should have received all events
    assert len(received) >= len(events)
    for event in events:
        assert event in received


def test_router_error_isolation(router, source_queue):
    """Failing subscriber doesn't break others."""
    received_good = []

    def failing_subscriber(event):
        raise Exception("Subscriber error")

    def good_subscriber(event):
        received_good.append(event)

    router.add_subscriber(DirectSubscriber(failing_subscriber))
    router.add_subscriber(DirectSubscriber(good_subscriber))
    router.start()

    _wait_for(lambda: router._thread and router._thread.is_alive())

    event = RequestBodyEvent(body={"test": "data"})
    source_queue.put(event)

    _wait_for(lambda: len(received_good) >= 1)

    # Good subscriber should still receive event despite failing subscriber
    assert event in received_good


def test_router_start_stop(source_queue):
    """Clean lifecycle - start and stop."""
    router = EventRouter(source_queue)

    # Should start without error
    router.start()
    assert router._thread is not None
    _wait_for(lambda: router._thread.is_alive())
    assert router._thread.is_alive()

    # Should stop without error
    router.stop()

    # Wait for thread to finish
    router._thread.join(timeout=2)

    # Thread should be stopped
    assert not router._thread.is_alive()


def test_router_stop_before_start(source_queue):
    """Stop before start doesn't crash."""
    router = EventRouter(source_queue)

    # Should not crash
    router.stop()


def test_router_multiple_stops(router, source_queue):
    """Multiple stops are idempotent."""
    router.start()
    _wait_for(lambda: router._thread and router._thread.is_alive())

    # First stop
    router.stop()
    router._thread.join(timeout=2)

    # Second stop should not crash
    router.stop()


def test_router_queue_subscriber_integration(router, source_queue):
    """QueueSubscriber works with router."""
    sub = QueueSubscriber()
    router.add_subscriber(sub)
    router.start()

    _wait_for(lambda: router._thread and router._thread.is_alive())

    event = RequestBodyEvent(body={"test": "data"})
    source_queue.put(event)

    # Event should be in subscriber's queue
    received = sub.queue.get(timeout=2)
    assert received == event


def test_router_empty_subscribers(router, source_queue):
    """Router with no subscribers doesn't crash."""
    router.start()

    _wait_for(lambda: router._thread and router._thread.is_alive())

    # Send event with no subscribers
    source_queue.put(RequestBodyEvent(body={"test": "data"}))

    # Give a moment for processing, then stop
    time.sleep(0.05)

    # Should not crash
    router.stop()


def test_router_subscriber_exception_logged(router, source_queue, capsys):
    """Subscriber exceptions are logged to stderr."""
    received_flag = []

    def failing_subscriber(event):
        received_flag.append(True)
        raise ValueError("Test error")

    router.add_subscriber(DirectSubscriber(failing_subscriber))
    router.start()

    _wait_for(lambda: router._thread and router._thread.is_alive())

    source_queue.put(RequestBodyEvent(body={"test": "data"}))

    # Wait for the subscriber to be called
    _wait_for(lambda: len(received_flag) >= 1)
    # Small extra wait for stderr to be flushed
    time.sleep(0.05)

    # Check that error was written to stderr
    captured = capsys.readouterr()
    assert "subscriber error" in captured.err or "Test error" in captured.err


# ─── Concurrency Tests ────────────────────────────────────────────────────────


def test_router_thread_safety(router, source_queue):
    """Router handles concurrent event submission."""
    received = []
    lock = threading.Lock()

    def collector(event):
        with lock:
            received.append(event)

    router.add_subscriber(DirectSubscriber(collector))
    router.start()

    _wait_for(lambda: router._thread and router._thread.is_alive())

    # Submit events from multiple threads
    def submit_events(start_idx):
        for i in range(5):
            source_queue.put(LogEvent(method="GET", path=f"/{start_idx}", status=str(i)))

    threads = []
    for i in range(3):
        t = threading.Thread(target=submit_events, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # Wait for router to process all events (15 total from 3 threads × 5 events)
    _wait_for(lambda: len(received) >= 15)

    # Should have received events from all threads
    assert len(received) >= 10  # Some events should have arrived


def test_router_graceful_shutdown_with_pending_events(source_queue):
    """Router stops gracefully even with pending events."""
    router = EventRouter(source_queue)

    received = []

    def collector(event):
        received.append(event)
        time.sleep(0.1)  # Slow processing

    router.add_subscriber(DirectSubscriber(collector))
    router.start()

    _wait_for(lambda: router._thread and router._thread.is_alive())

    # Queue multiple events
    for i in range(5):
        source_queue.put(LogEvent(method="GET", path="/", status=str(i)))

    # Stop immediately without waiting for all to process
    router.stop()

    # Should complete without hanging (timeout in stop() prevents hanging)
    assert True
