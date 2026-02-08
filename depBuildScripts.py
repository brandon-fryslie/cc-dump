#!/usr/bin/env python3
"""List (and optionally rebuild/approve) global pnpm deps with install scripts."""

import json
import subprocess
import sys
from pathlib import Path

INSTALL_SCRIPTS = {"preinstall", "install", "postinstall", "prepare"}
USAGE = """\
Usage: {prog} [--rebuild | --approve] <package-name>

  (no flag)   List deps with install scripts
  --rebuild   Run their build scripts via pnpm rebuild
  --approve   Add them to onlyBuiltDependencies in the global pnpm-workspace.yaml\
"""


def collect_deps(node, deps=None):
    if deps is None:
        deps = {}
    for name, info in (node.get("dependencies") or {}).items():
        key = f"{name}@{info.get('version', '?')}"
        if key not in deps:
            deps[key] = info.get("path")
            collect_deps(info, deps)
    return deps


def resolve_path(path):
    """Resolve package path, working around pnpm reporting wrong prefix."""
    p = Path(path)
    if p.exists():
        return p
    # pnpm list reports /…/node_modules/.pnpm/pkg/… but actual layout is /…/.pnpm/pkg/…
    s = str(p)
    if "/node_modules/.pnpm/" in s:
        alt = Path(s.replace("/node_modules/.pnpm/", "/.pnpm/", 1))
        if alt.exists():
            return alt
    return p


def check_scripts(path):
    if not path:
        return {}
    pkg_json = resolve_path(path) / "package.json"
    if not pkg_json.exists():
        return {}
    try:
        scripts = json.loads(pkg_json.read_text()).get("scripts", {})
    except (json.JSONDecodeError, OSError):
        return {}
    return {k: v for k, v in scripts.items() if k in INSTALL_SCRIPTS}


def global_dir():
    r = subprocess.run(["pnpm", "root", "-g"], capture_output=True, text=True)
    # pnpm root -g returns e.g. /Users/x/Library/pnpm/global/5/node_modules
    return str(Path(r.stdout.strip()).parent)


def find_packages_with_scripts(target):
    result = subprocess.run(
        ["pnpm", "list", "-g", "--json", "--depth", "99", "--long"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"pnpm list failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(result.stdout)
    root = data[0] if isinstance(data, list) else data
    top_deps = root.get("dependencies", {})

    if target not in top_deps:
        print(f"Package '{target}' not found in global pnpm packages.", file=sys.stderr)
        print(f"Available: {', '.join(sorted(top_deps.keys()))}", file=sys.stderr)
        sys.exit(1)

    pkg = top_deps[target]
    all_deps = {f"{target}@{pkg.get('version', '?')}": pkg.get("path")}
    collect_deps(pkg, all_deps)

    found = []
    for dep_key, dep_path in sorted(all_deps.items()):
        scripts = check_scripts(dep_path)
        if scripts:
            found.append((dep_key, scripts))
    return found


def do_rebuild(found):
    gdir = global_dir()
    names = [key.rsplit("@", 1)[0] for key, _ in found]
    print(f"Rebuilding: {', '.join(names)}")
    r = subprocess.run(
        ["pnpm", "--dir", gdir, "rebuild", *names],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(f"rebuild failed: {r.stderr}", file=sys.stderr)
        sys.exit(1)
    print("Done.")


def do_approve(found):
    gdir = global_dir()
    ws_path = Path(gdir) / "pnpm-workspace.yaml"
    names = sorted({key.rsplit("@", 1)[0] for key, _ in found})

    # Read existing workspace yaml if present (simple enough to not need a yaml lib)
    existing = set()
    if ws_path.exists():
        for line in ws_path.read_text().splitlines():
            stripped = line.strip().lstrip("- ").strip("'\"")
            if stripped and not stripped.endswith(":"):
                existing.add(stripped)

    to_add = [n for n in names if n not in existing]
    all_approved = sorted(existing | set(names))

    lines = ["onlyBuiltDependencies:"]
    for name in all_approved:
        lines.append(f"  - {name}")
    lines.append("")

    ws_path.write_text("\n".join(lines))
    if to_add:
        print(f"Approved in {ws_path}: {', '.join(to_add)}")
    else:
        print(f"Already approved: {', '.join(names)}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = {a for a in sys.argv[1:] if a.startswith("-")}

    if not args or flags - {"--rebuild", "--approve"}:
        print(USAGE.format(prog=sys.argv[0]), file=sys.stderr)
        sys.exit(1)

    target = args[0]
    found = find_packages_with_scripts(target)

    if not found:
        print(f"No dependencies of '{target}' have install scripts.")
        return

    for dep_key, scripts in found:
        print(dep_key)
        for name, cmd in scripts.items():
            print(f"  {name}: {cmd}")
    print(f"\n{len(found)} package(s)")

    if "--rebuild" in flags:
        print()
        do_rebuild(found)

    if "--approve" in flags:
        print()
        do_approve(found)


if __name__ == "__main__":
    main()
