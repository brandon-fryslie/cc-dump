"""HAR replay module — loads HAR files and converts them to pipeline events.

This module is the single enforcer for HAR shape validation. The raw nested
JSON of a HAR 1.2 file enters at one boundary (`load_har`) and is parsed into
typed `_HarFile` / `_HarEntry` Pydantic models, then projected into a public
`ReplayPair` dataclass that downstream code consumes by name. No code outside
this module asks "does this HAR entry have a request body?" — the type already
encodes the answer.

// [LAW:single-enforcer] All HAR-shape validation lives here. The 12+ scattered
//   "if 'X' not in dict" checks the legacy parser had are absorbed into the
//   private Pydantic models below.
// // [LAW:dataflow-not-control-flow] load_har is a straight pipe over typed
//   entries. The only branching is the load-bearing "skip vs raise" decision
//   that distinguishes per-entry recoverable failures from file-level fatal
//   structure errors, and the final "no valid entries" rule.
// // [LAW:one-source-of-truth] ReplayPair is the canonical "HAR pair" shape
//   for the codebase. cli.py, tui/app.py, experiments/subagent_enrichment.py
//   and the test suites all consume the same dataclass.
// // [LAW:no-defensive-null-guards] Headers without name+value cannot exist
//   in a parsed _HarEntry — the entry containing them is rejected at the
//   single boundary, not silently dropped at the consumer.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

import cc_dump.providers
from cc_dump.pipeline.event_types import (
    PipelineEvent,
    RequestBodyEvent,
    RequestHeadersEvent,
    ResponseCompleteEvent,
    ResponseHeadersEvent,
    event_envelope,
    new_request_id,
)

logger = logging.getLogger(__name__)


# ─── ReplayPair: the public canonical type ───────────────────────────────────


@dataclass(frozen=True)
class ReplayPair:
    """One fully-validated HAR request/response pair, ready for replay.

    Constructed only by `load_har` after the per-entry parser has accepted the
    raw HAR entry. Downstream consumers read fields by name; positional
    unpacking is forbidden because there is no positional contract.
    """
    request_headers: dict[str, str]
    request_body: dict[str, object]
    response_status: int
    response_headers: dict[str, str]
    complete_message: dict[str, object]
    provider: str


# ─── Private Pydantic models for HAR 1.2 shape ───────────────────────────────
# These collapse 12+ nested-dict-key checks into one `model_validate` call.
# All `extra="ignore"` so unrelated HAR fields don't fail parsing. _HarEntry
# uses `extra="allow"` so the existing `_cc_dump` provider metadata stays
# accessible to `infer_provider_from_har_entry`.


# `extra="allow"` everywhere so unrelated HAR fields round-trip through
# model_dump() — `infer_provider_from_har_entry` reads `request.url` and the
# entry-level `_cc_dump` metadata, neither of which we model explicitly.


class _HarHeader(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    value: str


class _HarPostData(BaseModel):
    model_config = ConfigDict(extra="allow")
    text: str


class _HarRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    headers: list[_HarHeader] = []
    postData: _HarPostData


class _HarContent(BaseModel):
    model_config = ConfigDict(extra="allow")
    text: str


class _HarResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: int = 200
    headers: list[_HarHeader] = []
    content: _HarContent


class _HarEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
    request: _HarRequest
    response: _HarResponse


class _HarLog(BaseModel):
    # // [LAW:dataflow-not-control-flow] entries is `list[dict]`, NOT
    # //   `list[_HarEntry]`, so per-entry validation happens in the loop
    # //   inside load_har (wrapped in _SkipEntry). One bad entry must not
    # //   reject the whole file — that's load-bearing replay behavior.
    model_config = ConfigDict(extra="allow")
    entries: list[dict]


class _HarFile(BaseModel):
    model_config = ConfigDict(extra="allow")
    log: _HarLog


# ─── _SkipEntry: per-entry recoverable failure ───────────────────────────────


class _SkipEntry(Exception):
    """Raised by per-entry parsing when one entry is unrecoverable but the
    overall file should continue. Replaces the legacy 3-type catch
    `(KeyError, JSONDecodeError, ValueError)`: there is now exactly one
    exception type per failure mode.
    """


# ─── load_har: SINGLE ENFORCER ───────────────────────────────────────────────


def load_har(path: str) -> list[ReplayPair]:
    """Load a HAR file and return a list of ReplayPair records.

    Raises:
        FileNotFoundError: file does not exist
        json.JSONDecodeError: file is not valid JSON
        ValidationError: HAR top-level structure is invalid (missing log,
            missing log.entries, entries not a list, etc.)
        ValueError: HAR file contained no valid entries

    Per-entry failures (missing required fields, malformed inner JSON, header
    objects without name+value, response not recognized as a complete message)
    are logged and skipped — the function returns whatever entries did parse.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    har_file = _HarFile.model_validate(raw)

    pairs: list[ReplayPair] = []
    for index, raw_entry in enumerate(har_file.log.entries):
        try:
            pairs.append(_pair_from_raw_entry(raw_entry))
        except _SkipEntry as exc:
            logger.warning("skipping HAR entry %s: %s", index, exc)

    if not pairs:
        raise ValueError("HAR file contains no valid entries")
    return pairs


