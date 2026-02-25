import io
import queue

from cc_dump.pipeline.event_types import ProxyErrorEvent
from cc_dump.pipeline.proxy import ProxyHandler
from cc_dump.proxies.runtime import ProxyRuntime


class _RaisingPlugin:
    def handles_path(self, _request_path: str) -> bool:
        return True

    def handle_request(self, _context) -> bool:
        raise RuntimeError("boom")


class _FakeHandler:
    def __init__(self) -> None:
        self.event_queue = queue.Queue()
        self.command = "POST"
        self.headers = {}
        self.sent_status = None
        self.sent_headers: list[tuple[str, str]] = []
        self.wfile = io.BytesIO()

    def send_response(self, code: int) -> None:
        self.sent_status = code

    def send_header(self, key: str, value: str) -> None:
        self.sent_headers.append((key, value))

    def end_headers(self) -> None:
        pass


def test_provider_plugin_failure_isolated_to_502():
    runtime = ProxyRuntime()
    snapshot = runtime.update_from_settings(
        {
            "proxy_provider": "copilot",
            "proxy_anthropic_base_url": "https://api.anthropic.com",
        }
    )
    handler = _FakeHandler()

    handled = ProxyHandler._dispatch_provider_plugin(
        handler,
        provider_plugin=_RaisingPlugin(),
        request_id="req_1",
        request_path="/v1/messages",
        body={},
        runtime_snapshot=snapshot,
    )

    assert handled is True
    assert handler.sent_status == 502
    body_text = handler.wfile.getvalue().decode("utf-8", errors="replace")
    assert "Provider plugin 'copilot' failed" in body_text

    events = []
    while not handler.event_queue.empty():
        events.append(handler.event_queue.get_nowait())
    assert any(isinstance(event, ProxyErrorEvent) for event in events)
