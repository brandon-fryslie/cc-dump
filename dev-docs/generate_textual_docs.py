#!/usr/bin/env python3
"""
Generate focused Textual documentation files organized by module.

This script generates compressed XML documentation for each major subdirectory
in the Textual repository, making it easy for agents to find exactly what they
need without reading excess content.

Usage:
    python generate_textual_docs.py
"""

import subprocess
import json
from pathlib import Path
from typing import Dict, List

REPO_URL = "https://github.com/textualize/textual"
OUTPUT_DIR = Path(__file__).parent
LOCAL_REPO = OUTPUT_DIR / "textual-repo"

# Major modules to extract (subdirectories under src/textual/)
SRC_MODULES = [
    "widgets",      # All built-in widgets
    "css",          # CSS parser and styling
    "_layout",      # Layout system (internal but important)
    "renderables",  # Rich renderables
]

# Top-level src/textual/ files (important APIs)
SRC_ROOT_FILES = [
    "app.py",
    "widget.py",
    "screen.py",
    "containers.py",
    "reactive.py",
    "message.py",
    "message_pump.py",
    "binding.py",
    "dom.py",
    "events.py",
    "worker.py",
    "pilot.py",  # Testing
]


def run_repomix(include_pattern: str, output_file: Path, compress: bool = True) -> Dict:
    """Run repomix and return statistics."""
    # Use local repo if available, otherwise use remote
    if LOCAL_REPO.exists():
        cmd = [
            "npx", "repomix",
            str(LOCAL_REPO),
            "--output", str(output_file),
            "--style", "xml",
            "--include", include_pattern,
            "--quiet",
        ]
    else:
        cmd = [
            "npx", "repomix",
            "--remote", REPO_URL,
            "--output", str(output_file),
            "--style", "xml",
            "--include", include_pattern,
            "--quiet",
        ]

    if compress:
        cmd.append("--compress")

    print(f"Generating {output_file.name}... ", end="", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"FAILED")
        print(result.stderr)
        return {}

    # Extract token count from output
    size = output_file.stat().st_size
    size_mb = size / (1024 * 1024)
    print(f"✓ ({size_mb:.1f}MB)")

    return {
        "file": output_file.name,
        "size_bytes": size,
        "size_mb": round(size_mb, 2),
        "pattern": include_pattern,
    }


def generate_module_docs() -> List[Dict]:
    """Generate documentation for each major module."""
    results = []

    # Generate docs for each src/textual/ subdirectory
    for module in SRC_MODULES:
        output_file = OUTPUT_DIR / f"textual-{module.replace('_', '')}.xml"
        pattern = f"src/textual/{module}/**/*"
        result = run_repomix(pattern, output_file, compress=True)
        if result:
            result["category"] = "module"
            result["module"] = module
            results.append(result)

    # Generate docs for important root files
    root_patterns = ",".join(f"src/textual/{f}" for f in SRC_ROOT_FILES)
    output_file = OUTPUT_DIR / "textual-core.xml"
    result = run_repomix(root_patterns, output_file, compress=True)
    if result:
        result["category"] = "core"
        result["description"] = "Core APIs: App, Widget, Screen, Reactive, etc."
        results.append(result)

    # Keep the examples as-is (small enough)
    output_file = OUTPUT_DIR / "textual-examples.xml"
    result = run_repomix("examples/**/*", output_file, compress=False)
    if result:
        result["category"] = "examples"
        result["description"] = "Example applications"
        results.append(result)

    return results


def generate_index(results: List[Dict]):
    """Generate an index file documenting what's available."""
    index_content = """# Textual Documentation Index

This directory contains focused, compressed documentation for the Textual TUI framework,
organized by module for easy reference.

## Files

"""

    # Group by category
    by_category = {}
    for r in results:
        cat = r.get("category", "other")
        by_category.setdefault(cat, []).append(r)

    for category in ["core", "module", "examples"]:
        if category not in by_category:
            continue

        items = by_category[category]
        index_content += f"### {category.title()}\n\n"

        for item in items:
            name = item["file"]
            size = item["size_mb"]
            desc = item.get("description", item.get("pattern", ""))
            index_content += f"- **{name}** ({size}MB) - {desc}\n"

        index_content += "\n"

    index_content += """## Usage

Each file contains compressed XML documentation extracted via Tree-sitter parsing,
showing class definitions, function signatures, and docstrings without full implementation.

For agents/LLMs: Read the specific module file you need instead of loading all source code.

## Generation

To regenerate these files:
```bash
python generate_textual_docs.py
```
"""

    index_path = OUTPUT_DIR / "INDEX.md"
    index_path.write_text(index_content)
    print(f"\n✓ Generated {index_path.name}")

    # Also write JSON manifest
    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(results, indent=2))
    print(f"✓ Generated {manifest_path.name}")


def cleanup_old_files():
    """Remove the old monolithic files."""
    old_files = [
        "textual-src-compressed.xml",
        "textual-src-full.xml",
        "textual-tests-compressed.xml",
        "textual-tests-full.xml",
        "textual-examples-compressed.xml",
        "textual-examples-full.xml",
    ]

    for fname in old_files:
        path = OUTPUT_DIR / fname
        if path.exists():
            path.unlink()
            print(f"Removed old file: {fname}")


def main():
    print("Generating focused Textual documentation...\n")

    # Check for local repo
    if LOCAL_REPO.exists():
        print(f"Using local repo: {LOCAL_REPO}")
    else:
        print(f"Local repo not found. Will clone from: {REPO_URL}")
        print("To use local repo, run: git clone --depth 1 {REPO_URL} textual-repo\n")

    # Clean up old monolithic files
    cleanup_old_files()
    print()

    # Generate new focused files
    results = generate_module_docs()

    # Generate index
    generate_index(results)

    print(f"\n✓ Done! Generated {len(results)} files in {OUTPUT_DIR}")
    print(f"\nSee INDEX.md for details.")


if __name__ == "__main__":
    main()
