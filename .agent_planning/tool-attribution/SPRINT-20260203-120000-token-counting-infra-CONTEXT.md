# Implementation Context: token-counting-infra
Generated: 2026-02-03-120000
Source: EVALUATION-20260202.md
Confidence: HIGH

## Token Counter Module

### New file: `src/cc_dump/token_counter.py`

**Imports needed:**
```python
import json
import ssl
import sys
import urllib.request
import urllib.error
```

**No cc_dump imports** -- this is a leaf module.

**Function signatures:**
```python
def count_tokens(text: str, model: str, api_key: str, base_url: str = "https://api.anthropic.com") -> int:
    """Count tokens for text using Anthropic count_tokens API. Returns 0 on any failure."""

def count_tokens_batch(items: list[str], model: str, api_key: str, base_url: str = "https://api.anthropic.com") -> list[int]:
    """Count tokens for multiple text items. Returns list of counts (0 on failure per item)."""
```

**API request format** (Anthropic /v1/messages/count_tokens):
```json
POST /v1/messages/count_tokens
Headers: {"x-api-key": "<key>", "content-type": "application/json", "anthropic-version": "2023-06-01"}
Body: {"model": "<model>", "messages": [{"role": "user", "content": "<text>"}]}
Response: {"input_tokens": 42}
```

**Error handling pattern** -- follow proxy.py style:
```python
try:
    ctx = ssl.create_default_context()
    resp = urllib.request.urlopen(req, context=ctx, timeout=5)
except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
    return 0
```

**Add to hot-reload reloadable list** in `CLAUDE.md` and `hot_reload.py` if needed. Since it has no state, it is trivially reloadable but likely does not need to be in the reload list since `store.py` is stable.

### Test file: `tests/test_token_counter.py`

Pattern to follow: see `tests/test_analysis.py` for pure function test style.

Mock `urllib.request.urlopen` using `unittest.mock.patch`.

---

## Schema Migration

### File: `src/cc_dump/schema.py`
**Lines to modify:**

**Line 13**: Change `SCHEMA_VERSION = 2` to `SCHEMA_VERSION = 3`

**Lines 74-82**: Update CREATE TABLE to include new columns:
```sql
CREATE TABLE IF NOT EXISTS tool_invocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id INTEGER NOT NULL REFERENCES turns(id),
    tool_name TEXT NOT NULL,
    tool_use_id TEXT NOT NULL,
    input_bytes INTEGER NOT NULL DEFAULT 0,
    result_bytes INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    result_tokens INTEGER NOT NULL DEFAULT 0,
    is_error INTEGER NOT NULL DEFAULT 0
);
```

**Add migration function** after `_create_tables()`:
```python
def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Add token count columns to tool_invocations."""
    cursor = conn.execute("PRAGMA table_info(tool_invocations)")
    columns = {row[1] for row in cursor.fetchall()}
    if "input_tokens" not in columns:
        conn.execute("ALTER TABLE tool_invocations ADD COLUMN input_tokens INTEGER NOT NULL DEFAULT 0")
    if "result_tokens" not in columns:
        conn.execute("ALTER TABLE tool_invocations ADD COLUMN result_tokens INTEGER NOT NULL DEFAULT 0")
    conn.commit()
```

**Call migration from `init_db()`** after `_create_tables(conn)`:
```python
_migrate_v2_to_v3(conn)
```

---

## API Key Capture

### File: `src/cc_dump/proxy.py`
**Lines 59-65**: After `body = json.loads(body_bytes)`, before emitting request event, capture API key:

```python
# Capture API key for sideband calls (one-time)
if not hasattr(self, '_auth_emitted') or not self._auth_emitted:
    api_key = self.headers.get("x-api-key", "")
    if not api_key:
        auth_header = self.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:]
    if api_key:
        self.event_queue.put(("auth_hint", api_key))
        ProxyHandler._auth_emitted = True
```

Note: `_auth_emitted` is a class-level flag so it fires once across all handler instances.

### File: `src/cc_dump/store.py`
**Line 28**: Add `self._api_key = None` to `__init__`

**Line 43-46**: In `_handle()`, add a new case:
```python
if kind == "auth_hint":
    self._api_key = event[1]
    return
```

### File: `src/cc_dump/router.py`
No changes needed -- the router fans out all events to all subscribers. The `auth_hint` event will reach `SQLiteWriter.on_event()` naturally.

---

## Wire Token Counting into store.py

### File: `src/cc_dump/store.py`
**Line 1-2**: Add import:
```python
from cc_dump.token_counter import count_tokens
```

Note: `store.py` is a stable boundary module. However, `token_counter` is a leaf utility module, so a direct import is acceptable (no hot-reload concern since store.py itself is not reloaded).

