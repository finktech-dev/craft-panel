"""``server/craftpanel.txt``: a plain-text, hand-editable settings file for one server.

The format is line based, in the spirit of ``.gitignore``:

* lines starting with ``#`` are comments and blank lines are ignored;
* ``key = value`` lines before any section set a variable (``start_script``,
  ``memory``, ``backup_interval``...);
* ``[section]`` starts a list: every following non-comment line is one item,
  until the next section (``[detect]``, ``[backup_exclude]``...).

Keys and section names are English snake_case; the comments inside the file
and every message are plain Spanish. Values use ``true``/``false`` for
switches, ``90s``/``10m``/``6h``/``2d`` for durations and ``512MB``/``15GB``
for sizes.

Unknown keys and sections are kept untouched, and saving from the panel only
rewrites the lines whose value changed, so comments and the user's layout
survive round trips. The file belongs to the user: it is never created until
someone saves from the panel, and it is never deleted or moved away.
"""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import os
import re
import shutil
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Literal

from app.core.config import Settings
from app.core.path_safety import is_safe_component

logger = logging.getLogger(__name__)

FILENAME = "craftpanel.txt"
MAX_FILE_BYTES = 64 * 1024
MIN_HINT_LENGTH = 4
_GIBIBYTE = 1024**3
_MEBIBYTE = 1024**2

_SECTION_LINE = re.compile(r"^\s*\[([^\[\]]*)\]\s*$")
_KEY_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*=(.*)$")
_START_SCRIPT_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,99}$")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_DURATION = re.compile(r"^(\d{1,6})\s*(s|m|h|d)$", re.IGNORECASE)
_SIZE = re.compile(r"^(\d{1,7})\s*(m|mb|g|gb|t|tb)$", re.IGNORECASE)
_TIME_OF_DAY = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_HOSTNAME_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")
_MOD_PATTERN = re.compile(r"^[A-Za-z0-9_.*?+\-]{2,100}$")
_ATTEMPTS = 6
_RETRY_SECONDS = 0.2


# ---------------------------------------------------------------------------
# Problems


@dataclass(frozen=True, slots=True)
class SettingsProblem:
    message: str
    line: int | None = None
    field: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"line": self.line, "field": self.field, "message": self.message}


def format_problems(problems: Iterable[SettingsProblem]) -> str:
    return "\n".join(
        f"Línea {problem.line}: {problem.message}" if problem.line else problem.message for problem in problems
    )


class SettingsFileError(ValueError):
    """The file or the submitted values are not valid; ``errors`` says where."""

    def __init__(self, errors: list[SettingsProblem]) -> None:
        self.errors = errors
        super().__init__(format_problems(errors))


class _Invalid(ValueError):
    """Raised by a value parser with a plain Spanish message."""


# ---------------------------------------------------------------------------
# Value parsers. Each takes the text from the file and returns the typed value.


@dataclass(frozen=True, slots=True)
class ValidationContext:
    server_directory: Path | None = None

    def world_directory(self) -> Path | None:
        if self.server_directory is None:
            return None
        level = "world"
        with contextlib.suppress(OSError):
            for line in (self.server_directory / "server.properties").read_text(encoding="utf-8", errors="replace").splitlines():
                key, separator, value = line.partition("=")
                if separator and key.strip() == "level-name" and is_safe_component(value.strip()):
                    level = value.strip()
        return self.server_directory / level


def _windows_host() -> bool:
    return sys.platform == "win32"


def parse_start_script(value: str, _: ValidationContext) -> str:
    if "/" in value or "\\" in value or ".." in value or ":" in value:
        raise _Invalid("Escribí solo el nombre del archivo (por ejemplo run.bat), sin carpetas.")
    if not _START_SCRIPT_NAME.match(value) or not is_safe_component(value):
        raise _Invalid("Usá solo letras, números, puntos, guiones y guiones bajos, sin espacios.")
    suffix = Path(value).suffix.casefold()
    allowed = (".bat", ".cmd") if _windows_host() else (".sh",)
    if suffix not in allowed:
        raise _Invalid("Tiene que ser un archivo .bat o .cmd." if _windows_host() else "Tiene que ser un archivo .sh.")
    return value


