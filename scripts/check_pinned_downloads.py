"""Check that every pinned download in the Containerfile matches its checksum.

    uv run scripts/check_pinned_downloads.py [Containerfile]

The Containerfile fetches files with ``ADD --checksum=sha256:... <url>``, where the
URL takes its version from a global ``ARG *_VERSION`` that Renovate raises. Renovate
cannot update the checksum, and BuildKit keys the cached layer on the checksum, so a
build with a warm cache keeps serving the old file after a version bump (ADR 25).

This script expands each URL the way BuildKit does (a global ARG default reaches a
stage only when the stage declares the ARG, and a stage default overrides it),
downloads it without any cache, and compares its sha256 with the pinned one. It
covers every architecture, not just the one CI builds. A remote ADD without a
checksum is an error too.
Exit status 0 when all match, 1 otherwise, including when no download is found.
"""

import hashlib
import http.client
import json
import re
import shlex
import sys
import urllib.request
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

CHUNK = 1 << 20
TIMEOUT_SECONDS = 60
VARIABLE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")
CHECKSUM = re.compile(r"^sha256:([0-9a-f]{64})$")


@dataclass(frozen=True)
class PinnedDownload:
    line: int
    url: str
    checksum: str | None


def instructions(text: str) -> Iterable[tuple[int, str]]:
    """Yield (first line number, instruction) with continuations joined."""
    start, parts = 0, list[str]()
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not parts and (not stripped or stripped.startswith("#")):
            continue
        if parts and (not stripped or stripped.startswith("#")):
            continue  # blank and comment lines inside a continuation are dropped
        if not parts:
            start = number
        if stripped.endswith("\\"):
            parts.append(stripped[:-1])
            continue
        parts.append(stripped)
        yield start, " ".join(parts)
        parts = []
    if parts:
        yield start, " ".join(parts)


def expand(value: str, args: dict[str, str], line: int) -> str:
    def substitute(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        if name not in args:
            raise ValueError(f"line {line}: ${name} has no value in this stage")
        return args[name]

    return VARIABLE.sub(substitute, value)


def add_arguments(rest: str, line: int) -> tuple[list[str], list[str]]:
    """The flags and the paths of an ADD, in shell or JSON form."""
    flags: list[str] = []
    while rest.startswith("--"):
        flag, _, rest = rest.partition(" ")
        flags.append(flag)
        rest = rest.lstrip()
    if rest.startswith("["):
        try:
            paths = json.loads(rest)
        except json.JSONDecodeError as error:
            raise ValueError(f"line {line}: ADD in JSON form does not parse: {error}") from None
        if not (isinstance(paths, list) and all(isinstance(p, str) for p in paths)):
            raise ValueError(f"line {line}: ADD in JSON form is not a list of strings")
        return flags, paths
    return flags, shlex.split(rest)


def pinned_downloads(text: str) -> list[PinnedDownload]:
    """The remote ADD sources, with their URLs expanded from the ARGs in scope."""
    global_args: dict[str, str] = {}
    stage_args: dict[str, str] | None = None  # None before the first FROM
    downloads: list[PinnedDownload] = []
    for line, instruction in instructions(text):
        keyword, _, rest = instruction.partition(" ")
        keyword = keyword.upper()
        if keyword == "FROM":
            stage_args = {}
        elif keyword == "ARG":
            for word in shlex.split(rest):
                name, sep, default = word.partition("=")
                if stage_args is None:
                    if sep:
                        global_args[name] = default
                elif sep:
                    stage_args[name] = expand(default, stage_args, line)
                elif name in global_args:
                    stage_args[name] = global_args[name]
        elif keyword == "ADD":
            flags, paths = add_arguments(rest, line)
            checksum = next(
                (f.partition("=")[2] for f in flags if f.startswith("--checksum=")), None
            )
            for source in paths[:-1]:
                if source.startswith(("http://", "https://")):
                    url = expand(source, stage_args or {}, line)
                    downloads.append(PinnedDownload(line, url, checksum))
    return downloads


def sha256_of(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "pinned-download-check"})  # noqa: S310
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        while chunk := response.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def problem(download: PinnedDownload, fetch: Callable[[str], str], name: str) -> str | None:
    """A description of what is wrong with one download, or None."""
    where = f"{name}:{download.line} {download.url}"
    if download.checksum is None:
        return f"{where}: remote ADD without --checksum"
    match = CHECKSUM.match(download.checksum)
    if match is None:
        return f"{where}: checksum is not sha256:<64 hex digits>"
    try:
        actual = fetch(download.url)
    except (OSError, http.client.HTTPException) as error:
        return f"{where}: download failed: {error}"
    if actual != match.group(1):
        return f"{where}: checksum is {download.checksum}, but the file is sha256:{actual}"
    return None


def check(text: str, fetch: Callable[[str], str], name: str = "Containerfile") -> list[str]:
    downloads = pinned_downloads(text)
    if not downloads:
        return [f"{name}: no remote ADD found; the check would prove nothing"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = pool.map(lambda d: problem(d, fetch, name), downloads)
    return [p for p in results if p is not None]


def main(argv: list[str]) -> int:
    path = Path(argv[0] if argv else "Containerfile")
    try:
        problems = check(path.read_text(encoding="utf-8"), sha256_of, str(path))
    except ValueError as error:
        problems = [f"{path}: {error}"]
    for line in problems:
        print(line, file=sys.stderr)
    if problems:
        print(
            "After a version bump, put the new sha256 in the --checksum of each ADD above.",
            file=sys.stderr,
        )
        return 1
    print(f"{path}: all pinned downloads match their checksums")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
