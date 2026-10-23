import pytest

from app.services.java_runtime_service import JavaRuntimeService, JavaRuntimeValidationError


def test_java_requirement_tracks_the_minecraft_version():
    assert JavaRuntimeService.required_major("1.21.1") == 21
    assert JavaRuntimeService.required_major("1.20.5") == 21
    assert JavaRuntimeService.required_major("1.20.4") == 17
    assert JavaRuntimeService.required_major("1.18.2") == 17
    assert JavaRuntimeService.required_major("1.17.1") == 16
    assert JavaRuntimeService.required_major("1.16.5") == 8


@pytest.mark.parametrize(
    ("minecraft", "java"),
    [
        ("1.8.9", 8),
        ("1.12.2", 8),
        ("1.16", 8),
        ("1.17", 16),
        ("1.18", 17),
        ("1.19.4", 17),
        ("1.20", 17),
        ("1.20.4", 17),
        ("1.20.5", 21),
        ("1.20.6", 21),
        ("1.21", 21),
        ("1.21.11", 21),
        ("26.1", 25),
        ("26.1.2", 25),
        ("26.3", 25),
        ("26.4-snapshot-5", 25),
        ("1.21.5-pre1", 21),
    ],
)
def test_java_requirement_covers_the_whole_version_range(minecraft: str, java: int) -> None:
    assert JavaRuntimeService.required_major(minecraft) == java


@pytest.mark.parametrize("minecraft", ["", "latest", "2.0", "abc.def"])
def test_java_requirement_rejects_invalid_versions(minecraft: str) -> None:
    with pytest.raises(JavaRuntimeValidationError):
        JavaRuntimeService.required_major(minecraft)


def test_onboarding_offers_a_local_java_download():
    from pathlib import Path

    panel_root = Path(__file__).parent.parent
    template = (panel_root / "templates" / "onboarding.html").read_text(encoding="utf-8")
    script = (panel_root / "static" / "js" / "onboarding.js").read_text(encoding="utf-8")
    assert 'id="download-java"' in template
    assert "/api/onboarding/java" in script