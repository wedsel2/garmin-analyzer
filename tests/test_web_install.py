"""Tests for what makes the site installable: the manifest, its icons and the service worker."""

import hashlib
import json
import re
import struct
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from garmin_analyzer.tokens import TokenCipher, generate_key
from garmin_analyzer.web.app import create_app
from garmin_analyzer.web.shared import HERE

CIPHER = TokenCipher(generate_key())
MANIFEST = "/static/manifest.webmanifest"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def client(db: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(db, CIPHER), follow_redirects=False) as client:
        yield client


def png_size(content: bytes) -> tuple[int, int]:
    """Width and height from the header of a PNG file."""
    assert content[:8] == PNG_SIGNATURE
    width, height = struct.unpack(">II", content[16:24])
    return width, height


def test_pages_link_the_manifest_and_register_the_service_worker(client: TestClient) -> None:
    page = client.get("/setup").text

    assert f'<link rel="manifest" href="{MANIFEST}" crossorigin="use-credentials">' in page
    assert '<script src="/static/install.js" defer></script>' in page
    assert 'register("/sw.js")' in client.get("/static/install.js").text


def test_the_manifest_opens_the_site_as_an_app(client: TestClient) -> None:
    response = client.get(MANIFEST)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    manifest = response.json()
    assert manifest["name"] == "Garmin Analyzer"
    assert (manifest["start_url"], manifest["scope"]) == ("/", "/")
    assert manifest["display"] == "standalone"


def test_every_icon_of_the_manifest_is_served_at_its_stated_size(client: TestClient) -> None:
    icons = client.get(MANIFEST).json()["icons"]

    # What Android asks for: 192 and 512 pixels, and one it may cut to a shape.
    pngs = [icon for icon in icons if icon["type"] == "image/png"]
    assert {icon["sizes"] for icon in pngs} == {"192x192", "512x512"}
    assert [icon["sizes"] for icon in pngs if icon.get("purpose") == "maskable"] == ["512x512"]
    for icon in icons:
        response = client.get(icon["src"])
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(icon["type"])
        if icon["type"] == "image/png":
            width, height = png_size(response.content)
            assert f"{width}x{height}" == icon["sizes"]


def test_the_service_worker_is_served_from_the_top_of_the_site(client: TestClient) -> None:
    response = client.get("/sw.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_the_service_worker_changes_when_the_offline_page_does(client: TestClient) -> None:
    page = hashlib.sha256(client.get("/offline").content).hexdigest()[:16]

    script = client.get("/sw.js").text

    assert script.endswith(f"// Offline page {page}\n")
    assert client.get("/sw.js").text == script


def test_the_service_worker_keeps_only_the_offline_page_and_its_files(client: TestClient) -> None:
    script = (HERE / "static" / "sw.js").read_text(encoding="utf-8")

    kept = re.search(r"const KEPT = \[(.*?)\];", script)
    assert kept is not None
    paths = json.loads("[" + kept.group(1).replace("OFFLINE", '"/offline"') + "]")
    assert paths == ["/offline", "/static/app.css", "/static/icon.svg"]
    # One cache, filled only with that list or with what was asked for from it.
    assert script.count("caches.open(") == 2
    assert script.count("cache.addAll(KEPT)") == 1
    assert script.count("cache.put(") == 1
    assert "KEPT.includes(url.pathname)" in script


def test_the_offline_page_needs_no_sign_in_and_shows_no_data(client: TestClient) -> None:
    response = client.get("/offline")

    assert response.status_code == 200
    assert "No connection" in response.text
    assert 'aria-label="Dashboards"' not in response.text
