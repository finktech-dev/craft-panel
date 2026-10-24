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
    assert "runJob('/api/backups'" in script
    assert "`/api/server/${action}`" in script
    assert "/api/server/safety-summary" in script


def test_long_operations_show_progress_where_they_started() -> None:
    """Copies, restarts, restores and installs are jobs with an inline progress element."""
    templates = _PANEL_ROOT / "templates"
    scripts = _PANEL_ROOT / "static" / "js"
    jobs_script = (scripts / "jobs.js").read_text(encoding="utf-8")
    assert "'/ws/terminal'" in jobs_script and "payload.type === 'job'" in jobs_script
    assert "/api/jobs" in jobs_script
    assert "Paso ${index + 1} de ${total}" in jobs_script

    expected = {
        "dashboard.html": ('id="hero-progress"', 'id="backup-progress"', 'id="jobs-now"', "Lo que está pasando"),
        "backups.html": ('id="backup-progress"', 'id="restore-progress"'),
        "onboarding.html": ('id="java-progress"', 'id="install-progress"', 'id="start-progress"'),
    }
    for name, markers in expected.items():
        content = (templates / name).read_text(encoding="utf-8")
        assert content.index("/static/js/jobs.js") < content.rindex("<script")  # loaded before the page script
        for marker in markers:
            assert marker in content, f"{name} is missing {marker}"
        assert "<script>" not in content and " onclick=" not in content

    for name in ("dashboard.js", "backups.js", "onboarding.js"):
        assert "PanelJobs." in (scripts / name).read_text(encoding="utf-8")
