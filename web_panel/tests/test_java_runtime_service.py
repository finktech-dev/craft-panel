from app.services.java_runtime_service import JavaRuntimeService


def test_java_requirement_tracks_the_minecraft_version():
    assert JavaRuntimeService.required_major("1.21.1") == 21
    assert JavaRuntimeService.required_major("1.20.5") == 21
    assert JavaRuntimeService.required_major("1.20.4") == 17
    assert JavaRuntimeService.required_major("1.18.2") == 17
    assert JavaRuntimeService.required_major("1.17.1") == 16
    assert JavaRuntimeService.required_major("1.16.5") == 8


def test_onboarding_offers_a_local_java_download():
    from pathlib import Path

    panel_root = Path(__file__).parent.parent
    template = (panel_root / "templates" / "onboarding.html").read_text(encoding="utf-8")
    script = (panel_root / "static" / "js" / "onboarding.js").read_text(encoding="utf-8")
    assert 'id="download-java"' in template
    assert "/api/onboarding/java" in script