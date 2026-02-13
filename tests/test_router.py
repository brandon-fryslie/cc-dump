"""Unit tests for router.py - event distribution."""

import queue
import threading
import time

import pytest

from cc_dump.router import DirectSubscriber, EventRouter, QueueSubscriber
from cc_dump.event_types import (
    PipelineEvent,
    RequestBodyEvent,
    ResponseDoneEvent,
    ErrorEvent,
    LogEvent,
)


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

    # Give router time to start
    time.sleep(0.1)

    event = RequestBodyEvent(body={"test": "data"})
    source_queue.put(event)

    # Wait for router to process
    time.sleep(0.2)

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

    time.sleep(0.1)

    events: list[PipelineEvent] = [
        RequestBodyEvent(body={"n": 1}),
        ResponseDoneEvent(),
        ErrorEvent(code=500, reason="err"),
    ]
    for event in events:
        source_queue.put(event)

    # Wait for processing
    time.sleep(0.3)

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

    time.sleep(0.1)

    event = RequestBodyEvent(body={"test": "data"})
    source_queue.put(event)

    # Wait for processing
    time.sleep(0.2)

    # Good subscriber should still receive event despite failing subscriber
    assert event in received_good


def test_router_start_stop(source_queue):
    """Clean lifecycle - start and stop."""
    router = EventRouter(source_queue)

    # Should start without error
    router.start()
    assert router._thread is not None
    assert router._thread.is_alive()

    time.sleep(0.1)

    # Should stop without error
    router.stop()

    # Wait for thread to finish
    time.sleep(0.3)

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
    time.sleep(0.1)

    # First stop
    router.stop()
    time.sleep(0.2)

    # Second stop should not crash
    router.stop()


def test_router_queue_subscriber_integration(router, source_queue):
    """QueueSubscriber works with router."""
    sub = QueueSubscriber()
    router.add_subscriber(sub)
    router.start()

    time.sleep(0.1)

    event = RequestBodyEvent(body={"test": "data"})
    source_queue.put(event)

    # Wait for router to process and forward
    time.sleep(0.2)

    # Event should be in subscriber's queue
    received = sub.queue.get(timeout=1)
    assert received == event


def test_router_empty_subscribers(router, source_queue):
    """Router with no subscribers doesn't crash."""
    router.start()

    time.sleep(0.1)

    # Send event with no subscribers
    source_queue.put(RequestBodyEvent(body={"test": "data"}))

    time.sleep(0.2)

    # Should not crash
    router.stop()


def test_router_subscriber_exception_logged(router, source_queue, capsys):
    """Subscriber exceptions are logged to stderr."""

    def failing_subscriber(event):
        raise ValueError("Test error")

    router.add_subscriber(DirectSubscriber(failing_subscriber))
    router.start()

    time.sleep(0.1)

    source_queue.put(RequestBodyEvent(body={"test": "data"}))

    # Wait for processing
    time.sleep(0.2)

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

    time.sleep(0.1)

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

    # Wait for router to process all events
    time.sleep(0.5)

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

    time.sleep(0.1)

    # Queue multiple events
    for i in range(5):
        source_queue.put(LogEvent(method="GET", path="/", status=str(i)))

    # Stop immediately without waiting for all to process
    router.stop()

    # Should complete without hanging (timeout in stop() prevents hanging)
    assert True
