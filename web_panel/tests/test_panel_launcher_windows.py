from pathlib import Path


LAUNCHER = Path(__file__).resolve().parents[1] / "run_panel.py"


def test_windows_launcher_keeps_subprocess_capable_event_loop() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")

    assert "asyncio.WindowsProactorEventLoopPolicy()" in source
    assert "_configure_windows_event_loop()" in source
    assert "reload=False" in source
    assert "reload=True" not in source
    assert "_open_browser_when_ready" in source
