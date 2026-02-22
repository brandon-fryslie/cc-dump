"""Local side-channel summary cache.

// [LAW:one-source-of-truth] Summary cache key/schema are centralized here.
// [LAW:single-enforcer] Cache file I/O happens only in this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


CACHE_SCHEMA_VERSION = 1
DEFAULT_MAX_ENTRIES = 2000


def get_summary_cache_path() -> Path:
    """Return local summary cache path."""
    cache_home = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    return Path(cache_home) / "cc-dump" / "summary-cache.json"


@dataclass(frozen=True)
class SummaryCacheEntry:
    key: str
    purpose: str
    prompt_version: str
    content_hash: str
    summary_text: str
    created_at: str


class SummaryCache:
    """Persistent local cache keyed by purpose + prompt_version + content hash."""

    def __init__(self, path: Path | None = None, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._path = path or get_summary_cache_path()
        self._max_entries = max(1, int(max_entries))
        self._entries: dict[str, SummaryCacheEntry] = {}
        self._load()

    def make_key(self, *, purpose: str, prompt_version: str, content: str) -> str:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return f"{purpose}:{prompt_version}:{content_hash}"

    def get(self, key: str) -> SummaryCacheEntry | None:
        return self._entries.get(key)

    def put(self, *, key: str, purpose: str, prompt_version: str, content: str, summary_text: str) -> None:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self._entries[key] = SummaryCacheEntry(
            key=key,
            purpose=purpose,
            prompt_version=prompt_version,
            content_hash=content_hash,
            summary_text=summary_text,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._enforce_max_entries()
        self._persist()

    def _enforce_max_entries(self) -> None:
        if len(self._entries) <= self._max_entries:
            return
        # Oldest-first eviction by created_at.
        ordered = sorted(
            self._entries.items(),
            key=lambda item: item[1].created_at,
        )
        to_drop = len(ordered) - self._max_entries
        for key, _entry in ordered[:to_drop]:
            self._entries.pop(key, None)

    def _load(self) -> None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self._entries = {}
            return
        if not isinstance(payload, dict):
            self._entries = {}
            return
        entries = payload.get("entries", {})
        if not isinstance(entries, dict):
            self._entries = {}
            return
        loaded: dict[str, SummaryCacheEntry] = {}
        for key, raw in entries.items():
            if not isinstance(key, str) or not isinstance(raw, dict):
                continue
            try:
                loaded[key] = SummaryCacheEntry(
                    key=key,
                    purpose=str(raw.get("purpose", "")),
                    prompt_version=str(raw.get("prompt_version", "")),
                    content_hash=str(raw.get("content_hash", "")),
                    summary_text=str(raw.get("summary_text", "")),
                    created_at=str(raw.get("created_at", "")),
                )
            except Exception:
                continue
        self._entries = loaded

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": CACHE_SCHEMA_VERSION,
            "entries": {
                key: {
                    "purpose": entry.purpose,
                    "prompt_version": entry.prompt_version,
                    "content_hash": entry.content_hash,
                    "summary_text": entry.summary_text,
                    "created_at": entry.created_at,
                }
                for key, entry in self._entries.items()
            },
        }
        fd, tmp_path = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
