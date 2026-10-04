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
    assert "/api/mods/bulk-action" in paths
    assert "/api/mods/updates" in paths


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


def test_mod_item_schema_and_server_only_classification(tmp_path):
    from app.services.mod_service import ModService

    server_jar = tmp_path / "spark-1.10.0-neoforge.jar"
    server_jar.write_bytes(b"dummy")
    client_jar = tmp_path / "jei-1.21.1-19.0.0.jar"
    client_jar.write_bytes(b"dummy")

    item_server = ModService._mod_item_from_path(server_jar)
    item_client = ModService._mod_item_from_path(client_jar)

    assert item_server.is_server_only is True
    assert item_server.name == "spark-1.10.0-neoforge"
    assert item_client.is_server_only is False
    assert item_client.name == "jei-1.21.1-19.0.0"


def test_mods_template_and_asset_integrity():
    """Valida que la vista /mods referencie su controlador mods.js y contenga los componentes UX clave."""
    panel_root = pathlib.Path(__file__).parent.parent
    template = (panel_root / "templates" / "mods.html").read_text(encoding="utf-8")
    script = (panel_root / "static" / "js" / "mods.js").read_text(encoding="utf-8")

    assert '/static/js/mods.js' in template
    assert 'id="panel-installed"' in template
    assert 'id="panel-modrinth"' in template
    assert 'id="local-mod-search"' in template
    assert 'id="modal-upload-mod"' in template
    assert 'id="modal-delete-mod"' in template
    assert 'id="modal-bulk-delete"' in template
    assert 'id="bulk-actions-bar"' in template
    assert 'id="btn-check-updates"' in template
    assert 'kpi-total-mods' in template

    # Validar que mods.js consuma las APIs de mods
    assert '/api/mods' in script
    assert '/api/mods/upload' in script
    assert '/api/mods/export-client-pack' in script
    assert '/api/mods/search' in script
    assert '/api/mods/bulk-action' in script
    assert '/api/mods/updates' in script


def test_mod_metadata_extraction_and_config_linking(tmp_path):
    """Valida la extracción de metadatos de neoforge.mods.toml y detección de archivos de configuración."""
    import zipfile
    from app.core.config import Settings
    from app.services.mod_service import ModService

    server_dir = tmp_path / "server"
    mods_dir = server_dir / "mods"
    mods_dir.mkdir(parents=True)
    jar_file = mods_dir / "custom-gun-1.0.jar"
    toml_content = """modLoader = "javafml"
[[mods]]
modId = "customguns"
version = "1.2.3"
displayName = "Custom Guns Mod"
description = "Armas de fuego avanzadas"
authors = "DevTeam"
"""
    with zipfile.ZipFile(jar_file, "w") as zf:
        zf.writestr("META-INF/neoforge.mods.toml", toml_content)

    # 2. Configurar directorio simulado de servidor con config/
    config_dir = server_dir / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "customguns-common.toml").write_text("# config", encoding="utf-8")

    mock_settings = Settings(project_root=tmp_path, server_directory=server_dir, mods_directory=mods_dir)
    item = ModService._mod_item_from_path(jar_file, settings_obj=mock_settings)

    assert item.mod_id == "customguns"
    assert item.name == "Custom Guns Mod"
    assert item.version == "1.2.3"
    assert item.description == "Armas de fuego avanzadas"
    assert item.authors == "DevTeam"
    assert item.has_config is True
    assert item.config_filename == "customguns-common.toml"


@pytest.mark.asyncio
async def test_mod_bulk_actions(tmp_path):
    """Valida operaciones en lote (enable, disable, delete) con ModService."""
    from app.core.config import Settings
    from app.services.mod_service import ModService

    # Crear 3 archivos
    server_dir = tmp_path / "server"
    mods_dir = server_dir / "mods"
    mods_dir.mkdir(parents=True)

    mod1 = mods_dir / "mod1.jar"
    mod2 = mods_dir / "mod2.jar"
    mod3 = mods_dir / "mod3.jar.disabled"
    mod1.write_bytes(b"1")
    mod2.write_bytes(b"2")
    mod3.write_bytes(b"3")

    mock_settings = Settings(project_root=tmp_path, server_directory=server_dir, mods_directory=mods_dir)
    service = ModService(configured_settings=mock_settings)

    # Desactivar en lote mod1 y mod2
    res_disable = await service.bulk_action("disable", ["mod1.jar", "mod2.jar"])
    assert res_disable.affected_count == 2
    assert (mods_dir / "mod1.jar.disabled").is_file()
    assert (mods_dir / "mod2.jar.disabled").is_file()

    # Habilitar en lote mod1, mod2, mod3
    res_enable = await service.bulk_action("enable", ["mod1.jar.disabled", "mod2.jar.disabled", "mod3.jar.disabled"])
    assert res_enable.affected_count == 3
    assert (mods_dir / "mod1.jar").is_file()
    assert (mods_dir / "mod3.jar").is_file()

    # Eliminar en lote mod1 y mod2
    res_delete = await service.bulk_action("delete", ["mod1.jar", "mod2.jar"])
    assert res_delete.affected_count == 2
    assert not (mods_dir / "mod1.jar").exists()
    assert not (mods_dir / "mod2.jar").exists()
    assert (mods_dir / "mod3.jar").exists()


