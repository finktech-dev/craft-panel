"""Restablece localmente la contraseña administrativa sin exponerla en pantalla."""

from __future__ import annotations

import getpass
import json
import secrets

from app.core.config import settings
from app.core.path_safety import write_private_text


def main() -> None:
    assert settings.local_secrets_path is not None
    password = getpass.getpass("Nueva contraseña del panel (12 caracteres o más): ")
    confirmation = getpass.getpass("Repetí la contraseña: ")

    if len(password) < 12:
        raise SystemExit("La contraseña debe tener al menos 12 caracteres.")
    if len(password) > 128:
        raise SystemExit("La contraseña puede tener como máximo 128 caracteres.")
    if len(set(password)) < 5:
        raise SystemExit("La contraseña es demasiado predecible. Usá letras, números y símbolos variados.")
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
    # A new session secret signs out every browser that used the old password.
    values["session_secret"] = secrets.token_urlsafe(48)
    write_private_text(secrets_path, json.dumps(values, indent=2))
    print("Contraseña actualizada y sesiones abiertas cerradas. Iniciá nuevamente el panel para usarla.")


if __name__ == "__main__":
    main()
