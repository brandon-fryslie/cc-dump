# Implementation Context: unit-tests

## Files to Create

### tests/test_analysis.py

```python
"""Unit tests for analysis.py - token estimation, budgets, tool correlation."""

import pytest
from cc_dump.analysis import (
    estimate_tokens,
    compute_turn_budget,
    TurnBudget,
    correlate_tools,
    aggregate_tools,
    ToolInvocation,
    tool_result_breakdown,
)

# Fixtures for sample data
@pytest.fixture
def simple_request():
    return {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": "Hello"}]
    }

@pytest.fixture
def request_with_tools():
    return {
        "model": "claude-3-opus",
        "max_tokens": 4096,
        "tools": [{"name": "read_file", "description": "..."}],
        "messages": [...]
    }
```

### tests/test_formatting.py

```python
"""Unit tests for formatting.py - block generation and content tracking."""

import pytest
from cc_dump.formatting import (
    format_request,
    format_response_event,
    track_content,
    make_diff_lines,
    # Block types
    HeaderBlock, MetadataBlock, RoleBlock, TextContentBlock,
    TrackedContentBlock, StreamInfoBlock, TextDeltaBlock,
)

@pytest.fixture
def fresh_state():
    """Fresh state dict for content tracking."""
    return {
        "positions": {},
        "known_hashes": {},
        "next_id": 0,
        "next_color": 0,
        "request_counter": 0,
    }
```

### tests/test_router.py

```python
"""Unit tests for router.py - event distribution."""

import pytest
import queue
import threading
import time
from cc_dump.router import (
    EventRouter,
    QueueSubscriber,
    DirectSubscriber,
)

@pytest.fixture
def source_queue():
    return queue.Queue()

@pytest.fixture
def router(source_queue):
    r = EventRouter(source_queue)
    yield r
    r.stop()  # Cleanup
```

## Key Testing Patterns

### 1. Analysis Tests - Pure Functions
```python
def test_estimate_tokens_empty():
    assert estimate_tokens("") == 1  # Minimum is 1

def test_estimate_tokens_calculates_correctly():
    # 4 chars per token heuristic
    assert estimate_tokens("a" * 100) == 25
```

### 2. Formatting Tests - State Mutation
```python
def test_track_content_new(fresh_state):
    result = track_content("Hello world", "system:0", fresh_state)
    assert result[0] == "new"
    assert "system:0" in fresh_state["positions"]

def test_track_content_ref(fresh_state):
    # First call
    track_content("Hello", "system:0", fresh_state)
    # Second call with same content at different position
    result = track_content("Hello", "system:1", fresh_state)
    assert result[0] == "ref"
```

### 3. Router Tests - Threading
```python
def test_router_fanout(router, source_queue):
    received = []

    def collector(event):
        received.append(event)

    router.add_subscriber(DirectSubscriber(collector))
    router.start()

    source_queue.put(("test", "data"))
    time.sleep(0.1)  # Allow router to process

    assert len(received) == 1
    assert received[0] == ("test", "data")
```

## Edge Cases to Cover

### analysis.py
- Empty strings → min 1 token
- Unicode text → bytes/4 heuristic still works
- Missing fields in request → no crash
- Nested content blocks → all counted
- Tool result as list vs string → both handled

### formatting.py
- Empty request body → still produces blocks
- System as string vs list → both handled
- Content hash collision → handled gracefully
- State reset between tests → use fixtures

### router.py
- Empty subscriber list → no crash
- Subscriber exception → isolated, others continue
- Stop before start → no crash
- Multiple stops → idempotent

## Test Commands

```bash
# Run all new unit tests
uv run pytest tests/test_analysis.py tests/test_formatting.py tests/test_router.py -v

# Run with coverage
uv run pytest tests/test_analysis.py tests/test_formatting.py tests/test_router.py --cov=cc_dump.analysis --cov=cc_dump.formatting --cov=cc_dump.router

# Run fast (no E2E)
uv run pytest tests/ --ignore=tests/test_hot_reload.py -v
```