def normalize_path_text(value: str) -> str:
    """Trim spaces and the quotes Windows adds when copying a path."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    return value


def _absolute_local_path(value: str, example: str) -> Path:
    if _CONTROL_CHARACTERS.search(value):
        raise _Invalid("La ruta tiene caracteres que no se pueden usar.")
    if value.startswith(("\\\\", "//")):
        raise _Invalid("Usá una carpeta de esta computadora, no de la red.")
    if _windows_host():
        windows_path = PureWindowsPath(value)
        if not windows_path.drive or not windows_path.is_absolute() or ":" in value[2:]:
            raise _Invalid(f"Escribí la ruta completa, por ejemplo {example}.")
    elif not value.startswith("/"):
        raise _Invalid("Escribí la ruta completa.")
    return Path(value)


def parse_java(value: str, _: ValidationContext) -> str:
    value = normalize_path_text(value)
    path = _absolute_local_path(value, "C:\\Program Files\\Java\\bin\\java.exe")
    names = {"java.exe", "javaw.exe"} if _windows_host() else {"java", "javaw"}
    if path.name.casefold() not in names:
        raise _Invalid("Tiene que terminar en java.exe o javaw.exe." if _windows_host() else "Tiene que terminar en java.")
    try:
        if not path.is_file():
            raise _Invalid("No encontramos ese archivo. Revisá que la ruta esté bien escrita.")
    except OSError as error:
        raise _Invalid("No pudimos revisar esa ruta.") from error
    return value


def parse_bool(value: str, _: ValidationContext) -> bool:
    lowered = value.casefold()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise _Invalid("Escribí true (sí) o false (no).")


def parse_duration_seconds(value: str) -> int:
    match = _DURATION.match(value.strip())
    if not match:
        raise _Invalid("Escribí un tiempo como 90s, 10m, 6h o 2d.")
    amount, unit = int(match.group(1)), match.group(2).casefold()
    return amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def parse_size_bytes(value: str) -> int:
    match = _SIZE.match(value.strip())
    if not match:
        raise _Invalid("Escribí un tamaño como 512MB o 15GB.")
    amount, unit = int(match.group(1)), match.group(2).casefold()[0]
    return amount * {"m": _MEBIBYTE, "g": _GIBIBYTE, "t": 1024 * _GIBIBYTE}[unit]


def _describe_seconds(seconds: int) -> str:
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _duration(minimum: int, maximum: int) -> Callable[[str, ValidationContext], int]:
    def parse(value: str, _: ValidationContext) -> int:
        seconds = parse_duration_seconds(value)
        if not minimum <= seconds <= maximum:
            raise _Invalid(f"Tiene que estar entre {_describe_seconds(minimum)} y {_describe_seconds(maximum)}.")
        return seconds

    return parse


def _integer(minimum: int, maximum: int) -> Callable[[str, ValidationContext], int]:
    def parse(value: str, _: ValidationContext) -> int:
        if not re.fullmatch(r"\d{1,6}", value):
            raise _Invalid("Escribí un número entero.")
        number = int(value)
        if not minimum <= number <= maximum:
            raise _Invalid(f"Tiene que estar entre {minimum} y {maximum}.")
        return number

    return parse


def host_memory_limits() -> tuple[int, int]:
    """(total GB, largest recommended GB): keep 2 GB for Windows, as the RAM selector does."""
    import psutil

    total_gb = max(1, int(psutil.virtual_memory().total / _GIBIBYTE))
    recommended = max(1, min(64, total_gb - 2 if total_gb > 3 else total_gb))
    return total_gb, recommended


def parse_memory_gb(value: str, _: ValidationContext) -> int:
    size = parse_size_bytes(value if not re.fullmatch(r"\d+", value) else f"{value}G")
    if size % _GIBIBYTE:
        raise _Invalid("Usá gigas enteros, por ejemplo 6G.")
    gigabytes = size // _GIBIBYTE
    _, recommended = host_memory_limits()
    if not 1 <= gigabytes <= recommended:
        raise _Invalid(f"Esta computadora necesita guardar memoria para Windows: elegí entre 1G y {recommended}G.")
    return gigabytes


def parse_size_gb(value: str, _: ValidationContext) -> int:
    size = parse_size_bytes(value)
    if size < _GIBIBYTE:
        raise _Invalid("Tiene que ser al menos 1GB.")
    if size > 10_000 * _GIBIBYTE:
        raise _Invalid("Tiene que ser como mucho 10000GB.")
    return max(1, size // _GIBIBYTE)


def parse_time_of_day(value: str, _: ValidationContext) -> tuple[int, int]:
    match = _TIME_OF_DAY.match(value.strip())
    if not match:
        raise _Invalid("Escribí la hora en formato de 24 horas, por ejemplo 05:30.")
    return int(match.group(1)), int(match.group(2))


def parse_server_name(value: str, _: ValidationContext) -> str:
    if _CONTROL_CHARACTERS.search(value):
        raise _Invalid("Tiene caracteres que no se pueden usar.")
    if len(value) > 80:
        raise _Invalid("Es muy largo: el máximo es 80 letras.")
    return value


def parse_public_address(value: str, _: ValidationContext) -> str:
    host, separator, port_text = value.rpartition(":") if value.count(":") == 1 else (value, "", "")
    if separator:
        if not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            raise _Invalid("El puerto tiene que ser un número entre 1 y 65535.")
    if not host or len(host) > 253:
        raise _Invalid("Escribí una dirección como mi-servidor.ejemplo.com o mi-servidor.ejemplo.com:25565.")
    with contextlib.suppress(ValueError):
        ipaddress.IPv4Address(host)
        return value
    labels = host.rstrip(".").split(".")
    if not all(_HOSTNAME_LABEL.match(label) for label in labels):
        raise _Invalid("Escribí una dirección como mi-servidor.ejemplo.com o mi-servidor.ejemplo.com:25565.")
    return value


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        return os.path.normcase(str(path.resolve())).startswith(os.path.normcase(str(parent.resolve())).rstrip("\\/") + os.sep) or (
            os.path.normcase(str(path.resolve())) == os.path.normcase(str(parent.resolve()))
        )
    except OSError:
        return False


def parse_backup_location(value: str, context: ValidationContext) -> str:
    value = normalize_path_text(value)
    path = _absolute_local_path(value, "D:\\Copias del servidor")
    if path.parent == path or (_windows_host() and PureWindowsPath(value).parent == PureWindowsPath(value)):
        raise _Invalid("Elegí una carpeta, no la raíz del disco (por ejemplo D:\\Copias del servidor).")
    if context.server_directory is not None and _is_relative_to(path, context.server_directory):
        raise _Invalid("Tiene que estar fuera de la carpeta del servidor, así una copia nunca se guarda dentro del mundo.")
    existing = path
    while not existing.exists():
        if existing.parent == existing:
            raise _Invalid("No encontramos ese disco.")
        existing = existing.parent
    if not existing.is_dir():
        raise _Invalid("Esa ruta es un archivo, no una carpeta.")
    probe = existing / f".craftpanel-write-test-{uuid.uuid4().hex}"
    try:
        probe.write_bytes(b"")
    except OSError as error:
        raise _Invalid("No se puede escribir en esa carpeta. Elegí otra.") from error
    finally:
        with contextlib.suppress(OSError):
            probe.unlink()
    return value


# ---------------------------------------------------------------------------
# List item parsers


def parse_hint(value: str, _: ValidationContext) -> str:
    if _CONTROL_CHARACTERS.search(value):
        raise _Invalid("Tiene caracteres que no se pueden usar.")
    if len(value) < MIN_HINT_LENGTH:
        raise _Invalid(f"Es muy corta: usá al menos {MIN_HINT_LENGTH} letras para no confundir otros programas.")
    if len(value) > 100:
        raise _Invalid("Es muy larga: el máximo es 100 letras.")
    return value


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    pattern: str
    regex: re.Pattern[str]
    negated: bool
    directory_only: bool
    anchored: bool

    def matches(self, relative: str, is_directory: bool) -> bool:
        if self.directory_only and not is_directory:
            return False
        target = relative if self.anchored else relative.rsplit("/", 1)[-1]
        return self.regex.fullmatch(target) is not None


def _glob_to_regex(glob: str) -> str:
    parts: list[str] = []
    index = 0
    length = len(glob)
    while index < length:
        character = glob[index]
        at_segment_start = index == 0 or glob[index - 1] == "/"
        if glob.startswith("**/", index) and at_segment_start:
            parts.append("(?:.*/)?")
            index += 3
            continue
        if glob.startswith("**", index) and at_segment_start and index + 2 == length:
            parts.append(".*")
            index += 2
            continue
        if character == "*":
            parts.append("[^/]*")
        elif character == "?":
            parts.append("[^/]")
        elif character == "[":
            closing = glob.find("]", index + 1)
            if closing == -1:
                parts.append(re.escape(character))
            else:
                body = glob[index + 1 : closing].replace("\\", "\\\\")
                if body.startswith("!"):
                    body = "^" + body[1:]
                parts.append(f"[{body}]")
                index = closing
        else:
            parts.append(re.escape(character))
        index += 1
    return "".join(parts)


def compile_ignore_pattern(line: str) -> IgnoreRule | None:
    """Compile one gitignore-style line; ``None`` for comments and blank lines."""
    pattern = line.strip()
    if not pattern or pattern.startswith("#"):
        return None
    negated = pattern.startswith("!")
    if negated:
        pattern = pattern[1:]
    elif pattern.startswith(("\\#", "\\!")):
        pattern = pattern[1:]
    directory_only = pattern.endswith("/")
    pattern = pattern.rstrip("/")
    anchored = "/" in pattern
    pattern = pattern.lstrip("/")
    if not pattern:
        raise ValueError("empty pattern")
    return IgnoreRule(line.strip(), re.compile(_glob_to_regex(pattern), re.IGNORECASE), negated, directory_only, anchored)


def _gitignore_rule(value: str) -> IgnoreRule | None:
    if _CONTROL_CHARACTERS.search(value):
        raise _Invalid("Tiene caracteres que no se pueden usar.")
    if len(value) > 300:
        raise _Invalid("Es muy larga: el máximo es 300 letras.")
    body = value[1:] if value.startswith(("!", "\\#", "\\!")) else value
    if body.startswith("\\"):
        body = body[1:]
    if "\\" in body:
        raise _Invalid("Usá / para separar carpetas, no \\.")
    if ".." in body.split("/") or ":" in body:
        raise _Invalid("No uses .. ni letras de disco: las rutas son dentro de la carpeta.")
    try:
        return compile_ignore_pattern(value)
    except (ValueError, re.error) as error:
        raise _Invalid("Esa regla no dice ningún archivo: escribí un archivo o una carpeta, por ejemplo logs/.") from error


# What [backup_exclude] may never leave out: without these a copy is not a world.
_WORLD_ESSENTIALS: tuple[tuple[str, bool], ...] = (("level.dat", False), ("region", True))
# Samples of what the panel must be able to change; [protected] may not cover several at once.
_PANEL_NEEDS: tuple[tuple[str, bool], ...] = (
    ("server.properties", False),
    ("mods", True),
    ("world", True),
    ("config", True),
    ("mods/example.jar", False),
)


def parse_backup_exclude(value: str, _: ValidationContext) -> str:
    rule = _gitignore_rule(value)
    if rule is not None and not rule.negated:
        if any(rule.matches(path, is_directory) for path, is_directory in _WORLD_ESSENTIALS):
            raise _Invalid(
                "Esa regla dejaría afuera todo el mundo o su parte principal (level.dat o region). Las copias no servirían."
            )
    return value


def parse_protected(value: str, _: ValidationContext) -> str:
    rule = _gitignore_rule(value)
    if rule is not None and not rule.negated:
        covered = sum(rule.matches(path, is_directory) for path, is_directory in _PANEL_NEEDS)
        if covered >= 2:
            raise _Invalid("Es demasiado amplia: protegería casi todo y el panel no podría hacer nada. Nombrá archivos o carpetas concretas.")
    return value


def parse_backup_include(value: str, context: ValidationContext) -> str:
    if _CONTROL_CHARACTERS.search(value) or len(value) > 200:
        raise _Invalid("Escribí una ruta corta, sin caracteres raros.")
    if "\\" in value:
        raise _Invalid("Usá / para separar carpetas, no \\.")
    if any(character in value for character in "*?[]!"):
        raise _Invalid("Escribí archivos o carpetas concretas, sin * ni ?.")
    parts = [part for part in value.strip("/").split("/") if part]
    if not parts or value.startswith("/") or not all(is_safe_component(part) for part in parts):
        raise _Invalid("Escribí una ruta dentro de la carpeta del servidor, por ejemplo config/.")
    world = context.world_directory()
    if world is not None and parts[0].casefold() == world.name.casefold():
        raise _Invalid("El mundo ya se copia siempre; acá van otras cosas, como config/ o server.properties.")
    if parts[0].casefold() in {"backups", "simplebackups"} or parts[0].startswith(".world-"):
        raise _Invalid("Las copias no pueden incluir otras copias.")
    return value


def parse_server_only_mod(value: str, _: ValidationContext) -> str:
    if not _MOD_PATTERN.match(value):
        raise _Invalid("Escribí el nombre del archivo del mod (se puede usar *) o su identificador, sin espacios ni carpetas.")
    if value.strip("*?.") == "" or value in {"*.jar", "*jar"}:
        raise _Invalid("Es demasiado amplia: dejaría a tus amigos sin ningún mod.")
    return value


# ---------------------------------------------------------------------------
# Schema


ValueParser = Callable[[str, ValidationContext], Any]


@dataclass(frozen=True, slots=True)
class KeySpec:
    name: str
    parser: ValueParser
    default: str
    needs_stopped_server: bool = False
    # Keys whose fallback lives elsewhere in the panel start empty in a new file.
    template: str | None = None

    @property
    def template_value(self) -> str:
        return self.default if self.template is None else self.template


@dataclass(frozen=True, slots=True)
class SectionSpec:
    name: str
    parser: ValueParser
    max_items: int


KEYS: dict[str, KeySpec] = {
    spec.name: spec
    for spec in (
        KeySpec("start_script", parse_start_script, "", needs_stopped_server=True),
        KeySpec("java", parse_java, "", needs_stopped_server=True),
        KeySpec("memory", parse_memory_gb, ""),
        KeySpec("start_with_panel", parse_bool, "false"),
        KeySpec("startup_timeout", _duration(30, 3600), "5m"),
        KeySpec("restart_on_crash", parse_bool, "false"),
        KeySpec("max_crash_restarts", _integer(1, 20), "3"),
        KeySpec("daily_restart", parse_time_of_day, ""),
        KeySpec("restart_warning", _duration(10, 600), "60s"),
        KeySpec("backup_interval", _duration(3600, 168 * 3600), "6h", template=""),
        KeySpec("backup_keep", _integer(1, 100), "4", template=""),
        KeySpec("backup_max_size", parse_size_gb, "15GB", template=""),
        KeySpec("backup_location", parse_backup_location, ""),
        KeySpec("server_name", parse_server_name, ""),
        KeySpec("public_address", parse_public_address, ""),
    )
}
SECTIONS: dict[str, SectionSpec] = {
    spec.name: spec
    for spec in (
        SectionSpec("detect", parse_hint, 20),
        SectionSpec("backup_exclude", parse_backup_exclude, 200),
        SectionSpec("backup_include", parse_backup_include, 50),
        SectionSpec("server_only_mods", parse_server_only_mod, 200),
        SectionSpec("protected", parse_protected, 200),
    )
}

DEFAULT_TEXT = """\
# Craft Panel · ajustes de este servidor
#
# Podés editar este archivo a mano (por ejemplo con el Bloc de notas)
# o desde Ajustes, en la parte «Tu servidor» del panel.
#
# Cómo se escribe:
#   - Las líneas que empiezan con # son comentarios: el panel no las lee.
#   - «nombre = valor» guarda un ajuste. Si dejás el valor vacío, el panel
#     usa lo de siempre (lo que dice «Vacío =» arriba de cada uno).
#   - Sí o no se escribe true o false.
#   - Los tiempos se escriben 90s, 10m, 6h o 2d (segundos, minutos, horas, días).
#   - Los tamaños se escriben 512MB o 15GB.
#   - Un nombre entre corchetes, como [detect], empieza una lista: cada línea
#     que sigue es un elemento, hasta el próximo nombre entre corchetes.
#   - Si agregás cosas que el panel no conoce, las deja tal como están.