**Lines 138-145**: In `_commit_turn()`, after `invocations = correlate_tools(messages)`, add token counting:

Current code:
```python
for inv in invocations:
    self._conn.execute("""
        INSERT INTO tool_invocations (turn_id, tool_name, tool_use_id, input_bytes, result_bytes, is_error)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (turn_id, inv.name, inv.tool_use_id, inv.input_bytes, inv.result_bytes, int(inv.is_error)))
```

New code:
```python
for inv in invocations:
    # Count actual tokens via API (0 if unavailable)
    input_tokens = 0
    result_tokens = 0
    if self._api_key and self._current_model:
        input_tokens = count_tokens(
            inv.input_str if hasattr(inv, 'input_str') else "",
            self._current_model, self._api_key
        )
        result_tokens = count_tokens(
            inv.result_str if hasattr(inv, 'result_str') else "",
            self._current_model, self._api_key
        )

    self._conn.execute("""
        INSERT INTO tool_invocations (turn_id, tool_name, tool_use_id, input_bytes, result_bytes, input_tokens, result_tokens, is_error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (turn_id, inv.name, inv.tool_use_id, inv.input_bytes, inv.result_bytes, input_tokens, result_tokens, int(inv.is_error)))
```

**Important**: `ToolInvocation` currently does not store `input_str` / `result_str`. We need to either:
1. Add these fields to `ToolInvocation` in `analysis.py` (preferred -- keeps raw text for token counting)
2. Or re-extract from the request body in `_commit_turn()`

**Recommended**: Add `input_str: str = ""` and `result_str: str = ""` to `ToolInvocation` dataclass (analysis.py line 148-157) and populate them in `correlate_tools()` (they are already computed as local variables `input_str` and `result_str` on lines 210-220 but not stored).

### File: `src/cc_dump/analysis.py`
**Lines 148-157**: Add fields to ToolInvocation:
```python
@dataclass
class ToolInvocation:
    """A matched tool_use -> tool_result pair."""
    tool_use_id: str = ""
    name: str = ""
    input_bytes: int = 0
    result_bytes: int = 0
    input_tokens_est: int = 0
    result_tokens_est: int = 0
    input_str: str = ""    # NEW: raw input text for token counting
    result_str: str = ""   # NEW: raw result text for token counting
    is_error: bool = False
```

**Lines 208-230**: In `correlate_tools()`, store the strings:
```python
invocations.append(ToolInvocation(
    tool_use_id=tool_use_id,
    name=use_block.get("name", "?"),
    input_bytes=input_bytes,
    result_bytes=result_bytes,
    input_tokens_est=estimate_tokens(input_str),
    result_tokens_est=estimate_tokens(result_str),
    input_str=input_str,      # NEW
    result_str=result_str,     # NEW
    is_error=block.get("is_error", False),
))
```

---

## db_queries.py Cleanup

### File: `src/cc_dump/db_queries.py`
**Lines 79-107**: Update `get_tool_invocations()` query to fetch real token columns instead of estimating:

```sql
SELECT
    ti.tool_name,
    ti.tool_use_id,
    ti.input_bytes,
    ti.result_bytes,
    ti.input_tokens,
    ti.result_tokens,
    ti.is_error
FROM tool_invocations ti
JOIN turns t ON ti.turn_id = t.id
WHERE t.session_id = ?
ORDER BY ti.id
```

And update the row parsing to use real values:
```python
tool_name, tool_use_id, input_bytes, result_bytes, input_tokens, result_tokens, is_error = row
invocations.append(ToolInvocation(
    tool_use_id=tool_use_id,
    name=tool_name,
    input_bytes=input_bytes,
    result_bytes=result_bytes,
    input_tokens_est=input_tokens,   # Real tokens now, not estimates
    result_tokens_est=result_tokens,  # Real tokens now, not estimates
    is_error=bool(is_error),
))
```

**Remove** the `estimate_tokens` import from line 12 (no longer needed in this module).

---

## Adjacent Code Patterns

**HTTP request pattern** (from `proxy.py` lines 75-79):
```python
req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
ctx = ssl.create_default_context()
resp = urllib.request.urlopen(req, context=ctx, timeout=300)
```

**Error handling pattern** (from `store.py` lines 33-41):
```python
try:
    self._handle(event)
except Exception as e:
    sys.stderr.write("[db] error: {}\n".format(e))
    traceback.print_exc(file=sys.stderr)
```

**Test mock pattern** (from `tests/test_analysis.py`):
Tests are pure function tests with no mocks needed for analysis. For token_counter, use:
```python
from unittest.mock import patch, MagicMock
@patch('cc_dump.token_counter.urllib.request.urlopen')
def test_count_tokens_success(mock_urlopen):
    ...
```
