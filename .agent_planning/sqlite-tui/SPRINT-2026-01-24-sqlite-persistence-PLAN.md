# Sprint: sqlite-persistence - SQLite Persistence Layer
Generated: 2026-01-24
Confidence: HIGH: 3, MEDIUM: 0, LOW: 0
Status: READY FOR IMPLEMENTATION

## Sprint Goal
Create a content-addressed SQLite persistence layer with blob deduplication and FTS5, wired as a DirectSubscriber to the EventRouter.

## Scope
**Deliverables:**
- `schema.py` — DDL, WAL setup, migrations, `init_db()`
- `store.py` — SQLiteWriter class (event accumulation, blobification, FTS indexing)
- CLI integration with `--db` flag

## Work Items

### P0: Create schema.py
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] `init_db(path) -> sqlite3.Connection` creates DB with WAL mode
- [ ] Creates `blobs` table: hash TEXT PK, content BLOB, byte_size INTEGER, created_at TEXT
- [ ] Creates `turns` table: id INTEGER PK, session_id TEXT, sequence_num INTEGER, timestamp TEXT, model TEXT, stop_reason TEXT, input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cache_creation_tokens INTEGER, tool_names TEXT (JSON array), request_json TEXT, response_json TEXT
- [ ] Creates `turn_blobs` table: turn_id INTEGER FK, blob_hash TEXT FK, field_path TEXT
- [ ] Creates `turns_fts` virtual table USING fts5(text_content, content=turns, content_rowid=id)
- [ ] Schema version tracking (simple pragma or meta table)
- [ ] All tables created idempotently (IF NOT EXISTS)

**Technical Notes:**
- WAL mode: `PRAGMA journal_mode=WAL` after connection
- `PRAGMA synchronous=NORMAL` for performance with WAL
- session_id: generated once per cc-dump invocation (uuid4 hex)
- FTS5 content sync: use triggers or manual insert

### P1: Create store.py with SQLiteWriter
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] `SQLiteWriter` class implements subscriber protocol (has `on_event(event)` method)
- [ ] Accumulates request body on "request" event
- [ ] Accumulates response events, extracts text content, stop_reason, usage stats
- [ ] On "response_done": commits a complete turn to DB
- [ ] Blobification: fields >= 512 bytes replaced with `{"__blob__": "<sha256>"}` in stored JSON, actual content in blobs table
- [ ] Blob deduplication: same content hash → reuse existing blob row
- [ ] FTS: concatenated message text inserted into turns_fts
- [ ] Extracts usage from message_start event (input_tokens, output_tokens, cache stats)
- [ ] Extracts tool names from request body tools list
- [ ] Handles errors gracefully (logs to stderr, doesn't crash proxy)

**Technical Notes:**
- Blobification walks the JSON structure, replaces large string values
- sha256 of content for blob hash (full hex, not truncated)
- SQLiteWriter.__init__(db_path): calls init_db(), stores connection
- Sequence number: auto-increment per session
- Tool names: extract from request body's tools array, store as JSON array string

### P2: Wire into cli.py
**Confidence: HIGH**
**Acceptance Criteria:**
- [ ] `--db` flag with default `~/.local/share/cc-dump/sessions.db`
- [ ] `--no-db` flag to disable persistence
- [ ] SQLiteWriter registered as DirectSubscriber on router
- [ ] DB directory created if it doesn't exist
- [ ] Session ID generated at startup, passed to SQLiteWriter

**Technical Notes:**
- `os.makedirs(os.path.dirname(db_path), exist_ok=True)`
- DirectSubscriber(writer.on_event) registered before router.start()
- Session ID: `uuid.uuid4().hex`

## Dependencies
- Sprint 2 (event-router) must be complete (need DirectSubscriber)

## Risks
- SQLite write blocking router thread: mitigated by WAL mode and small writes
- FTS5 availability: included in Python's sqlite3 module by default on most platforms
