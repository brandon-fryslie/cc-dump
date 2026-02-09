#!/usr/bin/env python3
"""
Generate granular Textual documentation - one file per widget/concept.

Creates small, focused files (~10-50KB each) so agents can quickly find
exactly what they need without reading irrelevant content.
"""

import subprocess
from pathlib import Path
from typing import Dict, List
import json

OUTPUT_DIR = Path(__file__).parent / "textual-docs"
REPO_DIR = Path(__file__).parent / "textual-repo"

# Subdirectories for organization
CORE_DIR = OUTPUT_DIR / "core"
WIDGETS_DIR = OUTPUT_DIR / "widgets"
SUPPORT_DIR = OUTPUT_DIR / "support"

# Core API files - most important for building apps
CORE_FILES = {
    "app": "src/textual/app.py",
    "widget": "src/textual/widget.py",
    "screen": "src/textual/screen.py",
    "containers": "src/textual/containers.py",
    "reactive": "src/textual/reactive.py",
    "binding": "src/textual/binding.py",
    "dom": "src/textual/dom.py",
    "events": "src/textual/events.py",
    "messages": "src/textual/messages.py",
    "worker": "src/textual/worker.py",
    "pilot": "src/textual/pilot.py",  # Testing
}

# Most commonly used widgets
KEY_WIDGETS = [
    "button", "input", "label", "static",
    "data_table", "text_area", "markdown",
    "select", "option_list", "checkbox", "switch",
    "list_view", "tree", "directory_tree",
    "tabs", "tabbed_content", "collapsible",
    "progress_bar", "loading_indicator", "sparkline",
    "header", "footer", "log", "pretty",
    "radio_button", "radio_set", "selection_list",
]

# Support modules grouped by purpose
SUPPORT_GROUPS = {
    "css": "src/textual/css/**/*",
    "styling": "src/textual/color.py,src/textual/theme.py,src/textual/design.py,src/textual/style.py",
    "geometry": "src/textual/geometry.py,src/textual/coordinate.py,src/textual/strip.py",
    "utils": "src/textual/keys.py,src/textual/suggester.py,src/textual/fuzzy.py,src/textual/validation.py",
}


