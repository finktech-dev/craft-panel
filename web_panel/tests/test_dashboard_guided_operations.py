"""Static regression coverage for the guided dashboard operations."""

from pathlib import Path


_PANEL_ROOT = Path(__file__).parents[1]


def test_dashboard_has_one_main_action_and_hides_risky_ones() -> None:
    content = (_PANEL_ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")

    assert 'id="hero-action"' in content
    assert 'id="create-backup"' in content
    assert 'id="graceful-restart"' in content
    # Risky actions live inside "Más acciones", and the data-loss warning comes before the kill button.
    assert content.index("Más acciones") < content.index('data-server-action="stop"')
    assert content.index("se pierde") < content.index('data-server-action="kill"')


def test_dashboard_speaks_plainly() -> None:
    content = (_PANEL_ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
    for jargon in ("TPS", "CPU", "PID", "Diagnóstico", "proceso Java"):
        assert jargon not in content


def test_dashboard_script_uses_existing_endpoints_with_confirmations() -> None:
    script = (_PANEL_ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

    assert "window.confirm" in script
    assert "/api/server/graceful-restart?countdown=10" in script
    assert "Panel.api('/api/backups', { method: 'POST' })" in script
    assert "`/api/server/${action}`" in script
    assert "/api/server/safety-summary" in script