def _pair_from_raw_entry(raw_entry: dict) -> ReplayPair:
    """Validate one HAR entry and project it into a ReplayPair.

    Raises _SkipEntry on any per-entry recoverable failure:
      * structural validation failure (missing required fields, wrong types,
        malformed header objects);
      * malformed inner JSON in request/response body text;
      * response shape not recognized for the inferred provider.
    """
    try:
        entry = _HarEntry.model_validate(raw_entry)
    except ValidationError as exc:
        raise _SkipEntry(str(exc)) from exc

    request_body = _decode_inner_json_object(
        entry.request.postData.text, field_name="request.postData.text",
    )
    complete_message = _decode_inner_json_object(
        entry.response.content.text, field_name="response.content.text",
    )

    request_headers = {h.name: h.value for h in entry.request.headers}
    response_headers = {h.name: h.value for h in entry.response.headers}

    # // [LAW:one-source-of-truth] HAR provider inference precedence is
    # //   centralized in providers.infer_provider_from_har_entry, which still
    # //   takes a raw dict — pass the original raw entry so the _cc_dump
    # //   metadata and request.url remain visible.
    provider = cc_dump.providers.infer_provider_from_har_entry(
        raw_entry,
        complete_message=complete_message,
    )

    if not cc_dump.providers.is_complete_response_for_provider(provider, complete_message):
        raise _SkipEntry(
            f"response is not a recognized complete message for provider={provider!r}"
        )

    return ReplayPair(
        request_headers=request_headers,
        request_body=request_body,
        response_status=entry.response.status,
        response_headers=response_headers,
        complete_message=complete_message,
        provider=provider,
    )


def _decode_inner_json_object(text: str, *, field_name: str) -> dict[str, object]:
    """Decode the inner JSON-object payload from a HAR `text` field.

    HAR stores request/response bodies as opaque text blobs; we still need to
    parse and shape-check them. This is the boundary parser for that inner
    layer. Failures collapse into one _SkipEntry — the per-entry try/except
    in load_har catches it.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _SkipEntry(f"{field_name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise _SkipEntry(f"{field_name} must decode to a JSON object")
    return payload


# ─── convert_to_events: ReplayPair -> typed pipeline events ──────────────────


def convert_to_events(pair: ReplayPair) -> list[PipelineEvent]:
    """Convert a validated ReplayPair into the typed pipeline event sequence
    that the live proxy emits for one request/response cycle.

    // [LAW:one-source-of-truth] Replay events use the exact same envelope
    //   shape as live-proxy events.
    """
    request_id = new_request_id()
    return [
        RequestHeadersEvent(
            headers=pair.request_headers,
            **event_envelope(request_id=request_id, seq=0, provider=pair.provider),
        ),
        RequestBodyEvent(
            body=pair.request_body,
            **event_envelope(request_id=request_id, seq=1, provider=pair.provider),
        ),
        ResponseHeadersEvent(
            status_code=pair.response_status,
            headers=pair.response_headers,
            **event_envelope(request_id=request_id, seq=2, provider=pair.provider),
        ),
        ResponseCompleteEvent(
            body=pair.complete_message,
            **event_envelope(request_id=request_id, seq=3, provider=pair.provider),
        ),
    ]


__all__ = ["ReplayPair", "load_har", "convert_to_events"]
