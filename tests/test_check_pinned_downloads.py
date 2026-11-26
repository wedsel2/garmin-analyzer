"""scripts/check_pinned_downloads.py, with downloads replaced by a local lookup."""

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "check_pinned_downloads.py"
CONTAINERFILE = SCRIPT.parent.parent / "Containerfile"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_pinned_downloads", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look the module up by name
    spec.loader.exec_module(module)
    return module


check_pinned = load_script()


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# What each URL serves; a URL missing here behaves like a failed download.
SERVED = {
    "https://example.test/tool/v1.1.0/tool-x64": b"tool 1.1.0 x64",
    "https://example.test/tool/v1.1.0/tool-arm64": b"tool 1.1.0 arm64",
    "https://example.test/tool/v1.0.0/tool-x64": b"tool 1.0.0 x64",
    "https://example.test/lib@2.0.0/lib.js": b"lib 2.0.0",
}


def fetch(url: str) -> str:
    if url not in SERVED:
        raise OSError(f"404 for {url}")
    return sha(SERVED[url])


def containerfile(tool_version: str, x64_checksum: str) -> str:
    return f"""# syntax=docker/dockerfile:1
ARG TOOL_VERSION={tool_version}
ARG LIB_VERSION="2.0.0"
ARG TARGETARCH

FROM base AS tool-amd64
ARG TOOL_VERSION
ADD --checksum=sha256:{x64_checksum} --chmod=755 \\
    https://example.test/tool/v${{TOOL_VERSION}}/tool-x64 \\
    /usr/local/bin/tool

FROM base AS tool-arm64
ARG TOOL_VERSION
# a comment inside the stage
ADD --checksum=sha256:{sha(b"tool 1.1.0 arm64")} \\
    https://example.test/tool/v$TOOL_VERSION/tool-arm64 /usr/local/bin/tool

FROM scratch
ARG LIB_VERSION
ADD --checksum=sha256:{sha(b"lib 2.0.0")} https://example.test/lib@${{LIB_VERSION}}/lib.js /lib.js
COPY local.txt /local.txt
ADD local.tar /
"""


def test_matching_checksums_pass() -> None:
    text = containerfile("1.1.0", sha(b"tool 1.1.0 x64"))
    assert check_pinned.check(text, fetch) == []


def test_version_bump_with_stale_checksum_fails() -> None:
    """The PR #40 case: the version moved on, the checksum did not."""
    text = containerfile("1.1.0", sha(b"tool 1.0.0 x64"))
    problems = check_pinned.check(text, fetch)
    assert len(problems) == 1
    assert "Containerfile:8 https://example.test/tool/v1.1.0/tool-x64" in problems[0]
    assert f"the file is sha256:{sha(b'tool 1.1.0 x64')}" in problems[0]


def test_urls_are_expanded_from_global_args_only() -> None:
    downloads = check_pinned.pinned_downloads(containerfile("1.1.0", "0" * 64))
    assert [(d.line, d.url) for d in downloads] == [
        (8, "https://example.test/tool/v1.1.0/tool-x64"),
        (15, "https://example.test/tool/v1.1.0/tool-arm64"),
        (20, "https://example.test/lib@2.0.0/lib.js"),
    ]


def test_failed_download_is_reported() -> None:
    text = containerfile("9.9.9", sha(b"tool 1.1.0 x64"))
    problems = check_pinned.check(text, fetch)
    assert len(problems) == 2  # both architectures of the missing version
    assert all("download failed: 404" in p for p in problems)


def test_remote_add_without_checksum_fails() -> None:
    text = "FROM scratch\nADD https://example.test/lib@2.0.0/lib.js /lib.js\n"
    assert check_pinned.check(text, fetch) == [
        "Containerfile:2 https://example.test/lib@2.0.0/lib.js: remote ADD without --checksum"
    ]


def test_malformed_checksum_fails() -> None:
    text = "FROM scratch\nADD --checksum=sha256:abc https://example.test/lib@2.0.0/lib.js /l\n"
    (problem,) = check_pinned.check(text, fetch)
    assert "not sha256:<64 hex digits>" in problem


PIN = "--checksum=sha256:" + "0" * 64


def test_global_arg_is_not_in_scope_until_the_stage_declares_it() -> None:
    text = f"ARG V=1\nFROM scratch\nADD {PIN} https://x.test/$V /v\n"
    with pytest.raises(ValueError, match=r"line 3: \$V has no value in this stage"):
        check_pinned.pinned_downloads(text)


def test_stage_default_overrides_the_global_one() -> None:
    text = f"ARG V=1\nFROM scratch\nARG V=2 W=x$V\nADD {PIN} https://x.test/$V/$W /v\n"
    (download,) = check_pinned.pinned_downloads(text)
    assert download.url == "https://x.test/2/x2"


def test_blank_line_inside_a_continuation_is_skipped() -> None:
    text = f"FROM scratch\nADD {PIN} \\\n\n    https://x.test/a \\\n    /a\n"
    (download,) = check_pinned.pinned_downloads(text)
    assert (download.line, download.url) == (2, "https://x.test/a")


def test_add_in_json_form_is_checked() -> None:
    text = f'ARG V=1\nFROM scratch\nARG V\nADD {PIN} ["https://x.test/$V", "/v"]\n'
    (download,) = check_pinned.pinned_downloads(text)
    assert download.url == "https://x.test/1"
    with pytest.raises(ValueError, match="does not parse"):
        check_pinned.pinned_downloads(f'FROM scratch\nADD {PIN} ["https://x.test/a"\n')
    with pytest.raises(ValueError, match="not a list of strings"):
        check_pinned.pinned_downloads(f"FROM scratch\nADD {PIN} [1, 2]\n")


def test_no_remote_add_is_a_failure() -> None:
    assert check_pinned.check("FROM scratch\nADD local.tar /\n", fetch, "x/Containerfile") == [
        "x/Containerfile: no remote ADD found; the check would prove nothing"
    ]


def test_main_reports_and_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(check_pinned, "sha256_of", fetch)
    path = tmp_path / "Containerfile"

    path.write_text(containerfile("1.1.0", sha(b"tool 1.1.0 x64")), encoding="utf-8")
    assert check_pinned.main([str(path)]) == 0

    path.write_text(containerfile("1.1.0", sha(b"tool 1.0.0 x64")), encoding="utf-8")
    assert check_pinned.main([str(path)]) == 1
    err = capsys.readouterr().err
    assert "put the new sha256" in err
    assert f"{path}:8 https://example.test/tool/v1.1.0/tool-x64" in err

    path.write_text("FROM scratch\nADD --checksum=sha256:x https://x.test/$NOPE /x\n")
    assert check_pinned.main([str(path)]) == 1
    assert f"{path}: line 2: $NOPE" in capsys.readouterr().err


def test_repository_containerfile_pins_every_download() -> None:
    """Offline part of the real check: every remote ADD has a well-formed checksum."""
    text = CONTAINERFILE.read_text(encoding="utf-8")
    downloads = check_pinned.pinned_downloads(text)
    assert len(downloads) >= 4
    assert all(d.url.startswith("https://") and "$" not in d.url for d in downloads)
    # A fake digest makes every entry mismatch; any other kind of problem is a real one.
    problems = check_pinned.check(text, lambda url: "0" * 64)
    assert len(problems) == len(downloads)
    assert all("the file is sha256:" in p for p in problems)
