"""Portable first-run launcher for the local Minecraft control panel."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PANEL = ROOT / "web_panel"
VENV = ROOT / ".venv"
PYTHON = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def main() -> int:
    if not PYTHON.is_file():
        print("Creating the local Python environment…")
        run(sys.executable, "-m", "venv", str(VENV))
    print("Checking panel dependencies…")
    run(str(PYTHON), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(PANEL / "requirements.txt"))
    print("The browser opens once the local panel is ready.")
    run(str(PYTHON), str(PANEL / "run_panel.py"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(f"Panel setup failed: {error}", file=sys.stderr)
        raise SystemExit(error.returncode)