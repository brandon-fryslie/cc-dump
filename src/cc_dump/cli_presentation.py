"""Pure CLI presentation helpers.

// [LAW:locality-or-seam] CLI formatting is isolated from IO/data-access modules.
"""

from __future__ import annotations

from cc_dump.io.sessions import RecordingInfo, format_size


def _format_recording_created(created: str) -> str:
    """Format timestamp for compact CLI table display."""
    if "T" not in created:
        return created
    return created.split("T")[0] + " " + created.split("T")[1].split("+")[0].split(".")[0]


def render_recordings_list(recordings: list[RecordingInfo]) -> str:
    """Render recordings list as a plain-text table.

    // [LAW:dataflow-not-control-flow] Rendering always executes; output varies by input rows.
    """
    if not recordings:
        return "No recordings found.\n"

    header = (
        f"{'SESSION':<20} {'PROVIDER':<12} {'CREATED':<22} "
        f"{'ENTRIES':<10} {'SIZE':<12} {'FILE':<50}"
    )
    lines = [f"Found {len(recordings)} recording(s):", "", header, "-" * 127]

    for rec in recordings:
        created = _format_recording_created(rec["created"])
        size_str = format_size(rec["size_bytes"])
        filename = rec["filename"]
        session_name = rec.get("session_name") or "(flat)"
        provider = rec.get("provider") or "(mixed)"
        lines.append(
            f"{session_name:<20} {provider:<12} {created:<22} "
            f"{rec['entry_count']:<10} {size_str:<12} {filename:<50}"
        )

    lines.append("")
    return "\n".join(lines)
