"""Portable first-run launcher for the local Minecraft control panel."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PANEL = ROOT / "web_panel"
VENV = ROOT / ".venv"
PYTHON = VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
MINIMUM_PYTHON = (3, 11)
_VERSION_CHECK = f"import sys; raise SystemExit(sys.version_info < {MINIMUM_PYTHON!r})"


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, check=True, cwd=cwd)


def venv_is_usable(python: Path = PYTHON) -> bool:
    """A venv breaks when the Python it was created from is removed or upgraded."""
    if not python.is_file():
        return False
    try:
        result = subprocess.run(
            (str(python), "-c", _VERSION_CHECK),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def main() -> int:
    if sys.version_info < MINIMUM_PYTHON:
        print("Se necesita Python 3.11 o superior para iniciar el panel.", file=sys.stderr)
        print("Descargalo desde https://www.python.org/downloads/ y volvé a ejecutar este archivo.", file=sys.stderr)
        return 1
    if VENV.exists() and not venv_is_usable():
        print("El entorno de Python de la carpeta .venv no funciona. Se va a crear de nuevo…")
        shutil.rmtree(VENV)
    if not PYTHON.is_file():
        print("Creando el entorno local de Python…")
        run(sys.executable, "-m", "venv", str(VENV))
    print("Revisando las dependencias del panel…")
    run(str(PYTHON), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(PANEL / "requirements.txt"))
    print("El navegador se abrirá cuando el panel local esté listo.")
    # Same working directory as iniciar_panel.bat, so web_panel/.env is used.
    run(str(PYTHON), "run_panel.py", cwd=PANEL)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(f"No se pudo preparar o iniciar el panel: {error}", file=sys.stderr)
        raise SystemExit(error.returncode)
    except OSError as error:
        print(f"No se pudo preparar la carpeta .venv: {error}", file=sys.stderr)
        raise SystemExit(1)
