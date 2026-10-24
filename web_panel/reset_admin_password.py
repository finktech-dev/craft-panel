"""Restablece localmente la contraseña administrativa.

Only a scrypt hash is written to ``.panel_secrets.json``. When the owner lets
the tool generate the password, it is printed once in this window and never
stored in plain text anywhere.
"""

from __future__ import annotations

import getpass
import json
import secrets
from collections.abc import Callable
from pathlib import Path

from app.core.passwords import hash_password
from app.core.path_safety import write_private_text


def _validate(password: str) -> None:
    if len(password) < 12:
        raise SystemExit("La contraseña debe tener al menos 12 caracteres.")
    if len(password) > 128:
        raise SystemExit("La contraseña puede tener como máximo 128 caracteres.")
    if len(set(password)) < 5:
        raise SystemExit("La contraseña es demasiado predecible. Usá letras, números y símbolos variados.")


def reset_password(
    secrets_path: Path,
    prompt: Callable[[str], str] = getpass.getpass,
    output: Callable[[str], None] = print,
) -> None:
    """Replace the stored password hash and sign out every open session."""
    password = prompt("Escribí una contraseña nueva (12 caracteres o más) o apretá Enter para que se genere una: ")
    generated = not password
    if generated:
        password = secrets.token_urlsafe(18)
    else:
        _validate(password)
        if password != prompt("Repetí la contraseña: "):
            raise SystemExit("Las contraseñas no coinciden. No se modificó nada.")

    try:
        values = json.loads(secrets_path.read_text(encoding="utf-8")) if secrets_path.is_file() else {}
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit("No se pudo leer el archivo local de secretos.") from error
    if not isinstance(values, dict):
        raise SystemExit("El archivo local de secretos no tiene un formato válido.")

    values.pop("admin_pin", None)  # plain-text value from older versions
    values.pop("admin_password_unclaimed", None)
    values["admin_password_hash"] = hash_password(password)
    # A new session secret signs out every browser that used the old password.
    values["session_secret"] = secrets.token_urlsafe(48)
    write_private_text(secrets_path, json.dumps(values, indent=2))

    if generated:
        output("")
        output("Tu contraseña nueva es:")
        output("")
        output(f"    {password}")
        output("")
        output("Copiala ahora y guardala en un lugar seguro: no se vuelve a mostrar y el panel solo guarda una huella de ella.")
    output("Contraseña actualizada y sesiones abiertas cerradas. Iniciá nuevamente el panel para usarla.")


def main() -> None:
    from app.core.config import settings

    assert settings.local_secrets_path is not None
    reset_password(settings.local_secrets_path)


if __name__ == "__main__":
    main()
