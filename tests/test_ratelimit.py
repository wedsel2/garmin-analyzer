from garmin_analyzer.ratelimit import FailureLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_blocks_after_the_limit_and_frees_when_the_period_has_passed() -> None:
    clock = Clock()
    limiter = FailureLimiter(limit=2, period_seconds=60, clock=clock)

    assert limiter.attempt("a")
    clock.now = 30
    assert limiter.attempt("a")
    assert not limiter.attempt("a")
    assert limiter.attempt("b")

    clock.now = 61
    assert limiter.attempt("a")
    assert not limiter.attempt("a")
    clock.now = 200
    assert limiter.attempt("c")
    assert list(limiter._failures) == ["c"]


def test_a_refused_attempt_does_not_extend_the_block() -> None:
    clock = Clock()
    limiter = FailureLimiter(limit=1, period_seconds=60, clock=clock)
    limiter.attempt("a")

    clock.now = 59
    assert not limiter.attempt("a")

    clock.now = 61
    assert limiter.attempt("a")


def test_forgive_takes_back_one_attempt_and_reset_all_of_a_key() -> None:
    limiter = FailureLimiter(limit=2, period_seconds=60)
    for key in ("a", "a", "b", "b"):
        limiter.attempt(key)

    limiter.forgive("a")
    limiter.forgive("unknown")
    limiter.reset("b")

    assert limiter.attempt("a")
    assert not limiter.attempt("a")
    assert limiter.attempt("b")
    assert limiter.attempt("b")
