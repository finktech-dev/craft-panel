"""Every page that listens to the live console must use the message type the server sends."""

from __future__ import annotations

import re
from pathlib import Path

PANEL = Path(__file__).parents[1]


def test_server_broadcasts_console_lines_as_log() -> None:
    source = (PANEL / "app" / "services" / "server_process.py").read_text(encoding="utf-8")
    assert '{"type": "log", "line": asdict(line)}' in source


def test_pages_listen_for_the_same_type() -> None:
    for name in ("console.js", "admin-ranks.js"):
        source = (PANEL / "static" / "js" / name).read_text(encoding="utf-8")
        types = set(re.findall(r"\.type === '([a-z_]+)' && \w+\.line\b", source))
        assert types <= {"log"}, f"{name} listens for {types}"
    ranks = (PANEL / "static" / "js" / "admin-ranks.js").read_text(encoding="utf-8")
    assert "data.type === 'log'" in ranks