# ----- Encender y apagar -----

# Archivo que enciende el servidor (dentro de esta carpeta).
# Vacío = run.bat. Solo letras, números, puntos y guiones, sin espacios.
start_script =

# Java para este servidor: la ruta completa a java.exe.
# Vacío = el panel elige solo.
# Ejemplo: java = C:\\Program Files\\Eclipse Adoptium\\jdk-21\\bin\\java.exe
java =

# Memoria para el servidor, por ejemplo 6G.
# Vacío = lo que elegiste al preparar el servidor.
memory =

# Encender el servidor solo cuando se abre el panel (true o false).
start_with_panel = false

# Cuánto esperar a que cargue el mundo antes de avisar que tarda.
startup_timeout = 5m

# Volver a encenderlo solo si se cierra por un error (true o false).
restart_on_crash = false

# Si se cae esta cantidad de veces en 10 minutos, deja de intentar.
max_crash_restarts = 3

# Reiniciar todos los días a esta hora (24 horas, por ejemplo 05:30).
# Vacío = no reiniciar solo.
daily_restart =

# Cuánto antes avisar en el chat que se va a reiniciar.
restart_warning = 60s

# ----- Copias -----

# Cada cuánto hacer una copia del mundo (como mínimo 1h).
# Vacío = lo que elegiste en «Copias automáticas» (6h si nunca lo cambiaste).
backup_interval =

