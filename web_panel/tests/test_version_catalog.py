"""Version lists from official sources, parsed from recorded sample payloads (no live network)."""

from __future__ import annotations

import httpx
import pytest

from app.services.version_catalog_service import (
    FABRIC_GAME_URL,
    MOJANG_MANIFEST_URL,
    NEOFORGE_METADATA_URL,
    VersionCatalogError,
    VersionCatalogService,
    VersionCatalogValidationError,
    neoforge_catalog_entries,
    parse_fabric_game_versions,
    parse_fabric_installer_versions,
    parse_fabric_loader_versions,
    parse_mojang_manifest,
    parse_neoforge_metadata,
)

MOJANG_SAMPLE = {
    "latest": {"release": "26.3", "snapshot": "26.4-snapshot-5"},
    "versions": [
        {"id": "26.4-snapshot-5", "type": "snapshot", "releaseTime": "2026-10-20T12:15:06+00:00"},
        {"id": "26.3", "type": "release", "releaseTime": "2026-09-15T11:23:02+00:00"},
        {"id": "26.3-rc-1", "type": "snapshot", "releaseTime": "2026-09-10T11:28:25+00:00"},
        {"id": "1.21.1", "type": "release", "releaseTime": "2024-08-08T12:24:45+00:00"},
        {"id": "1.21.11", "type": "release", "releaseTime": "2025-12-09T12:00:00+00:00"},
        {"id": "b1.7.3", "type": "old_beta", "releaseTime": "2011-07-07T22:00:00+00:00"},
    ],
}

FABRIC_GAME_SAMPLE = [
    {"version": "26.4-snapshot-5", "stable": False},
    {"version": "26.3", "stable": True},
    {"version": "1.21.1", "stable": True},
]

FABRIC_LOADER_SAMPLE = [
    {"loader": {"separator": ".", "build": 2, "maven": "net.fabricmc:fabric-loader:0.21.0-beta.1", "version": "0.21.0-beta.1", "stable": False}},
    {"loader": {"separator": ".", "build": 1, "maven": "net.fabricmc:fabric-loader:0.20.1", "version": "0.20.1", "stable": True},
     "intermediary": {"maven": "net.fabricmc:intermediary:1.21.1", "version": "1.21.1", "stable": True}},
    {"loader": {"version": "0.20.0", "stable": True}},
]

FABRIC_INSTALLER_SAMPLE = [
    {"url": "https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.3/fabric-installer-1.1.3.jar", "version": "1.1.3", "stable": False},
    {"url": "https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.2/fabric-installer-1.1.2.jar", "version": "1.1.2", "stable": True},
]

NEOFORGE_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<metadata>
  <groupId>net.neoforged</groupId>
  <artifactId>neoforge</artifactId>
  <versioning>
    <latest>26.3.0.95</latest>
    <release>26.3.0.95</release>
    <versions>
      <version>20.2.3-beta</version>
      <version>20.4.237</version>
      <version>21.0.167</version>
      <version>21.0.10-beta</version>
      <version>21.1.9</version>
      <version>21.1.264</version>
      <version>21.1.250</version>
      <version>26.1.0.0-alpha.1+snapshot-1</version>
      <version>26.1.2.122</version>
      <version>26.3.0.75-beta</version>
      <version>26.3.0.95</version>
      <version>26.4.0.3-beta</version>
    </versions>
  </versioning>
