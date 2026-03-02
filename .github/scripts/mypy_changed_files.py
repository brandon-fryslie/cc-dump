#!/usr/bin/env python3
"""Run mypy on changed Python files and fail only for changed-file errors."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def _git_ref_exists(ref: str) -> bool:
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        check=False,
        capture_output=True,
        text=True,
    )
    return probe.returncode == 0


def _resolve_base_ref() -> str:
    """Pick an appropriate base ref for changed-file diffing."""
    base_branch = os.environ.get("GITHUB_BASE_REF", "").strip()
    if base_branch:
        # // [LAW:one-source-of-truth] PR base branch is the canonical diff anchor.
        fetch = subprocess.run(
            ["git", "fetch", "--no-tags", "--prune", "--depth=1", "origin", base_branch],
            check=False,
            capture_output=True,
            text=True,
        )
        if fetch.returncode != 0:
            sys.stdout.write(fetch.stdout)
            sys.stderr.write(fetch.stderr)
            raise RuntimeError("failed to fetch origin/{}".format(base_branch))
        return "origin/{}".format(base_branch)

    for ref in ("origin/master", "origin/main", "master", "main"):
        if _git_ref_exists(ref):
            return ref
    return "HEAD~1"


def _changed_python_files(base_ref: str) -> list[str]:
    merge_base = _run(["git", "merge-base", base_ref, "HEAD"]).stdout.strip()
    if not merge_base:
        raise RuntimeError("unable to compute merge base against {}".format(base_ref))
    changed = _run(["git", "diff", "--name-only", "{}..HEAD".format(merge_base)]).stdout.splitlines()
    # // [LAW:locality-or-seam] Restrict to product Python sources for stable mypy scope.
    return sorted(
        path
        for path in changed
        if path.endswith(".py") and path.startswith("src/")
    )


def _changed_file_errors(mypy_output: str, changed: set[str]) -> set[str]:
    pattern = re.compile(r"^(?P<path>[^:\n]+\.py):\d+(?::\d+)?: error:", re.MULTILINE)
    paths = set()
    for match in pattern.finditer(mypy_output):
        paths.add(Path(match.group("path")).as_posix())
    return paths.intersection(changed)


def main() -> int:
    base_ref = _resolve_base_ref()
    changed = _changed_python_files(base_ref)
    if not changed:
        print("No changed Python files under src/; skipping mypy changed-file gate.")
        return 0

    print("Changed Python files (mypy gate):")
    for path in changed:
        print(" - {}".format(path))

    cmd = ["uv", "run", "mypy", *changed]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    output = "{}{}".format(proc.stdout, proc.stderr)

    changed_set = set(changed)
    blocking = _changed_file_errors(output, changed_set)
    if blocking:
        print(output, end="")
        print("\nChanged-file mypy errors detected:")
        for path in sorted(blocking):
            print(" - {}".format(path))
        return 1

    if proc.returncode != 0:
        # // [LAW:dataflow-not-control-flow] CI outcome is derived from changed-file error set.
        print(output, end="")
        print(
            "\nNon-zero mypy exit code without changed-file errors; treating as pass "
            "for changed-file gate."
        )
        return 0

    print(output, end="")
    print("Changed-file mypy gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
