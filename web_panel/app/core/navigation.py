"""Header links, and which of them each person keeps in the bar or under "Más"."""

from __future__ import annotations

from dataclasses import dataclass

# The browser remembers the choice in this cookie, so the header is drawn right on the first paint.
NAV_COOKIE = "cp_nav"


@dataclass(frozen=True, slots=True)
class NavItem:
    key: str
    href: str
    label: str
    hint: str
    page: str | None
    icon: str


NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem("inicio", "/", "Inicio", "Encender, apagar y la dirección para tus amigos", "dashboard", "home"),
    NavItem("jugadores", "/worlds#whitelist", "Jugadores", "Quién puede entrar", None, "players"),
    NavItem("mundo", "/worlds", "Mundo", "Tu mundo y sus ajustes", "worlds", "world"),
    NavItem("mods", "/mods", "Mods", "Agregar, quitar y actualizar mods", "mods", "mods"),
    NavItem("copias", "/backups", "Copias", "Copias de seguridad del mundo", "backups", "backups"),
    NavItem("consola", "/console", "Consola", "Lo que dice el servidor en vivo", "console", "console"),
    NavItem("problemas", "/crashes", "Problemas", "Por qué se cerró el servidor o se cayó alguien", "crashes", "problems"),
    NavItem("ajustes", "/administration", "Ajustes", "Acceso, Discord, rangos y más", "administration", "settings"),
)
DEFAULT_BAR: tuple[str, ...] = ("inicio", "jugadores", "mundo", "mods", "copias", "consola")
_KEYS = {item.key for item in NAV_ITEMS}


def parse_nav_cookie(value: str | None) -> tuple[str, ...]:
    """Keys kept in the bar. Unknown keys are ignored; a missing or broken cookie means the default."""
    if value is None:
        return DEFAULT_BAR
    keys = tuple(dict.fromkeys(key for key in value.split(".") if key in _KEYS))
    # "-" is how the browser says "nothing in the bar", since an empty cookie may be dropped.
    return keys if keys or value == "-" else DEFAULT_BAR


def nav_layout(bar_keys: tuple[str, ...] | list[str] | None = None) -> dict[str, list[NavItem]]:
    """Split the links into the bar and the "Más" menu, both in the usual order."""
    chosen = set(DEFAULT_BAR if bar_keys is None else bar_keys)
    return {
        "bar": [item for item in NAV_ITEMS if item.key in chosen],
        "more": [item for item in NAV_ITEMS if item.key not in chosen],
        "all": list(NAV_ITEMS),
    }
