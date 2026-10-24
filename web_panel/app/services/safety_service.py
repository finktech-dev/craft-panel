"""Answer "is anything wrong?" in plain words: access, disk space, backups and problems."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.core.config import Settings, settings
from app.services.external_server_service import ExternalServer, ExternalServerDetector

Level = Literal["ok", "warn", "danger", "unknown"]
_LEVEL_ORDER: dict[str, int] = {"unknown": 0, "ok": 1, "warn": 2, "danger": 3}
_GIBIBYTE = 1024**3
_RECENT_CRASH_SECONDS = 7 * 24 * 3600


class SafetyItem(BaseModel):
    key: str
    label: str
    level: Level
    title: str
    detail: str
    action_label: str | None = None
    action_href: str | None = None


class SafetySummary(BaseModel):
    level: Level
    headline: str
    items: list[SafetyItem]


def _ago(seconds: float) -> str:
    """Human Spanish wording such as "hace 5 minutos", "hace 3 horas", "ayer"."""
    minutes, hours, days = seconds / 60, seconds / 3600, seconds / 86400
    if minutes < 60:
        value = max(round(minutes), 1)
        return f"hace {value} minuto{'s' if value != 1 else ''}"
    if hours < 24:
        value = round(hours)
        return f"hace {value} hora{'s' if value != 1 else ''}"
    if days < 2:
        return "ayer"
    return f"hace {round(days)} días"


def access_item(properties: dict[str, str], whitelisted_players: int, public_tunnel: bool) -> SafetyItem:
    online_mode = properties.get("online-mode", "true").lower() == "true"
    whitelist = properties.get("white-list", "false").lower() == "true"
    action = {"action_label": "Elegir quién puede entrar", "action_href": "/worlds#whitelist"}
    friends = f"{whitelisted_players} amigo{'s' if whitelisted_players != 1 else ''}"
    if whitelist and online_mode:
        return SafetyItem(key="access", label="Acceso", level="ok", title="Solo entran tus amigos",
                          detail=f"Hay {friends} en la lista.", **action)
    if whitelist:
        return SafetyItem(key="access", label="Acceso", level="warn", title="Alguien podría hacerse pasar por un amigo",
                          detail="Tu servidor acepta cuentas no oficiales, así que la lista de amigos ayuda pero no lo "
                                 "evita del todo. Si todos tienen Minecraft original, activá las cuentas oficiales en Ajustes.",
                          action_label="Ver ajustes del mundo", action_href="/worlds#props")
    if online_mode and not public_tunnel:
        return SafetyItem(key="access", label="Acceso", level="ok", title="Solo se puede entrar desde tu casa",
                          detail="El servidor no está abierto a Internet.", **action)
    if public_tunnel:
        return SafetyItem(key="access", label="Acceso", level="danger", title="Cualquiera puede entrar a tu servidor",
                          detail="Si alguien consigue la dirección, puede entrar"
                                 + ("." if online_mode else " con el nombre que quiera.")
                                 + " Armá una lista con tus amigos para que solo entren ellos.", **action)
    return SafetyItem(key="access", label="Acceso", level="warn", title="Cualquiera en tu casa puede entrar",
                      detail="Armá una lista de amigos antes de compartir el servidor por Internet.", **action)


def disk_item(free_bytes: int, last_backup_bytes: int | None, reserve_bytes: int) -> SafetyItem:
    needed = (last_backup_bytes or 0) + reserve_bytes
    free_gb = free_bytes / _GIBIBYTE
    action = {"action_label": "Ver copias", "action_href": "/backups"}
    if free_bytes < needed:
        return SafetyItem(key="disk", label="Espacio", level="danger", title="No queda espacio para guardar tu mundo",
                          detail=f"Quedan {free_gb:.0f} GB libres y la próxima copia necesita unos {needed / _GIBIBYTE:.0f} GB. "
                                 "Borrá copias viejas o archivos que no uses.", **action)
    if last_backup_bytes and free_bytes < needed + 2 * last_backup_bytes:
        return SafetyItem(key="disk", label="Espacio", level="warn", title="Queda poco espacio en el disco",
                          detail=f"Quedan {free_gb:.0f} GB: alcanza para pocas copias más.", **action)
    return SafetyItem(key="disk", label="Espacio", level="ok", title=f"Hay {free_gb:.0f} GB libres",
                      detail="Alcanza para las copias automáticas.", **action)


def backup_item(newest_backup_age_seconds: float | None, interval_hours: int, world_exists: bool) -> SafetyItem:
    action = {"action_label": "Ver copias", "action_href": "/backups"}
    if newest_backup_age_seconds is None:
        level: Level = "danger" if world_exists else "unknown"
        return SafetyItem(key="backups", label="Copias", level=level, title="Tu mundo todavía no tiene copia",
                          detail="Hacé una antes de instalar mods o cambiar cosas grandes.", **action)
    hours = newest_backup_age_seconds / 3600
    if hours > 2 * interval_hours + 1:
        return SafetyItem(key="backups", label="Copias", level="warn",
                          title=f"La última copia es de {_ago(newest_backup_age_seconds)}",
                          detail=f"Deberían hacerse cada {interval_hours} horas. Revisá que el panel haya estado abierto.",
                          **action)
    return SafetyItem(key="backups", label="Copias", level="ok",
                      title=f"Última copia {_ago(newest_backup_age_seconds)}",
                      detail="Se revisó que esté completa.", **action)


def diagnostics_item(external: ExternalServer | None, newest_crash_age_seconds: float | None) -> SafetyItem:
    if external is not None:
        return SafetyItem(key="diagnostics", label="Problemas", level="warn",
                          title="El servidor ya está abierto en otra ventana",
                          detail=external.message, action_label="Ver qué hacer", action_href="/#external-server")
    if newest_crash_age_seconds is not None and newest_crash_age_seconds < _RECENT_CRASH_SECONDS:
        return SafetyItem(key="diagnostics", label="Problemas", level="warn",
                          title=f"El servidor se cerró solo {_ago(newest_crash_age_seconds)}",
                          detail="Casi siempre lo causa un mod. El informe te dice cuál.",
                          action_label="Ver qué pasó", action_href="/crashes")
    return SafetyItem(key="diagnostics", label="Problemas", level="ok", title="Sin cierres inesperados",
                      detail="No hubo problemas en la última semana.", action_label="Ver historial", action_href="/crashes")


def summarize(items: list[SafetyItem]) -> SafetySummary:
    level = max((item.level for item in items), key=_LEVEL_ORDER.__getitem__, default="unknown")
    headline = {
        "danger": "Hay algo importante para revisar",
        "warn": "Hay algunas cosas para revisar",
        "ok": "Todo en orden",
        "unknown": "Todavía no hay datos suficientes",
    }[level]
    return SafetySummary(level=level, headline=headline, items=items)


class SafetyService:
    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings
        self._detector = ExternalServerDetector(configured_settings)

    def summary(self, properties: dict[str, str], public_tunnel: bool, own_pid: int | None) -> SafetySummary:
        assert self._settings.server_directory is not None and self._settings.backups_directory is not None
        backups = self._panel_backups()
        newest = max(backups, key=lambda path: path.stat().st_mtime, default=None)
        world = self._settings.server_directory / properties.get("level-name", "world")
        disk_root = self._settings.backups_directory if self._settings.backups_directory.is_dir() else self._settings.server_directory
        return summarize([
            access_item(properties, self._whitelisted_players(), public_tunnel),
            disk_item(
                shutil.disk_usage(disk_root).free,
                newest.stat().st_size if newest else None,
                self._settings.backup_min_free_disk_gb * _GIBIBYTE,
            ),
            backup_item(
                time.time() - newest.stat().st_mtime if newest else None,
                self._backup_interval_hours(),
                world.is_dir(),
            ),
            diagnostics_item(self._detector.detect(own_pid), self._newest_crash_age()),
        ])

    def _panel_backups(self) -> list[Path]:
        assert self._settings.backups_directory is not None
        if not self._settings.backups_directory.is_dir():
            return []
        return [path for path in self._settings.backups_directory.rglob("*.zip") if path.is_file()]

    def _whitelisted_players(self) -> int:
        assert self._settings.server_directory is not None
        try:
            entries = json.loads((self._settings.server_directory / "whitelist.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0
        return len(entries) if isinstance(entries, list) else 0

    def _backup_interval_hours(self) -> int:
        assert self._settings.panel_directory is not None
        try:
            value = json.loads((self._settings.panel_directory / ".scheduled_tasks.json").read_text(encoding="utf-8"))
            hours = value.get("backup_interval_hours")
        except (OSError, json.JSONDecodeError, AttributeError):
            hours = None
        return hours if isinstance(hours, int) and hours > 0 else self._settings.auto_backup_interval_hours

    def _newest_crash_age(self) -> float | None:
        directory = self._settings.crash_reports_directory
        if directory is None or not directory.is_dir():
            return None
        reports = [path.stat().st_mtime for path in directory.glob("*.txt") if path.is_file()]
        return time.time() - max(reports) if reports else None


safety_service = SafetyService()
