"""App-layer error model types shared across projections and UI adaptation.

// [LAW:one-source-of-truth] ErrorItem shape is defined once outside tui modules.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorItem:
    id: str
    icon: str
    summary: str
