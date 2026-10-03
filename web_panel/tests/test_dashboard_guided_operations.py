"""Static regression coverage for the guided dashboard operations."""

from pathlib import Path


_PANEL_ROOT = Path(__file__).parents[1]


def test_dashboard_prioritizes_guided_operations_and_discloses_risk() -> None:
    content = (_PANEL_ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")

    assert "Operaciones guiadas" in content
    assert 'data-server-action="start"' in content
    assert 'id="create-backup"' in content
    assert 'id="graceful-restart"' in content
    assert "Herramientas avanzadas: apagar, forzar cierre y consola" in content
    assert content.index("Herramientas avanzadas: apagar, forzar cierre y consola") < content.index('data-server-action="kill"')


def test_dashboard_script_uses_existing_endpoints_with_confirmations() -> None:
    script = (_PANEL_ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

    assert "window.confirm" in script
    assert "/api/server/graceful-restart?countdown=10" in script
    assert "Panel.api('/api/backups', { method: 'POST' })" in script
    assert "`/api/server/${action}`" in script
