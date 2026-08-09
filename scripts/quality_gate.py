#!/usr/bin/env python3
"""Regression ratchet for lint and cyclomatic complexity.

This gate is designed to allow pre-existing debt while preventing new debt.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE_DIR = REPO_ROOT / ".quality_gate"
LINT_BASELINE_FILE = "lint_baseline.json"
COMPLEXITY_BASELINE_FILE = "complexity_baseline.json"
BASELINE_SCHEMA_VERSION = 1

# TUI code must narrow types explicitly rather than lean on cc_dump.core.coerce
# helpers, so illegal states are rejected at the seam instead of laundered downstream.
# [LAW:types-are-the-program] The seam, not a coercion helper, is where narrowing belongs.
TUI_DIR = REPO_ROOT / "src" / "cc_dump" / "tui"
COERCE_MODULE = "cc_dump.core.coerce"
# A coercion-helper call is `coerce_<name>(...)` — never the underscore-prefixed
# `_coerce_...` local helpers that legitimately narrow at a boundary.
COERCE_CALL_RE = re.compile(r"^coerce_[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class Baseline:
    counts: dict[str, int]
    generated_at: str


def _run_json_command(cmd: list[str], label: str) -> Any:
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(f"ERROR: {label} failed with exit code {proc.returncode}", file=sys.stderr)
        if proc.stderr.strip():
            print(proc.stderr.strip(), file=sys.stderr)
        elif proc.stdout.strip():
            print(proc.stdout.strip(), file=sys.stderr)
        raise SystemExit(1)

    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError as exc:
        print(f"ERROR: {label} produced invalid JSON: {exc}", file=sys.stderr)
        print((proc.stdout or "")[:500], file=sys.stderr)
        raise SystemExit(1) from exc


def _normalize_path(path: str) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.relative_to(REPO_ROOT)
        except ValueError:
            pass
    return p.as_posix()


def _sorted_counts(counter: Counter[str]) -> dict[str, int]:
    return {k: counter[k] for k in sorted(counter.keys())}


def collect_lint_counts() -> dict[str, int]:
    """Collect ruff diagnostics and aggregate by file+code.

    // [LAW:one-source-of-truth] Lint regression identity is file+code count.
    """
    # [LAW:one-source-of-truth] Use the ruff pinned in the locked project env, never
    # `--with ruff` (which re-resolves the latest PyPI ruff and makes the gate verdict
    # depend on release timing rather than on the code).
    data = _run_json_command(
        [
            "uv",
            "run",
            "ruff",
            "check",
            "src",
            "tests",
            "--output-format",
            "json",
            "--exit-zero",
        ],
        "ruff check",
    )

    counter: Counter[str] = Counter()
    for item in data:
        code = str(item.get("code") or "UNKNOWN")
        filename = _normalize_path(str(item.get("filename") or "<unknown>"))
        counter[f"{filename}::{code}"] += 1
    return _sorted_counts(counter)


def _complexity_key(path: str, block: dict[str, Any]) -> str:
    block_type = str(block.get("type") or "")
    name = str(block.get("name") or "<unknown>")
    if block_type == "method":
        class_name = str(block.get("classname") or "<unknown>")
        return f"{path}::method::{class_name}.{name}"
    return f"{path}::function::{name}"


def collect_complexity_scores() -> dict[str, int]:
    """Collect radon CC scores for functions/methods only.

    // [LAW:behavior-not-structure] Gate tracks externally visible complexity metric,
    // not source layout details like line numbers.
    """
    # [LAW:one-source-of-truth] Same as ruff: use the pinned radon from the locked env
    # so complexity scores are reproducible. This gate is a required check; an unpinned
    # scorer would let a radon release turn it red on unchanged code.
    data = _run_json_command(
        [
            "uv",
            "run",
            "radon",
            "cc",
            "-j",
            "-s",
            "src/cc_dump",
        ],
        "radon cc",
    )

    scores: dict[str, int] = {}
    for raw_path, blocks in data.items():
        path = _normalize_path(str(raw_path))
        for block in blocks:
            block_type = str(block.get("type") or "")
            if block_type not in {"function", "method"}:
                continue
            key = _complexity_key(path, block)
            complexity = int(block.get("complexity") or 0)
            prev = scores.get(key)
            if prev is None or complexity > prev:
                scores[key] = complexity
    return {k: scores[k] for k in sorted(scores.keys())}


def _load_baseline(path: Path) -> Baseline:
    if not path.exists():
        print(
            f"ERROR: baseline file missing: {path}\n"
            "Run: uv run python scripts/quality_gate.py refresh",
            file=sys.stderr,
        )
        raise SystemExit(1)

    data = json.loads(path.read_text())
    version = data.get("schema_version")
    if version != BASELINE_SCHEMA_VERSION:
        print(
            f"ERROR: unsupported baseline schema version {version} in {path}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    raw_counts = data.get("counts")
    if not isinstance(raw_counts, dict):
        print(f"ERROR: invalid counts payload in {path}", file=sys.stderr)
        raise SystemExit(1)

    counts: dict[str, int] = {}
    for key, value in raw_counts.items():
        counts[str(key)] = int(value)
    generated_at = str(data.get("generated_at") or "")
    return Baseline(counts=counts, generated_at=generated_at)


def _write_baseline(path: Path, counts: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _print_count_summary(label: str, baseline: dict[str, int], current: dict[str, int]) -> None:
    baseline_total = sum(baseline.values())
    current_total = sum(current.values())
    delta = current_total - baseline_total
    print(f"{label}: baseline={baseline_total} current={current_total} delta={delta:+d}")


def check_lint_regressions(baseline: dict[str, int], current: dict[str, int]) -> list[tuple[str, int, int]]:
    regressions: list[tuple[str, int, int]] = []
    for key, current_count in current.items():
        baseline_count = baseline.get(key, 0)
        if current_count > baseline_count:
            regressions.append((key, baseline_count, current_count))
    return sorted(regressions, key=lambda item: (item[0], item[2] - item[1]))


def check_complexity_regressions(
    baseline: dict[str, int],
    current: dict[str, int],
    new_function_cap: int,
) -> tuple[list[tuple[str, int, int]], list[tuple[str, int]]]:
    increased: list[tuple[str, int, int]] = []
    new_too_complex: list[tuple[str, int]] = []

    for key, score in current.items():
        if key in baseline:
            baseline_score = baseline[key]
            if score > baseline_score:
                increased.append((key, baseline_score, score))
            continue
        if score > new_function_cap:
            new_too_complex.append((key, score))

    increased.sort(key=lambda item: (item[2] - item[1], item[0]), reverse=True)
    new_too_complex.sort(key=lambda item: (item[1], item[0]), reverse=True)
    return increased, new_too_complex


def _is_forbidden_coerce_node(node: ast.AST) -> bool:
    """Whether an AST node is a forbidden cc_dump.core.coerce import or helper call."""
    if isinstance(node, ast.ImportFrom):
        return node.module == COERCE_MODULE
    if isinstance(node, ast.Import):
        return any(alias.name == COERCE_MODULE for alias in node.names)
    if isinstance(node, ast.Call):
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None
        )
        return name is not None and COERCE_CALL_RE.match(name) is not None
    return False


def collect_forbidden_tui_coerce_usage(
    tui_dir: Path = TUI_DIR, repo_root: Path = REPO_ROOT
) -> list[str]:
    """Collect forbidden coercion-helper usage within TUI modules.

    Returns ``"path:lineno:text"`` for every offending line, sorted by path then
    line number. The scan is AST-based, so a ``coerce_x(...)`` mention inside a
    comment, docstring, or string literal is not a violation — only real code is.
    The scanned root is a parameter so the rule is testable against fixtures rather
    than only the live tree.

    // [LAW:single-enforcer] This gate is the sole policy enforcer for the restriction.
    // [LAW:types-are-the-program] Match code structure, not text; text-context
    //   false positives are unrepresentable by construction.
    // [LAW:effects-at-boundaries] Pure filesystem read; no external tool dependency.
    """
    offenses: set[tuple[str, int]] = set()
    line_text: dict[tuple[str, int], str] = {}
    for path in sorted(tui_dir.rglob("*.py")):
        rel = path.relative_to(repo_root).as_posix()
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        # ast.parse raises SyntaxError on a broken file — surface it loudly.
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if _is_forbidden_coerce_node(node):
                lineno = getattr(node, "lineno", 0)
                key = (rel, lineno)
                offenses.add(key)
                line_text.setdefault(key, lines[lineno - 1].strip() if lineno else "")
    return [f"{rel}:{lineno}:{line_text[(rel, lineno)]}" for rel, lineno in sorted(offenses)]


def cmd_refresh(args: argparse.Namespace) -> int:
    baseline_dir = Path(args.baseline_dir)
    lint_counts = collect_lint_counts()
    complexity_scores = collect_complexity_scores()

    lint_path = baseline_dir / LINT_BASELINE_FILE
    complexity_path = baseline_dir / COMPLEXITY_BASELINE_FILE
    _write_baseline(lint_path, lint_counts)
    _write_baseline(complexity_path, complexity_scores)

    print(f"Wrote lint baseline: {lint_path}")
    print(f"Wrote complexity baseline: {complexity_path}")
    print(f"Lint entries: {len(lint_counts)}")
    print(f"Complexity entries: {len(complexity_scores)}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    baseline_dir = Path(args.baseline_dir)
    lint_path = baseline_dir / LINT_BASELINE_FILE
    complexity_path = baseline_dir / COMPLEXITY_BASELINE_FILE

    lint_baseline = _load_baseline(lint_path)
    complexity_baseline = _load_baseline(complexity_path)

    lint_current = collect_lint_counts()
    complexity_current = collect_complexity_scores()

    lint_regressions = check_lint_regressions(lint_baseline.counts, lint_current)
    increased_complexity, new_complexity = check_complexity_regressions(
        complexity_baseline.counts,
        complexity_current,
        args.new_function_cap,
    )

    _print_count_summary("Lint diagnostics", lint_baseline.counts, lint_current)
    _print_count_summary("Complexity points", complexity_baseline.counts, complexity_current)

    has_failure = False
    if lint_regressions:
        has_failure = True
        print("\nFAIL: lint regressions detected (file::code count increased):")
        for key, old, new in lint_regressions[:50]:
            print(f"  - {key}: {old} -> {new}")
        if len(lint_regressions) > 50:
            print(f"  ... and {len(lint_regressions) - 50} more")

    if increased_complexity:
        has_failure = True
        print("\nFAIL: complexity increased for existing functions/methods:")
        for key, old, new in increased_complexity[:50]:
            print(f"  - {key}: {old} -> {new}")
        if len(increased_complexity) > 50:
            print(f"  ... and {len(increased_complexity) - 50} more")

    if new_complexity:
        has_failure = True
        print(
            "\nFAIL: new functions/methods exceed complexity cap "
            f"(>{args.new_function_cap}):"
        )
        for key, score in new_complexity[:50]:
            print(f"  - {key}: {score}")
        if len(new_complexity) > 50:
            print(f"  ... and {len(new_complexity) - 50} more")

    forbidden_tui_coerce_usage = collect_forbidden_tui_coerce_usage()
    if forbidden_tui_coerce_usage:
        has_failure = True
        print(
            "\nFAIL: coercion helpers are forbidden in src/cc_dump/tui "
            "(use explicit type validation/narrowing instead):"
        )
        for line in forbidden_tui_coerce_usage[:50]:
            print(f"  - {line}")
        if len(forbidden_tui_coerce_usage) > 50:
            print(f"  ... and {len(forbidden_tui_coerce_usage) - 50} more")

    if has_failure:
        return 1

    print("\nPASS: no new lint or complexity regressions.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline-dir",
        default=str(DEFAULT_BASELINE_DIR),
        help=f"Directory containing baseline files (default: {DEFAULT_BASELINE_DIR})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh = subparsers.add_parser("refresh", help="Refresh lint/complexity baselines")
    refresh.set_defaults(func=cmd_refresh)

    check = subparsers.add_parser("check", help="Check for regressions against baseline")
    check.add_argument(
        "--new-function-cap",
        type=int,
        default=10,
        help="Max CC allowed for newly introduced functions/methods",
    )
    check.set_defaults(func=cmd_check)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
