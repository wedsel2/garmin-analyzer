"""Turn a real Garmin response into a synthetic test fixture.

    uv run scripts/scrub_fixture.py user_summary sleep_data

Reads .garmin-tokens/samples/<name>.json (local, personal) and writes
tests/fixtures/garmin/<name>.json (committed, public). The fixture keeps the
structure and value formats of the real response but none of its values:

  identifiers            replaced by small counters
  numbers                replaced by random numbers of similar size
  dates and timestamps   moved to around 2026-01-15, with a random time offset
  text                   replaced by "redacted", except enum-like constants
  coordinates            zeroed
  long lists             cut to the first few items

Review the printed list of kept text values before committing a fixture.
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
FAKE_DAY = date(2026, 1, 15)
MAX_ITEMS = 5
EPOCH_MS_MIN = 10**11

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
        # Maps keyed by an id, such as a device id.
        return str(self.identifier(key)) if key.isdigit() else key

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
        return round(value * self.random.uniform(0.5, 1.5)) or 1

    def decimal(self, value: float, key: str) -> float:
        if COORDINATE_KEY.search(key):
            return 0.0
        return round(value * self.random.uniform(0.5, 1.5), 2)


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
    for name in names:
        real = json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))
        scrubber = Scrubber(seed=name, newest=newest_date(real) or FAKE_DAY)
        fixture = scrubber.scrub(real)
        target = FIXTURES / f"{name}.json"
        target.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"{target}: kept text values {sorted(scrubber.kept_text)}")


if __name__ == "__main__":
    main()
