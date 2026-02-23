"""Side-channel purpose-level analytics.

// [LAW:one-source-of-truth] Per-purpose rollups are owned here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PurposeUsage:
    runs: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    output_tokens: int = 0
    input_tokens: int = 0


class SideChannelAnalytics:
    """In-memory purpose-level usage rollups."""

    def __init__(self) -> None:
        self._by_purpose: dict[str, PurposeUsage] = {}

    def record(
        self,
        *,
        purpose: str,
        input_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        row = self._by_purpose.get(purpose)
        if row is None:
            row = PurposeUsage()
            self._by_purpose[purpose] = row
        row.runs += 1
        row.input_tokens += input_tokens
        row.cache_read_tokens += cache_read_tokens
        row.cache_creation_tokens += cache_creation_tokens
        row.output_tokens += output_tokens

    def snapshot(self) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for purpose, row in self._by_purpose.items():
            result[purpose] = {
                "runs": row.runs,
                "input_tokens": row.input_tokens,
                "cache_read_tokens": row.cache_read_tokens,
                "cache_creation_tokens": row.cache_creation_tokens,
                "output_tokens": row.output_tokens,
            }
        return result

