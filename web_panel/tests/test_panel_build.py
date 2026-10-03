"""Verificación de build y montaje completo del panel FastAPI."""

import pathlib

import pytest
from main import app, templates
from app.core.config import settings


def test_openapi_schema_build():
    """Valida que FastAPI compile su esquema OpenAPI completo sin errores de tipado en schemas."""
    schema = app.openapi()
    assert schema is not None
    assert schema["openapi"].startswith("3.")
    assert "paths" in schema
    # Verificar que existan las rutas esenciales en el build
    paths = schema["paths"]
    assert "/health" in paths
    assert "/api/worldedit/status" in paths
    assert "/api/worldedit/toggle" in paths
    assert "/api/restrictions/summary" in paths
    assert "/api/restrictions/catalog" in paths
    assert "/api/discord/config" in paths
    assert "/api/discord/test" in paths
    assert "/api/runtime/discovery" in paths
    assert "/api/onboarding/status" in paths


def test_static_and_templates_configuration():
    """Valida la configuración de directorios de assets estáticos y plantillas Jinja2."""
    assert settings.static_directory.is_dir()
    assert settings.panel_directory.is_dir()

    expected_templates = [
        "base.html",
        "dashboard.html",
        "administration.html",
        "console.html",
        "mods.html",
        "backups.html",
        "schematics.html",
        "worlds.html",
        "crashes.html",
        "login.html",
        "setup.html",
        "onboarding.html",
    ]
    for tmpl in expected_templates:
        tpl_path = settings.panel_directory / "templates" / tmpl
        assert tpl_path.is_file(), f"Falta la plantilla requerida: {tmpl}"
        # Verificar que Jinja2 pueda parsear la plantilla
        compiled = templates.get_template(tmpl)
        assert compiled is not None


def test_dashboard_v2_is_read_only_and_uses_a_separate_asset():
    """El inicio no debe disparar operaciones del servidor al cargar."""
    panel_root = pathlib.Path(__file__).parent.parent
    template = (panel_root / "templates" / "dashboard.html").read_text(encoding="utf-8")
    script = (panel_root / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
    assert '/static/js/dashboard.js' in template
    assert "/api/server/metrics" in script
    assert "/api/backups" in script
    assert "document.addEventListener('DOMContentLoaded'" in script
    assert "addEventListener('click'" in script
    assert "window.confirm" in script
    assert "method: 'POST'" in script


@pytest.mark.asyncio
async def test_lifespan_build():
    """Valida que el manejador de ciclo de vida (lifespan) inicialice y libere recursos sin errores."""
    from main import lifespan
    async with lifespan(app):
        # Durante el ciclo de vida, la app está activa
        assert app.title == "Panel del servidor Minecraft"