# Cuántas copias guardar. Vacío = 4.
backup_keep =

# Espacio máximo para todas las copias juntas. Vacío = 15GB.
backup_max_size =

# Carpeta donde guardar las copias, mejor si es en otro disco.
# Vacío = la carpeta backups del panel.
# Ejemplo: backup_location = D:\\Copias del servidor
backup_location =

# ----- Mods y amigos -----

# Nombre del servidor en el panel, en Discord y en la imagen de estado.
# Vacío = el de siempre.
server_name =

# Dirección para tus amigos, por ejemplo mi-servidor.ejemplo.com:25565.
# Vacío = el panel la busca solo.
public_address =

[detect]
# Palabras que aparecen al abrir tu servidor y ayudan a reconocerlo
# cuando lo abriste fuera del panel (una por línea).
# Por ejemplo, el nombre del .jar que arranca tu servidor.

[backup_exclude]
# Archivos o carpetas del mundo que no hace falta guardar en las copias.
# Funciona como .gitignore: *.tmp, carpeta/, **/cache/
# Una línea que empieza con ! vuelve a incluir algo que otra regla sacó.
# level.dat y la carpeta region siempre se copian.
# Ojo: al restaurar una copia, lo que no se copió no vuelve.

[backup_include]
# Otras cosas de la carpeta del servidor para guardar en cada copia,
# por ejemplo config/ o server.properties (una por línea).

