"""Header layout, opening mod settings in the system editor, and mod updates by file hash."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.api import endpoints_configs
from app.core.config import Settings
from app.core.navigation import DEFAULT_BAR, nav_layout, parse_nav_cookie
from app.core.rate_limit import limiter
from app.core.security import get_current_admin
from app.services import config_service as config_module
from app.services import mod_service as mod_module
from app.services.config_service import ConfigService
from app.services.mod_service import ModService


class StoppedServer:
    is_running = False
    state = "STOPPED"


# Header layout


def test_nav_cookie_defaults_and_ignores_unknown_keys() -> None:
    assert parse_nav_cookie(None) == DEFAULT_BAR
    assert parse_nav_cookie("garbage") == DEFAULT_BAR
    assert parse_nav_cookie("mods.problemas.nope.mods") == ("mods", "problemas")
    assert parse_nav_cookie("-") == ()


def test_nav_layout_moves_the_rest_under_mas() -> None:
    layout = nav_layout(("inicio", "ajustes"))
    assert [item.key for item in layout["bar"]] == ["inicio", "ajustes"]
    assert "consola" in [item.key for item in layout["more"]]
    assert len(layout["all"]) == len(layout["bar"]) + len(layout["more"])


def test_header_draws_the_saved_layout() -> None:
    from main import templates

    html = templates.env.get_template("dashboard.html").render(
        request=None, current_page="dashboard", is_admin=True, brand_name="Panel", csrf_token="x",
        two_factor_enabled=False, public_address=None, minecraft_version="", nav_bar=("inicio", "problemas"),
    )
    bar = html[html.index('aria-label="Navegación principal"'):html.index("<summary")]
    assert 'href="/crashes"' in bar
    assert 'href="/mods"' not in bar
    assert "Personalizar el menú" in html


# Opening a mod's settings in the computer's own editor


@pytest.fixture
def configs_api(tmp_path: Path, monkeypatch):
    configured = Settings(project_root=tmp_path)
    assert configured.config_directory is not None
    configured.config_directory.mkdir(parents=True)
    (configured.config_directory / "waystones-common.toml").write_text("enabled = true\n", encoding="utf-8")
    service = ConfigService(configured, StoppedServer())
    monkeypatch.setattr(endpoints_configs, "config_service", service)
    launched: list[list[str]] = []
    monkeypatch.setattr(config_module, "_system_editor", lambda: ("el Bloc de notas", ["notepad.exe"]))
    monkeypatch.setattr(config_module.subprocess, "Popen", lambda args, **_: launched.append(list(args)))
    app = FastAPI()
    app.include_router(endpoints_configs.router, prefix="/api")
    app.dependency_overrides[get_current_admin] = lambda: "admin"
    return app, launched, configured


@pytest.mark.asyncio
async def test_open_in_editor_only_for_a_browser_on_the_same_pc(configs_api) -> None:
    app, launched, _ = configs_api
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 5000))
    async with httpx.AsyncClient(transport=transport, base_url="http://panel.example") as client:
        info = (await client.get("/api/config-editor")).json()
        assert info["can_open_locally"] is False
        response = await client.post("/api/config-editor/open/waystones-common.toml")
        assert response.status_code == 409
    assert launched == []


@pytest.mark.asyncio
async def test_open_in_editor_passes_one_checked_path(configs_api) -> None:
    app, launched, configured = configs_api
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 5000))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8080") as client:
        assert (await client.get("/api/config-editor")).json() == {"can_open_locally": True, "editor_name": "el Bloc de notas"}
        response = await client.post("/api/config-editor/open/waystones-common.toml")
        assert response.status_code == 200
        assert "Bloc de notas" in response.json()["message"]
        # Paths outside config/ or with other extensions never reach the editor.
        assert (await client.post("/api/config-editor/open/../server.properties")).status_code in {400, 404}
        assert (await client.post("/api/config-editor/open/run.bat")).status_code == 400
    assert launched == [["notepad.exe", str((configured.config_directory / "waystones-common.toml").resolve())]]


# Mod updates, by file hash


def _jar(path: Path, payload: bytes) -> str:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("payload.txt", payload)
    return hashlib.sha1(path.read_bytes()).hexdigest()


@pytest.mark.asyncio
async def test_updates_compare_versions_by_file_hash(tmp_path: Path, monkeypatch) -> None:
    configured = Settings(project_root=tmp_path)
    assert configured.mods_directory is not None
    configured.mods_directory.mkdir(parents=True)
    old_hash = _jar(configured.mods_directory / "waystones-1.0.jar", b"old")
    current_hash = _jar(configured.mods_directory / "jei-2.0.jar", b"current")
    _jar(configured.mods_directory / "private-build.jar", b"not on modrinth")
    requests: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append((request.url.path, body))
        if request.url.path.endswith("/version_files"):
            return httpx.Response(200, json={
                old_hash: {"id": "v1", "project_id": "waystones", "version_number": "1.0", "date_published": "2026-01-01"},
                current_hash: {"id": "j2", "project_id": "jei", "version_number": "2.0", "date_published": "2026-05-01"},
            })
        return httpx.Response(200, json={
            old_hash: {"id": "v2", "project_id": "waystones", "version_number": "1.1", "date_published": "2026-06-01"},
            current_hash: {"id": "j2", "project_id": "jei", "version_number": "2.0", "date_published": "2026-05-01"},
        })

    monkeypatch.setattr(mod_module, "allowed_client", lambda hosts, **_: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    service = ModService(configured, StoppedServer())
    limiter.reset()

    results = {item.filename: item for item in await service.check_updates()}
    assert set(results) == {"waystones-1.0.jar", "jei-2.0.jar"}
    assert results["waystones-1.0.jar"].has_update is True
    assert results["waystones-1.0.jar"].version_id == "v2"
    assert results["waystones-1.0.jar"].latest_version == "1.1"
    assert results["jei-2.0.jar"].has_update is False
    assert len(requests) == 2  # the whole folder in two requests

    # A second look within a few hours uses the remembered answer.
    await service.check_updates()
    assert len(requests) == 2
    await service.check_updates(refresh=True)
    assert len(requests) == 4