</metadata>
"""


def test_mojang_manifest_lists_releases_newest_first() -> None:
    entries = parse_mojang_manifest(MOJANG_SAMPLE)

    assert [entry.minecraft_version for entry in entries] == ["26.3", "1.21.11", "1.21.1"]
    assert [entry.java_major for entry in entries] == [25, 21, 21]
    assert all(entry.stable for entry in entries)


def test_mojang_manifest_can_include_snapshots() -> None:
    ids = [entry.minecraft_version for entry in parse_mojang_manifest(MOJANG_SAMPLE, include_snapshots=True)]

    assert ids[0] == "26.4-snapshot-5"
    assert "26.3-rc-1" in ids
    assert "b1.7.3" not in ids


def test_mojang_manifest_with_unexpected_shape_is_an_error() -> None:
    with pytest.raises(VersionCatalogError):
        parse_mojang_manifest({"nope": []})


def test_fabric_game_versions_exclude_unstable_by_default() -> None:
    assert [entry.minecraft_version for entry in parse_fabric_game_versions(FABRIC_GAME_SAMPLE)] == ["26.3", "1.21.1"]
    assert len(parse_fabric_game_versions(FABRIC_GAME_SAMPLE, include_snapshots=True)) == 3


def test_fabric_loader_and_installer_pick_the_latest_stable() -> None:
    assert parse_fabric_loader_versions(FABRIC_LOADER_SAMPLE) == "0.20.1"
    assert parse_fabric_loader_versions([]) is None
    assert parse_fabric_installer_versions(FABRIC_INSTALLER_SAMPLE) == "1.1.2"


def test_neoforge_metadata_groups_builds_by_minecraft_version() -> None:
    grouped = parse_neoforge_metadata(NEOFORGE_SAMPLE)

    assert grouped["1.21.1"]["stable"] == ["21.1.264", "21.1.250", "21.1.9"]
    assert grouped["1.21"]["stable"] == ["21.0.167"]
    assert grouped["1.21"]["beta"] == ["21.0.10-beta"]
    assert grouped["26.3"] == {"stable": ["26.3.0.95"], "beta": ["26.3.0.75-beta"]}
    assert grouped["26.1.2"]["stable"] == ["26.1.2.122"]
    assert "26.1" not in grouped  # alpha snapshot builds are ignored


def test_neoforge_catalog_lists_stable_minecraft_versions_newest_first() -> None:
    grouped = parse_neoforge_metadata(NEOFORGE_SAMPLE)

    stable = neoforge_catalog_entries(grouped)
    assert [(entry.minecraft_version, entry.loader_version) for entry in stable] == [
        ("26.3", "26.3.0.95"),
        ("26.1.2", "26.1.2.122"),
        ("1.21.1", "21.1.264"),
        ("1.21", "21.0.167"),
        ("1.20.4", "20.4.237"),
    ]
    with_betas = [entry.minecraft_version for entry in neoforge_catalog_entries(grouped, include_snapshots=True)]
    assert with_betas[0] == "26.4"
    assert "1.20.2" in with_betas


def test_neoforge_metadata_with_unexpected_shape_is_an_error() -> None:
    with pytest.raises(VersionCatalogError):
        parse_neoforge_metadata("<html>maintenance</html>")


def _service(responses: dict[str, httpx.Response], calls: list[str] | None = None) -> VersionCatalogService:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        return responses.get(str(request.url), httpx.Response(404))

    return VersionCatalogService(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_catalog_service_caches_results() -> None:
    calls: list[str] = []
    service = _service({MOJANG_MANIFEST_URL: httpx.Response(200, json=MOJANG_SAMPLE)}, calls)

    first = await service.list_versions("vanilla")
    second = await service.list_versions("vanilla")

    assert first.latest == "26.3"
    assert second.versions == first.versions
    assert calls == [MOJANG_MANIFEST_URL]


@pytest.mark.asyncio
async def test_catalog_service_neoforge_and_fabric_lists() -> None:
    service = _service({
        NEOFORGE_METADATA_URL: httpx.Response(200, text=NEOFORGE_SAMPLE),
        FABRIC_GAME_URL: httpx.Response(200, json=FABRIC_GAME_SAMPLE),
    })

    neoforge = await service.list_versions("neoforge")
    fabric = await service.list_versions("fabric")

    assert neoforge.latest == "26.3"
    assert neoforge.versions[0].loader_version == "26.3.0.95"
    assert fabric.latest == "26.3"


@pytest.mark.asyncio
async def test_latest_neoforge_build_requires_a_stable_build() -> None:
    service = _service({NEOFORGE_METADATA_URL: httpx.Response(200, text=NEOFORGE_SAMPLE)})

    assert await service.latest_neoforge_build("1.21.1") == "21.1.264"
    assert await service.latest_neoforge_build("26.1.2") == "26.1.2.122"
    with pytest.raises(VersionCatalogValidationError, match="estable"):
        await service.latest_neoforge_build("26.4")
    with pytest.raises(VersionCatalogValidationError):
        await service.latest_neoforge_build("1.12.2")


@pytest.mark.asyncio
async def test_offline_source_is_a_clear_error_not_a_fake_list() -> None:
    calls: list[str] = []

    def offline(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        raise httpx.ConnectError("offline", request=request)

    service = VersionCatalogService(transport=httpx.MockTransport(offline))

    with pytest.raises(VersionCatalogError, match="conexión"):
        await service.list_versions("vanilla")
    with pytest.raises(VersionCatalogError):
        await service.list_versions("vanilla")
    assert len(calls) == 1  # the failure is cached briefly so offline hosts fail fast


def test_versions_endpoint_returns_the_catalog(monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import endpoints_onboarding
    from app.core.security import get_current_admin

    service = _service({FABRIC_GAME_URL: httpx.Response(200, json=FABRIC_GAME_SAMPLE)})
    monkeypatch.setattr(endpoints_onboarding, "version_catalog_service", service)
    app = FastAPI()
    app.include_router(endpoints_onboarding.router, prefix="/api")
    app.dependency_overrides[get_current_admin] = lambda: "admin"
    client = TestClient(app)

    response = client.get("/api/onboarding/versions", params={"flavor": "fabric"})

    assert response.status_code == 200
    body = response.json()
    assert body["flavor"] == "fabric"
    assert body["latest"] == "26.3"
    assert [item["minecraft_version"] for item in body["versions"]] == ["26.3", "1.21.1"]
    assert body["versions"][0]["java_major"] == 25

    offline = client.get("/api/onboarding/versions", params={"flavor": "vanilla"})
    assert offline.status_code == 503
    assert "conexión" in offline.json()["detail"]

    invalid = client.get("/api/onboarding/versions", params={"flavor": "paper"})
    assert invalid.status_code == 422
