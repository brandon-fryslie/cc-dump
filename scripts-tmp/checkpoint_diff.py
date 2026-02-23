#!/usr/bin/env python3
"""Standalone checkpoint diff script for HAR recordings.

Usage:
  python scripts/checkpoint_diff.py --har /path/to/file.har --before 10 --after 43
  python scripts/checkpoint_diff.py --har /path/to/file.har --suggest 3
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from cc_dump.har_checkpoint_diff import (
    diff_checkpoints,
    find_interesting_pairs,
    load_har_entries,
    render_diff_markdown,
    snapshot_from_har_entry,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diff two checkpoints from a HAR recording.")
    parser.add_argument("--har", required=True, help="Path to .har file")
    parser.add_argument("--before", type=int, help="Entry index for checkpoint A")
    parser.add_argument("--after", type=int, help="Entry index for checkpoint B")
    parser.add_argument(
        "--list",
        type=int,
        default=0,
        help="List first N entries with index/session/model/message_count",
    )
    parser.add_argument(
        "--suggest",
        type=int,
        default=0,
        help="Show top-N interesting checkpoint pairs from this HAR",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of markdown",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    har_path = Path(args.har)
    entries = load_har_entries(har_path)
    if not entries:
        sys.stderr.write(f"No HAR entries found in {har_path}\n")
        return 2

    snapshots = [snapshot_from_har_entry(entry, idx) for idx, entry in enumerate(entries)]

    if args.list > 0:
        limit = min(args.list, len(snapshots))
        for snapshot in snapshots[:limit]:
            print(
                "\t".join(
                    [
                        str(snapshot.entry_index),
                        snapshot.started_at,
                        snapshot.session_id,
                        snapshot.model,
                        str(snapshot.message_count),
                    ]
                )
            )
        return 0

    if args.suggest > 0:
        diffs = find_interesting_pairs(snapshots, limit=args.suggest)
        if args.json:
            print(json.dumps([diff.to_dict() for diff in diffs], indent=2, sort_keys=True))
            return 0
        for i, diff in enumerate(diffs):
            if i > 0:
                print("\n---\n")
            print(render_diff_markdown(diff))
        return 0

    if args.before is None or args.after is None:
        parser.error("--before and --after are required when --suggest is not used.")

    if args.before < 0 or args.before >= len(snapshots):
        parser.error(f"--before index out of range (0-{len(snapshots)-1}): {args.before}")
    if args.after < 0 or args.after >= len(snapshots):
        parser.error(f"--after index out of range (0-{len(snapshots)-1}): {args.after}")
    if args.after <= args.before:
        parser.error("--after must be greater than --before.")

    diff = diff_checkpoints(snapshots[args.before], snapshots[args.after])
    if args.json:
        print(json.dumps(diff.to_dict(), indent=2, sort_keys=True))
    else:
        print(render_diff_markdown(diff))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
