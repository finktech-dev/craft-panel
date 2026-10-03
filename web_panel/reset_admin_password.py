"""Restablece localmente la contraseña administrativa sin exponerla en pantalla."""

from __future__ import annotations

import contextlib
import getpass
import json
import os
from pathlib import Path

from app.core.config import settings


def main() -> None:
    assert settings.local_secrets_path is not None
    password = getpass.getpass("Nueva contraseña del panel (12 caracteres o más): ")
    confirmation = getpass.getpass("Repetí la contraseña: ")

    if len(password) < 12:
        raise SystemExit("La contraseña debe tener al menos 12 caracteres.")
    if password != confirmation:
        raise SystemExit("Las contraseñas no coinciden. No se modificó nada.")

    secrets_path = settings.local_secrets_path
    try:
        values = json.loads(secrets_path.read_text(encoding="utf-8")) if secrets_path.is_file() else {}
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit("No se pudo leer el archivo local de secretos.") from error
    if not isinstance(values, dict):
        raise SystemExit("El archivo local de secretos no tiene un formato válido.")

    values["admin_pin"] = password
    temporary_path = Path(f"{secrets_path}.tmp")
    temporary_path.write_text(json.dumps(values, indent=2), encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(temporary_path, 0o600)
    os.replace(temporary_path, secrets_path)
    print("Contraseña actualizada. Iniciá nuevamente el panel para usarla.")


if __name__ == "__main__":
    main()
