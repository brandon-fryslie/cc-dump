"""Web server entry point using textual-serve.

This module provides a browser-based interface for cc-dump using textual-serve.
When launched, it starts a web server that runs cc-dump instances in the browser.
"""

from textual_serve.server import Server


def main():
    """Launch cc-dump web server using textual-serve."""
    # Create server that launches cc-dump command
    # Users can pass any cc-dump flags in the browser URL
    server = Server(
        command="cc-dump",
        host="localhost",
        port=8000,
        title="cc-dump - Claude Code API Monitor",
    )

    print("🌐 cc-dump web server starting...")
    print("   Visit http://localhost:8000 to access cc-dump in your browser")
    print("   Each browser session will launch an independent cc-dump instance")
    print()

    # Start serving (blocks until Ctrl+C)
    server.serve()


if __name__ == "__main__":
    main()
