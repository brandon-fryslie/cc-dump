"""Message capture for Textual in-process tests.

Callable class passed as message_hook to run_test().
Captures all Textual messages for later inspection.
"""

from textual.message import Message


class MessageCapture:
    """Captures Textual messages during run_test().

    Usage:
        capture = MessageCapture()
        async with run_app(message_hook=capture) as (pilot, app):
            ...
            assert len(capture.of_type("Resize")) > 0
    """

    def __init__(self):
        self._messages: list[Message] = []

    def __call__(self, message: Message) -> None:
        """Hook called by Textual for every message."""
        self._messages.append(message)

    @property
    def all(self) -> list[Message]:
        """All captured messages."""
        return list(self._messages)

    def of_type(self, type_name: str) -> list[Message]:
        """Filter messages by class name (string match avoids import coupling)."""
        return [m for m in self._messages if type(m).__name__ == type_name]

    def containing(self, predicate) -> list[Message]:
        """Filter messages by predicate function."""
        return [m for m in self._messages if predicate(m)]

    def clear(self) -> None:
        """Clear all captured messages."""
        self._messages.clear()
