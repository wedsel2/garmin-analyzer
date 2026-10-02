"""Turn a real Garmin response into a synthetic test fixture.

    uv run scripts/scrub_fixture.py user_summary sleep_data

Reads .garmin-tokens/samples/<name>.json (local, personal) and writes
tests/fixtures/garmin/<name>.json (committed, public). The fixture keeps the
structure and value formats of the real response but none of its values:

  identifiers            replaced by small counters
  numbers                replaced by random numbers of similar size; small
                         negative whole numbers are kept, as Garmin uses them
                         to mean "not measured"
  dates and timestamps   moved to around 2026-01-15, with a random time offset
  text                   replaced by "redacted", except enum-like constants
  coordinates            zeroed
  long lists             cut to the first few items

Review the printed list of kept text values before committing a fixture.

It also writes .garmin-tokens/stats/<name>.json (local, not committed): for
every series of at least 10 numbers, the minimum, maximum and, when there are
only a few, the distinct values. That shows ranges, units and codes without
exposing the series itself. Single values are left out, as their range would
be the value.
"""

import json
import random
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

SAMPLES = Path(".garmin-tokens/samples")
FIXTURES = Path("tests/fixtures/garmin")
STATS = Path(".garmin-tokens/stats")
FAKE_DAY = date(2026, 1, 15)
MAX_ITEMS = 5
EPOCH_MS_MIN = 10**11
SENTINEL_MIN = -10
SERIES_MIN_LENGTH = 10
MAX_DISTINCT = 8

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME = re.compile(r"^(\d{4}-\d{2}-\d{2})([T ])(\d{2}:\d{2}:\d{2})(.*)$")
CONSTANT = re.compile(r"^[A-Z][A-Z0-9_]*$")
TOKEN = re.compile(r"^[a-z][A-Za-z0-9_.]{0,40}$")
IDENTIFIER_KEY = re.compile(r"(id|pk|uuid|guid|serial|number)$|profile", re.IGNORECASE)
COORDINATE_KEY = re.compile(r"lat|lon", re.IGNORECASE)
# Small integers under these keys are codes, not measurements.
CODE_KEY = re.compile(r"(index|version|typeid|count)$", re.IGNORECASE)


class Scrubber:
    def __init__(self, seed: str, newest: date) -> None:
        self.random = random.Random(seed)  # noqa: S311 - not used for security
        self.shift = timedelta(days=(FAKE_DAY - newest).days, minutes=self.random.randint(-90, 90))
        self.identifiers: dict[Any, int] = {}
        self.kept_text: set[str] = set()

    def identifier(self, value: Any) -> int:
        return self.identifiers.setdefault(value, len(self.identifiers) + 1)

    def scrub(self, value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {self.key(k): self.scrub(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self.scrub(item, key) for item in value[:MAX_ITEMS]]
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, str):
            return self.text(value, key)
        if isinstance(value, int):
            return self.integer(value, key)
        return self.decimal(value, key)

    def key(self, key: str) -> str:
        # Maps keyed by an id, such as a device id, or by a date.
        if key.isdigit():
            return str(self.identifier(key))
        return self.text(key, "") if DATE.match(key) else key

    def text(self, value: str, key: str) -> str:
        if DATE.match(value):
            return (date.fromisoformat(value) + timedelta(days=self.shift.days)).isoformat()
        match = DATETIME.match(value)
        if match:
            day, separator, clock, rest = match.groups()
            moved = datetime.fromisoformat(f"{day}T{clock}") + self.shift
            return f"{moved.date().isoformat()}{separator}{moved.time().isoformat()}{rest}"
        if IDENTIFIER_KEY.search(key):
            return f"id-{self.identifier(value)}"
        is_constant = CONSTANT.match(value) and "name" not in key.lower()
        is_token = TOKEN.match(value) and key.lower().endswith("key")
        if is_constant or is_token:
            self.kept_text.add(value)
            return value
        return "redacted"

    def integer(self, value: int, key: str) -> int:
        if abs(value) >= EPOCH_MS_MIN:
            return value + int(self.shift.total_seconds() * 1000)
        if IDENTIFIER_KEY.search(key):
            return self.identifier(value)
        if value == 0 or (CODE_KEY.search(key) and abs(value) < 100):
            return value
        # Drawn before the sentinel check so the other values of a fixture do
        # not depend on how many sentinels it contains.
        factor = self.random.uniform(0.5, 1.5)
        if is_sentinel(value):
            return value
        return round(value * factor) or 1

    def decimal(self, value: float, key: str) -> float:
        if COORDINATE_KEY.search(key):
            return 0.0
        factor = self.random.uniform(0.5, 1.5)
        if is_sentinel(value):
            return value
        return round(value * factor, 2)


def is_sentinel(value: float) -> bool:
    """Garmin marks unmeasured points with values such as -1 and -2."""
    return SENTINEL_MIN <= value < 0 and value == int(value)


def collect_series(value: Any, path: str, series: dict[str, list[float]]) -> None:
    """Gather the numbers found at each path, with list positions collapsed."""
    if isinstance(value, dict):
        for key, item in value.items():
            collect_series(item, f"{path}.{'*' if key.isdigit() else key}", series)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, list):
                # Pairs such as [timestamp, value] keep their position.
                for index, element in enumerate(item):
                    collect_series(element, f"{path}[][{index}]", series)
            else:
                collect_series(item, f"{path}[]", series)
    elif isinstance(value, int | float) and not isinstance(value, bool):
        series.setdefault(path, []).append(value)


def series_stats(real: Any) -> dict[str, dict[str, Any]]:
    series: dict[str, list[float]] = {}
    collect_series(real, "", series)
    stats: dict[str, dict[str, Any]] = {}
    for path, values in sorted(series.items()):
        if len(values) < SERIES_MIN_LENGTH or min(values) >= EPOCH_MS_MIN:
            continue
        entry: dict[str, Any] = {"count": len(values), "min": min(values), "max": max(values)}
        distinct = sorted(set(values))
        if len(distinct) <= MAX_DISTINCT:
            entry["distinct"] = distinct
        entry["sentinels"] = sorted({v for v in values if is_sentinel(v)})
        stats[path] = entry
    return stats


def newest_date(value: Any) -> date | None:
    """The latest day mentioned anywhere in the response, as a date or timestamp."""
    found: list[date] = []
    if isinstance(value, dict):
        found = [d for d in map(newest_date, value.values()) if d]
    elif isinstance(value, list):
        found = [d for d in map(newest_date, value) if d]
    elif isinstance(value, str) and (DATE.match(value) or DATETIME.match(value)):
        found = [date.fromisoformat(value[:10])]
    elif isinstance(value, int) and not isinstance(value, bool) and value >= EPOCH_MS_MIN:
        found = [datetime.fromtimestamp(value / 1000, UTC).date()]
    return max(found, default=None)


def main() -> None:
    names = sys.argv[1:]
    if not names:
        raise SystemExit(__doc__)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    STATS.mkdir(parents=True, exist_ok=True)
    for name in names:
        real = json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))
        scrubber = Scrubber(seed=name, newest=newest_date(real) or FAKE_DAY)
        fixture = scrubber.scrub(real)
        target = FIXTURES / f"{name}.json"
        target.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"{target}: kept text values {sorted(scrubber.kept_text)}")
        stats = STATS / f"{name}.json"
        stats.write_text(json.dumps(series_stats(real), indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