def run_repomix(pattern: str, output_file: Path) -> Dict:
    """Generate compressed XML for a specific file pattern."""
    cmd = [
        "npx", "repomix",
        str(REPO_DIR),
        "--output", str(output_file),
        "--style", "xml",
        "--include", pattern,
        "--compress",
        "--quiet",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  ✗ FAILED: {output_file.name}")
        return {}

    size = output_file.stat().st_size
    size_kb = size / 1024
    return {
        "file": output_file.name,
        "size_bytes": size,
        "size_kb": round(size_kb, 1),
        "pattern": pattern,
    }


def generate_core_files() -> List[Dict]:
    """Generate one file per core API."""
    print("\n📦 Core API files:")
    CORE_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    for name, path in CORE_FILES.items():
        output = CORE_DIR / f"{name}.xml"
        print(f"  {name:20s}", end=" ", flush=True)
        result = run_repomix(path, output)
        if result:
            result["category"] = "core"
            result["name"] = name
            print(f"✓ ({result['size_kb']}KB)")
            results.append(result)

    return results


def generate_widget_files() -> List[Dict]:
    """Generate one file per key widget."""
    print("\n🎨 Widget files:")
    WIDGETS_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    for widget in KEY_WIDGETS:
        output = WIDGETS_DIR / f"{widget}.xml"
        pattern = f"src/textual/widgets/_{widget}.py"

        print(f"  {widget:20s}", end=" ", flush=True)
        result = run_repomix(pattern, output)

        if result:
            result["category"] = "widget"
            result["name"] = widget
            print(f"✓ ({result['size_kb']}KB)")
            results.append(result)
        else:
            # Try alternate naming (e.g., DataTable vs data_table)
            alt_name = widget.replace("_", "")
            pattern = f"src/textual/widgets/_{alt_name}.py"
            result = run_repomix(pattern, output)
            if result:
                result["category"] = "widget"
                result["name"] = widget
                print(f"✓ ({result['size_kb']}KB)")
                results.append(result)

    return results


def generate_support_files() -> List[Dict]:
    """Generate grouped support module files."""
    print("\n🔧 Support modules:")
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    for name, pattern in SUPPORT_GROUPS.items():
        output = SUPPORT_DIR / f"{name}.xml"
        print(f"  {name:20s}", end=" ", flush=True)
        result = run_repomix(pattern, output)

        if result:
            result["category"] = "support"
            result["name"] = name
            print(f"✓ ({result['size_kb']}KB)")
            results.append(result)

    return results


def cleanup_old_files():
    """Remove old flat-structure files."""
    base_dir = Path(__file__).parent

    # Remove old monolithic files
    patterns = ["textual-*.xml", "core-*.xml", "widget-*.xml", "support-*.xml"]
    removed = []

    for pattern in patterns:
        for f in base_dir.glob(pattern):
            f.unlink()
            removed.append(f.name)

    if removed:
        print(f"\n🗑️  Removed {len(removed)} old flat-structure files")


def generate_index(results: List[Dict]):
    """Generate index and manifest."""
    # Group by category
    by_category = {}
    for r in results:
        cat = r["category"]
        by_category.setdefault(cat, []).append(r)

    # Calculate totals
    total_files = len(results)
    total_kb = sum(r["size_kb"] for r in results)

    index_md = f"""# Textual Documentation - Granular Reference

**{total_files} focused files, {total_kb:.0f}KB total**

Organized in subdirectories:
- `core/` - Essential APIs for building apps
- `widgets/` - One file per widget
- `support/` - Grouped utility modules

Each file is small (10-50KB) and focused on a single concept.

## Core API ({len(by_category.get('core', []))} files)

Location: `textual-docs/core/`

"""

    for item in sorted(by_category.get("core", []), key=lambda x: x["name"]):
        name = item["name"]
        size = item["size_kb"]
        index_md += f"- `{name}.xml` ({size}KB)\n"

    index_md += f"""
## Widgets ({len(by_category.get('widget', []))} files)

Location: `textual-docs/widgets/`

"""

    for item in sorted(by_category.get("widget", []), key=lambda x: x["name"]):
        name = item["name"]
        size = item["size_kb"]
        index_md += f"- `{name}.xml` ({size}KB)\n"

    index_md += f"""
## Support Modules ({len(by_category.get('support', []))} files)

Location: `textual-docs/support/`

"""

    for item in sorted(by_category.get("support", []), key=lambda x: x["name"]):
        name = item["name"]
        size = item["size_kb"]
        index_md += f"- `{name}.xml` ({size}KB)\n"

    index_md += """
## Usage Examples

**Building a simple app:**
```python
# Read:
#   textual-docs/core/app.xml
#   textual-docs/core/widget.xml
#   textual-docs/widgets/button.xml
#   textual-docs/widgets/input.xml
```

**Working with DataTable:**
```python
# Read:
#   textual-docs/widgets/data_table.xml
#   textual-docs/core/reactive.xml
```

**Styling and themes:**
```python
# Read:
#   textual-docs/support/css.xml
#   textual-docs/support/styling.xml
```

## Generation

```bash
# First time: clone repo locally
git clone --depth 1 https://github.com/textualize/textual.git textual-repo

# Generate docs
python3 generate_granular_docs.py
```
"""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "INDEX.md").write_text(index_md)
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(results, indent=2))

    print(f"\n✓ Generated INDEX.md and manifest.json")
    print(f"\n📊 Summary: {total_files} files, {total_kb:.0f}KB total")
    print(f"   Average: {total_kb/total_files:.1f}KB per file")


def main():
    if not REPO_DIR.exists():
        print(f"❌ Error: {REPO_DIR} not found")
        print(f"   Run: git clone --depth 1 https://github.com/textualize/textual.git textual-repo")
        return 1

    print("🔨 Generating granular Textual documentation...")
    print(f"   Using: {REPO_DIR}")

    cleanup_old_files()

    results = []
    results.extend(generate_core_files())
    results.extend(generate_widget_files())
    results.extend(generate_support_files())

    generate_index(results)

    print(f"\n✅ Done! Check INDEX.md for details")
    return 0


if __name__ == "__main__":
    exit(main())
