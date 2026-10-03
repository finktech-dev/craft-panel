#!/usr/bin/env sh
# First-run launcher for Linux and macOS. It keeps all Python files in .venv.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PANEL="$ROOT/web_panel"
PYTHON="$ROOT/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  if command -v python3 >/dev/null 2>&1; then
    BOOTSTRAP_PYTHON=python3
  elif command -v python >/dev/null 2>&1; then
    BOOTSTRAP_PYTHON=python
  else
    echo "Python is missing. Installing it with the system package manager..."
    if command -v brew >/dev/null 2>&1; then
      brew install python
    elif command -v apt-get >/dev/null 2>&1; then
      sudo apt-get update && sudo apt-get install -y python3 python3-venv
    elif command -v dnf >/dev/null 2>&1; then
      sudo dnf install -y python3
    elif command -v pacman >/dev/null 2>&1; then
      sudo pacman -Sy --noconfirm python
    else
      echo "No supported package manager was found. Install Python 3.11 or newer, then run ./iniciar_panel.sh again." >&2
      exit 1
    fi
    if command -v python3 >/dev/null 2>&1; then
      BOOTSTRAP_PYTHON=python3
    elif command -v python >/dev/null 2>&1; then
      BOOTSTRAP_PYTHON=python
    else
      echo "Python installation did not finish successfully. Run this file again after it completes." >&2
      exit 1
    fi
  fi
  "$BOOTSTRAP_PYTHON" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' || { echo "Python 3.11 or newer is required." >&2; exit 1; }
  echo "Creating the local Python environment..."
  "$BOOTSTRAP_PYTHON" -m venv "$ROOT/.venv"
fi

echo "Checking panel dependencies..."
"$PYTHON" -m pip install --disable-pip-version-check -q -r "$PANEL/requirements.txt"
echo "Starting the panel. Your browser will open when it is ready."
exec "$PYTHON" "$PANEL/run_panel.py"