[server_only_mods]
# Mods que son solo del servidor: no se mandan a tus amigos.
# Escribí el nombre del archivo (se puede usar *) o el identificador del mod.

[protected]
# Archivos o carpetas que el panel nunca debe cambiar ni borrar.
# Funciona como .gitignore, desde la carpeta del servidor.
"""

LineKind = Literal["blank", "comment", "section", "key", "item", "other"]


@dataclass(slots=True)
class _Line:
    text: str
    kind: LineKind
    section: str | None
    key: str | None = None
    value: str = ""


@dataclass(slots=True)
class _Document:
    lines: list[_Line]
    newline: str
    problems: list[SettingsProblem]

    def render(self) -> str:
        return self.newline.join(line.text for line in self.lines) + self.newline


# ---------------------------------------------------------------------------
# Parsed result


@dataclass(frozen=True, slots=True)
class ServerFileSettings:
    """Validated values. Invalid entries fall back to their default and are listed in ``problems``."""

    exists: bool = False
    values: Mapping[str, Any] = field(default_factory=dict)
    texts: Mapping[str, str] = field(default_factory=dict)
    lists: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    list_texts: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    problems: tuple[SettingsProblem, ...] = ()
    raw: str = DEFAULT_TEXT

    def value(self, key: str) -> Any:
        """The typed value written in the file, or ``None`` when absent, empty or invalid."""
        return self.values.get(key)

    def is_set(self, key: str) -> bool:
        return self.values.get(key) is not None

    def items(self, section: str) -> tuple[str, ...]:
        return self.lists.get(section, ())

    def _typed_default(self, key: str) -> Any:
        spec = KEYS[key]
        return spec.parser(spec.default, ValidationContext()) if spec.default else None

    def effective(self, key: str) -> Any:
        """Value from the file, else the built-in default from the schema."""
        value = self.values.get(key)
        return value if value is not None else self._typed_default(key)

    # Convenience accessors used across the panel.
    @property
    def start_script(self) -> str | None:
        return self.value("start_script")

    @property
    def java(self) -> str | None:
        return self.value("java")

    @property
    def recognize(self) -> tuple[str, ...]:
        return self.items("detect")

    @property
    def backup_exclude(self) -> tuple[str, ...]:
        return self.items("backup_exclude")

    @property
    def launch_problem(self) -> str | None:
        """Why the server must not start with this file, in plain words."""
        relevant = [problem for problem in self.problems if problem.field in {"start_script", "java"}]
        if not relevant:
            return None
        return f"Revisá {FILENAME} en la carpeta del servidor (o Ajustes › Tu servidor). {format_problems(relevant)}"


# ---------------------------------------------------------------------------
# Parsing and rendering


def _normalize_name(name: str) -> str:
    return re.sub(r"[\s-]+", "_", name.strip()).casefold()


def _parse(text: str) -> _Document:
    if text.startswith("\ufeff"):
        text = text[1:]
    newline = "\r\n" if "\r\n" in text else "\n"
    lines: list[_Line] = []
    problems: list[SettingsProblem] = []
    section: str | None = None
    seen_keys: dict[str, int] = {}
    seen_sections: dict[str, int] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        header = _SECTION_LINE.match(raw)
        if header:
            section = _normalize_name(header.group(1))
            lines.append(_Line(raw, "section", section))
            if section in SECTIONS:
                if section in seen_sections:
                    problems.append(SettingsProblem(f"[{section}] ya aparece en la línea {seen_sections[section]}.", number, section))
                seen_sections.setdefault(section, number)
            continue
        if not stripped:
            lines.append(_Line(raw, "blank", section))
        elif stripped.startswith("#"):
            lines.append(_Line(raw, "comment", section))
        elif section is None:
            match = _KEY_LINE.match(raw)
            if not match:
                problems.append(
                    SettingsProblem("No entendemos esta línea. Escribila como «nombre = valor» o empezala con #.", number)
                )
                lines.append(_Line(raw, "other", section))
                continue
            key = match.group(1).casefold()
            lines.append(_Line(raw, "key", section, key, match.group(2).strip()))
            if key in KEYS:
                if key in seen_keys:
                    problems.append(SettingsProblem(f"«{key}» ya aparece en la línea {seen_keys[key]}.", number, key))
                seen_keys.setdefault(key, number)
        elif section in SECTIONS:
            lines.append(_Line(raw, "item", section, value=stripped))
        else:
            lines.append(_Line(raw, "other", section))
    return _Document(lines, newline, problems)


def _validated(document: _Document, exists: bool, raw: str, context: ValidationContext) -> ServerFileSettings:
    problems = list(document.problems)
    values: dict[str, Any] = {}
    texts: dict[str, str] = {}
    lists: dict[str, list[str]] = {name: [] for name in SECTIONS}
    list_texts: dict[str, list[str]] = {name: [] for name in SECTIONS}
    for number, line in enumerate(document.lines, start=1):
        if line.kind == "key" and line.key in KEYS and line.key not in texts:
            texts[line.key] = line.value
            if not line.value:
                continue
            try:
                values[line.key] = KEYS[line.key].parser(line.value, context)
            except _Invalid as error:
                problems.append(SettingsProblem(str(error), number, line.key))
        elif line.kind == "item" and line.section in SECTIONS:
            spec = SECTIONS[line.section]
            list_texts[spec.name].append(line.value)
            count = len(list_texts[spec.name])
            if count == spec.max_items + 1:
                problems.append(SettingsProblem(f"[{spec.name}] admite hasta {spec.max_items} líneas.", number, spec.name))
            if count > spec.max_items:
                continue
            try:
                lists[spec.name].append(spec.parser(line.value, context))
            except _Invalid as error:
                problems.append(SettingsProblem(str(error), number, spec.name))
    problems.sort(key=lambda problem: problem.line or 0)
    return ServerFileSettings(
        exists=exists,
        values=values,
        texts=texts,
        lists={name: tuple(dict.fromkeys(items)) if name == "detect" else tuple(items) for name, items in lists.items()},
        list_texts={name: tuple(items) for name, items in list_texts.items()},
        problems=tuple(problems),
        raw=raw,
    )


def parse_text(text: str, *, exists: bool = True, context: ValidationContext | None = None) -> ServerFileSettings:
    """Parse and validate ``text``; invalid entries are reported, never applied."""
    return _validated(_parse(text), exists, text, context or ValidationContext())


def _set_key(document: _Document, key: str, value: str) -> None:
    text = f"{key} = {value}" if value else f"{key} ="
    for line in document.lines:
        if line.kind == "key" and line.key == key:
            if line.value != value:
                line.text = text
                line.value = value
            return
    # Missing key: add it at the end of the variables, before the first list.
    insert_at = next((index for index, line in enumerate(document.lines) if line.kind == "section"), len(document.lines))
    while insert_at > 0 and document.lines[insert_at - 1].kind == "blank":
        insert_at -= 1
    document.lines[insert_at:insert_at] = [_Line("", "blank", None), _Line(text, "key", None, key, value)]


def _set_list(document: _Document, section: str, items: list[str]) -> None:
    current = [line.value for line in document.lines if line.kind == "item" and line.section == section]
    if current == items:
        return
    start = next(
        (index for index, line in enumerate(document.lines) if line.kind == "section" and line.section == section),
        None,
    )
    if start is None:
        if document.lines and document.lines[-1].kind != "blank":
            document.lines.append(_Line("", "blank", None))
        document.lines.append(_Line(f"[{section}]", "section", section))
        start = len(document.lines) - 1
    end = start + 1
    while end < len(document.lines) and document.lines[end].kind != "section":
        end += 1
    body = document.lines[start + 1 : end]
    first_item = next((index for index, line in enumerate(body) if line.kind == "item"), None)
    kept = [line for line in body if line.kind != "item"]
    if first_item is None:
        # After the section's own comments, before the blank lines that separate it from the next one.
        position = len(kept)
        while position > 0 and kept[position - 1].kind == "blank":
            position -= 1
    else:
        position = sum(1 for line in body[:first_item] if line.kind != "item")
    new_items = [_Line(item, "item", section, value=item) for item in items]
    document.lines[start + 1 : end] = kept[:position] + new_items + kept[position:]


# ---------------------------------------------------------------------------
# gitignore-style matching for [backup_exclude] and [protected]


class GitignoreMatcher:
    """Applies rules like git does: the last matching rule wins, folders cover their contents."""

    def __init__(self, patterns: Iterable[str]) -> None:
        self.rules: list[IgnoreRule] = []
        for pattern in patterns:
            with contextlib.suppress(ValueError, re.error):
                rule = compile_ignore_pattern(pattern)
                if rule is not None:
                    self.rules.append(rule)

    def __bool__(self) -> bool:
        return bool(self.rules)

    def _own_verdict(self, relative: str, is_directory: bool) -> bool:
        matched = False
        for rule in self.rules:
            if rule.matches(relative, is_directory):
                matched = not rule.negated
        return matched

    def matches(self, relative: str, is_directory: bool = False) -> bool:
        """Whether ``relative`` (forward slashes) is covered by the rules."""
        parts = [part for part in relative.replace("\\", "/").split("/") if part and part != "."]
        if not parts:
            return False
        # Git cannot re-include a file whose parent folder is excluded.
        for depth in range(1, len(parts)):
            if self._own_verdict("/".join(parts[:depth]), True):
                return True
        return self._own_verdict("/".join(parts), is_directory)

    is_excluded = matches

    def walk_files(self, root: Path) -> Iterator[Path]:
        """Regular files below ``root`` that are not matched; never follows links."""
        for directory, folders, files in os.walk(root, followlinks=False):
            base = Path(directory)
            relative_base = base.relative_to(root).as_posix()
            prefix = "" if relative_base == "." else f"{relative_base}/"
            kept: list[str] = []
            for folder in folders:
                if (base / folder).is_symlink():
                    continue
                if self.rules and self._own_verdict(f"{prefix}{folder}", True):
                    continue
                kept.append(folder)
            folders[:] = kept
            for name in files:
                if self.rules and self._own_verdict(f"{prefix}{name}", False):
                    continue
                yield base / name


BackupIgnore = GitignoreMatcher


# ---------------------------------------------------------------------------
# Reading and writing the file


class ServerSettingsFile:
    """Reads, validates and atomically saves ``server/craftpanel.txt``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[tuple[int, int], ServerFileSettings]] = {}

    @staticmethod
    def path(configured: Settings) -> Path:
        assert configured.server_directory is not None
        return configured.server_directory / FILENAME

    @staticmethod
    def context(configured: Settings) -> ValidationContext:
        return ValidationContext(server_directory=configured.server_directory)

    def load(self, configured: Settings) -> ServerFileSettings:
        """Current values; defaults (without creating anything) when the file is missing."""
        path = self.path(configured)
        try:
            stat = path.stat()
        except OSError:
            return ServerFileSettings()
        signature = (stat.st_mtime_ns, stat.st_size)
        key = str(path)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1]
        if stat.st_size > MAX_FILE_BYTES:
            result = ServerFileSettings(
                exists=True, problems=(SettingsProblem(f"{FILENAME} es demasiado grande (máximo 64 KB)."),)
            )
        else:
            try:
                text = path.read_bytes().decode("utf-8", errors="replace")
            except OSError as error:
                logger.warning("Could not read %s: %s", path, error)
                return ServerFileSettings()
            result = parse_text(text, context=self.context(configured))
        for problem in result.problems:
            logger.warning("%s line %s: %s", FILENAME, problem.line, problem.message)
        with self._lock:
            self._cache[key] = (signature, result)
        return result

    def check_raw(self, configured: Settings, text: str) -> ServerFileSettings:
        """Parse ``text`` as if it were saved; raises :class:`SettingsFileError` on problems."""
        if len(text.encode("utf-8")) > MAX_FILE_BYTES:
            raise SettingsFileError([SettingsProblem("El archivo es demasiado grande (máximo 64 KB).")])
        result = parse_text(text, context=self.context(configured))
        if result.problems:
            raise SettingsFileError(list(result.problems))
        return result

    def save_raw(self, configured: Settings, text: str) -> ServerFileSettings:
        """Validate the whole text and save it as is."""
        self.check_raw(configured, text)
        document = _parse(text)
        path = self.path(configured)
        # Keep the line endings the user already had; new files follow the host.
        if not path.exists() and "\r\n" not in text and _windows_host():
            document.newline = "\r\n"
        self._write(path, document.render())
        return self.load(configured)

    def preview_fields(
        self,
        configured: Settings,
        values: Mapping[str, str] | None = None,
        lists: Mapping[str, Iterable[str]] | None = None,
    ) -> tuple[str, ServerFileSettings]:
        """Render the file with these changes and validate it, without saving."""
        values = dict(values or {})
        lists = {name: list(items) for name, items in (lists or {}).items()}
        problems: list[SettingsProblem] = []
        context = self.context(configured)
        for key, value in values.items():
            if key not in KEYS:
                problems.append(SettingsProblem(f"«{key}» no es un ajuste que el panel conozca.", field=key))
                continue
            value = normalize_path_text(value) if key in {"java", "backup_location"} else value.strip()
            values[key] = value
            if _CONTROL_CHARACTERS.search(value):
                problems.append(SettingsProblem("Tiene caracteres que no se pueden usar.", field=key))
                continue
            if value:
                try:
                    KEYS[key].parser(value, context)
                except _Invalid as error:
                    problems.append(SettingsProblem(str(error), field=key))
        for name, items in lists.items():
            if name not in SECTIONS:
                problems.append(SettingsProblem(f"[{name}] no es una lista que el panel conozca.", field=name))
                continue
            spec = SECTIONS[name]
            # In the file a line starting with # is a comment, so it can never be a list item.
            cleaned = [item.strip() for item in items if item.strip() and not item.strip().startswith("#")]
            lists[name] = cleaned
            if len(cleaned) > spec.max_items:
                problems.append(SettingsProblem(f"Podés poner hasta {spec.max_items} líneas.", field=name))
                continue
            for index, item in enumerate(cleaned, start=1):
                try:
                    spec.parser(item, context)
                except _Invalid as error:
                    problems.append(SettingsProblem(f"Línea {index} («{item}»): {error}", field=name))
        if problems:
            raise SettingsFileError(problems)

        path = self.path(configured)
        current = self._read_existing(path)
        document = _parse(current if current is not None else DEFAULT_TEXT)
        if current is None and _windows_host():
            document.newline = "\r\n"
        for key, value in values.items():
            _set_key(document, key, value)
        for name, items in lists.items():
            _set_list(document, name, items)
        rendered = document.render()
        # The rest of the file may hold earlier hand-made mistakes; never save on top of them silently.
        result = parse_text(rendered, context=context)
        if result.problems:
            raise SettingsFileError(list(result.problems))
        return rendered, result

    def save_fields(
        self,
        configured: Settings,
        values: Mapping[str, str] | None = None,
        lists: Mapping[str, Iterable[str]] | None = None,
    ) -> ServerFileSettings:
        """Update only the given keys and lists, keeping every other line as the user wrote it."""
        rendered, _ = self.preview_fields(configured, values, lists)
        self._write(self.path(configured), rendered)
        return self.load(configured)

    @staticmethod
    def _read_existing(path: Path) -> str | None:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return None
        if len(data) > MAX_FILE_BYTES:
            raise SettingsFileError([SettingsProblem(f"{FILENAME} es demasiado grande (máximo 64 KB).")])
        return data.decode("utf-8", errors="replace")

    def _write(self, path: Path, text: str) -> None:
        if not path.parent.is_dir():
            raise SettingsFileError([SettingsProblem("Todavía no hay una carpeta del servidor donde guardar esto.")])
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(temporary, "xb") as handle:
                handle.write(text.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            for attempt in range(_ATTEMPTS):
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError:
                    # An editor or the antivirus may hold the file for a moment on Windows.
                    if attempt == _ATTEMPTS - 1:
                        raise
                    time.sleep(_RETRY_SECONDS)
        except OSError as error:
            raise SettingsFileError(
                [SettingsProblem(f"No se pudo guardar {FILENAME}. Cerralo si lo tenés abierto y probá de nuevo.")]
            ) from error
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink()
        with self._lock:
            self._cache.pop(str(path), None)


server_settings_file = ServerSettingsFile()


def read_server_settings(configured: Settings) -> ServerFileSettings:
    return server_settings_file.load(configured)


def free_bytes(path: Path) -> int:
    """Free space on the drive that holds ``path`` (or its nearest existing parent)."""
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    return shutil.disk_usage(current).free
