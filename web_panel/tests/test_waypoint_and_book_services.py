"""Tests para WaypointService y BookService agnósticos."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.schemas.waypoints import WaypointCreate
from app.services.book_service import BookService
from app.services.waypoint_service import WaypointService


@pytest.mark.asyncio
async def test_waypoint_service_defaults_contain_only_generic_spawn(tmp_path: Path):
    settings = Settings(project_root=tmp_path, panel_directory=tmp_path)
    service = WaypointService(configured_settings=settings)

    waypoints = await service.list_waypoints()
    assert len(waypoints) == 1
    assert waypoints[0].id == "spawn"
    assert waypoints[0].name == "Punto de Spawn"
    assert waypoints[0].x == 0.0
    assert waypoints[0].y == 100.0
    assert waypoints[0].z == 0.0


@pytest.mark.asyncio
async def test_waypoint_service_crud(tmp_path: Path):
    settings = Settings(project_root=tmp_path, panel_directory=tmp_path)
    service = WaypointService(configured_settings=settings)

    created = await service.add_waypoint(
        WaypointCreate(
            name="Base Principal",
            x=100.0,
            y=64.0,
            z=-250.0,
            dimension="minecraft:overworld",
            description="Base de la comunidad",
            icon="home",
        )
    )
    assert created.id
    assert created.name == "Base Principal"

    waypoints = await service.list_waypoints()
    assert len(waypoints) == 2
    assert any(w.name == "Base Principal" for w in waypoints)

    deleted = await service.delete_waypoint(created.id)
    assert deleted is True

    remaining = await service.list_waypoints()
    assert len(remaining) == 1


def test_book_service_uses_generic_defaults_when_no_custom_file(tmp_path: Path):
    defaultconfigs = tmp_path / "server" / "defaultconfigs"
    defaultconfigs.mkdir(parents=True)
    settings = Settings(project_root=tmp_path, panel_directory=tmp_path, defaultconfigs_directory=defaultconfigs)
    service = BookService(configured_settings=settings)

    title, author, pages = service._load_guide_content()
    assert title == "Guía Inicial"
    assert author == "Servidor"
    assert len(pages) >= 2


def test_book_service_loads_custom_guide_file_when_present(tmp_path: Path):
    custom_file = tmp_path / ".guide_book.json"
    custom_file.write_text(
        json.dumps(
            {
                "title": "Mi Manual Personal",
                "author": "Comunidad",
                "pages": ["Página 1", "Página 2"],
            }
        ),
        encoding="utf-8",
    )
    defaultconfigs = tmp_path / "server" / "defaultconfigs"
    defaultconfigs.mkdir(parents=True)
    settings = Settings(project_root=tmp_path, panel_directory=tmp_path, defaultconfigs_directory=defaultconfigs)
    service = BookService(configured_settings=settings)

    title, author, pages = service._load_guide_content()
    assert title == "Mi Manual Personal"
    assert author == "Comunidad"
    assert pages == ["Página 1", "Página 2"]

    # Verify generate_guide_book writes NBT correctly
    book_nbt = service.generate_guide_book()
    assert book_nbt.is_file()
