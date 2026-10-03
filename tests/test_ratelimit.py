from garmin_analyzer.ratelimit import FailureLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_blocks_after_the_limit_and_frees_when_the_period_has_passed() -> None:
    clock = Clock()
    limiter = FailureLimiter(limit=2, period_seconds=60, clock=clock)

    limiter.record_failure("a")
    assert not limiter.blocked("a")
    clock.now = 30
    limiter.record_failure("a")
    assert limiter.blocked("a")
    assert not limiter.blocked("b")

    clock.now = 61
    assert not limiter.blocked("a")
    clock.now = 91
    assert not limiter.blocked("a")
    assert limiter._failures == {}


def test_reset_clears_one_key() -> None:
    limiter = FailureLimiter(limit=1, period_seconds=60)
    limiter.record_failure("a")
    limiter.record_failure("b")

    limiter.reset("a")

    assert not limiter.blocked("a")
    assert limiter.blocked("b")
