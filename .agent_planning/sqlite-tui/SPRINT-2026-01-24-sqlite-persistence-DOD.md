# Definition of Done: sqlite-persistence
Generated: 2026-01-24

## Acceptance Criteria

1. **schema.py exists** with `init_db()` that creates all tables
2. **WAL mode** enabled on connection
3. **blobs table** stores content-addressed binary data with sha256 hash PK
4. **turns table** stores complete turn metadata (model, tokens, tools, timestamps)
5. **turn_blobs table** links turns to their extracted blobs with field paths
6. **turns_fts** provides full-text search on message text content
7. **store.py exists** with `SQLiteWriter` class
8. **SQLiteWriter.on_event()** accumulates request+response into complete turns
9. **Blobification**: strings >= 512 bytes extracted to blobs table, replaced with `{"__blob__": "<hash>"}`
10. **Blob dedup**: identical content stored once (hash-based)
11. **FTS indexing**: turn text content searchable via FTS5
12. **--db flag** in CLI with sensible default path
13. **--no-db flag** to disable persistence entirely
14. **Error resilience**: DB errors logged to stderr, don't crash the proxy
15. **Session tracking**: each cc-dump run gets a unique session_id

## Verification Method
- Run `cc-dump` with default --db, make several API requests
- `sqlite3 ~/.local/share/cc-dump/sessions.db "SELECT count(*) FROM turns"` shows correct row count
- `sqlite3 ... "SELECT count(*) FROM blobs"` shows deduplicated blobs
- `sqlite3 ... "SELECT * FROM turns_fts WHERE turns_fts MATCH 'some_term'"` returns matches
- Run with `--no-db`, verify no DB file created
- Kill proxy mid-request, verify DB is not corrupted (WAL recovery)
