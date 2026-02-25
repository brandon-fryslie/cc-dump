from cc_dump.proxies.copilot.rate_limit import CopilotRateLimiter


def test_rate_limiter_allows_when_interval_disabled():
    limiter = CopilotRateLimiter()
    allowed, remaining = limiter.gate(min_interval_seconds=0, wait_on_limit=False)
    assert allowed is True
    assert remaining == 0.0


def test_rate_limiter_rejects_when_wait_disabled(monkeypatch):
    now = {"t": 100.0}

    def _monotonic():
        return now["t"]

    monkeypatch.setattr("cc_dump.proxies.copilot.rate_limit.time.monotonic", _monotonic)

    limiter = CopilotRateLimiter()
    first_allowed, first_remaining = limiter.gate(min_interval_seconds=10, wait_on_limit=False)
    assert first_allowed is True
    assert first_remaining == 0.0

    now["t"] = 103.5
    second_allowed, second_remaining = limiter.gate(min_interval_seconds=10, wait_on_limit=False)
    assert second_allowed is False
    assert round(second_remaining, 2) == 6.5


def test_rate_limiter_waits_when_configured(monkeypatch):
    now = {"t": 100.0}
    sleeps: list[float] = []

    def _monotonic():
        return now["t"]

    def _sleep(duration: float):
        sleeps.append(duration)
        now["t"] += duration

    monkeypatch.setattr("cc_dump.proxies.copilot.rate_limit.time.monotonic", _monotonic)
    monkeypatch.setattr("cc_dump.proxies.copilot.rate_limit.time.sleep", _sleep)

    limiter = CopilotRateLimiter()
    limiter.gate(min_interval_seconds=5, wait_on_limit=False)

    now["t"] = 102.0
    allowed, remaining = limiter.gate(min_interval_seconds=5, wait_on_limit=True)
    assert allowed is True
    assert round(remaining, 2) == 3.0
    assert len(sleeps) == 1
    assert round(sleeps[0], 2) == 3.0
