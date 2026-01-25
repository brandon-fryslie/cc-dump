"""Display facade — single entry point for all terminal output.

Reloaded by the consumer loop on file changes. All stdout/stderr writes
happen here. No module-level mutable state.
"""

import sys

from cc_dump.colors import BOLD, DIM, GREEN, RED, RESET, SEPARATOR
from cc_dump.formatting import format_request, format_response_event
from cc_dump.formatting_ansi import render_blocks, render_block
from datetime import datetime


def _timestamp():
    """Generate a timestamp string for headers."""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def handle(event, state):
    """Dispatch an event tuple to the appropriate renderer."""
    kind = event[0]

    if kind == "request":
        body = event[1]
        blocks = format_request(body, state)
        output = render_blocks(blocks)
        sys.stdout.write(output + "\n")
        sys.stdout.flush()

    elif kind == "response_start":
        sys.stdout.write("\n" + SEPARATOR + "\n")
        sys.stdout.write(BOLD + GREEN + " RESPONSE " + RESET + DIM + " ({})".format(_timestamp()) + RESET + "\n")
        sys.stdout.write(SEPARATOR + "\n")
        sys.stdout.flush()

    elif kind == "response_event":
        event_type, data = event[1], event[2]
        blocks = format_response_event(event_type, data)
        for block in blocks:
            rendered = render_block(block)
            if rendered:
                # TextDeltaBlock renders inline (no trailing newline)
                # Check if this is a text delta event
                from cc_dump.formatting import TextDeltaBlock
                if isinstance(block, TextDeltaBlock):
                    sys.stdout.write(rendered)
                else:
                    sys.stdout.write(rendered + "\n")
                sys.stdout.flush()

    elif kind == "response_done":
        sys.stdout.write("\n")
        sys.stdout.flush()

    elif kind == "error":
        code, reason = event[1], event[2]
        sys.stdout.write(RED + "\n  [HTTP {} {}]".format(code, reason) + RESET + "\n")
        sys.stdout.flush()

    elif kind == "proxy_error":
        err = event[1]
        sys.stdout.write(RED + "\n  [PROXY ERROR: {}]".format(err) + RESET + "\n")
        sys.stdout.flush()

    elif kind == "log":
        command, path, status = event[1], event[2], event[3]
        sys.stderr.write(DIM + "  {} {} {}\n".format(command, path, status) + RESET)
        sys.stderr.flush()
