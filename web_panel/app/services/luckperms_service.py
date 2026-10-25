"""LuckPerms integration for web editor links and quick commands."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import uuid
from pathlib import Path
import re
from datetime import UTC, datetime
from typing import Any

from app.schemas.luckperms import (
    LuckPermsAvailability,
    LuckPermsCustomRank,
    LuckPermsEditorResponse,
    LuckPermsPanelConfig,
)
from app.services.server_process import server_manager

# "<PlayerName> message" is how Minecraft logs player chat.
_CHAT_LINE = re.compile(r"<[A-Za-z0-9_]{1,16}>")
# "/lp user <name> info" prints "- Primary Group: vip".
_PRIMARY_GROUP = re.compile(r"Primary Group:\s*([A-Za-z0-9_.\-]+)", re.IGNORECASE)
_COLOR_CODE = re.compile(r"§.")


DEFAULT_PRIMARY_RANKS: list[dict[str, Any]] = [
    {
        "id": "owner",
        "name": "Dueño",
        "icon": "👑",
        "weight": 100,
        "perm": "luckperms.*",
        "tag": "&4[Dueño]&r ",
        "desc": "Acceso total y administración absoluta del servidor.",
        "border": "border-red-500/40",
        "bg": "bg-red-950/20",
        "permColor": "border-red-500/40 text-red-300",
        "badge": "bg-red-950 border border-red-500/40 text-red-300",
    },
    {
        "id": "admin",
        "name": "Administrador",
        "icon": "🛡️",
        "weight": 90,
        "perm": "minecraft.admin",
        "tag": "&c[Admin]&r ",
        "desc": "Gestión de jugadores, bans, moderación y control.",
        "border": "border-rose-500/40",
        "bg": "bg-rose-950/20",
        "permColor": "border-rose-500/40 text-rose-300",
        "badge": "bg-rose-950 border border-rose-500/40 text-rose-300",
    },
    {
        "id": "mod",
        "name": "Moderador",
        "icon": "⚔️",
        "weight": 70,
        "perm": "essentialcommands.*",
        "tag": "&b[Mod]&r ",
        "desc": "Soporte, teletransportes, muteo y supervisión de chat.",
        "border": "border-cyan-500/40",
        "bg": "bg-cyan-950/20",
        "permColor": "border-cyan-500/40 text-cyan-300",
        "badge": "bg-cyan-950 border border-cyan-500/40 text-cyan-300",
    },
    {
        "id": "vip",
        "name": "VIP",
        "icon": "⭐",
        "weight": 50,
        "perm": "essentialcommands.fly",
        "tag": "&6[VIP]&r ",
        "desc": "Beneficios estéticos, comandos rápidos y accesos VIP.",
        "border": "border-amber-500/40",
        "bg": "bg-amber-950/20",
        "permColor": "border-amber-500/40 text-amber-300",
        "badge": "bg-amber-950 border border-amber-500/40 text-amber-300",
    },
    {
        "id": "default",
        "name": "Miembro",
        "icon": "👤",
        "weight": 10,
        "perm": "vanilla.member",
        "tag": "&7[Miembro]&r ",
        "desc": "Rango base predeterminado para todos los jugadores que ingresan.",
        "border": "border-zinc-700",
        "bg": "bg-zinc-900/40",
        "permColor": "border-zinc-700 text-zinc-300",
        "badge": "bg-zinc-900 border border-zinc-700 text-zinc-300",
    },
]

DEFAULT_SECONDARY_ROLES: list[dict[str, Any]] = [
    {
        "id": "streamer",
        "name": "Streamer",
        "icon": "📺",
        "tag": "&d[Live]&r ",
        "desc": "Creadores de contenido y transmisiones en vivo.",
        "border": "border-purple-500/40",
        "badge": "bg-purple-950 border border-purple-500/40 text-purple-300",
    },
    {
        "id": "builder",
        "name": "Constructor",
        "icon": "🔨",
        "tag": "&e[Builder]&r ",
        "desc": "Constructor oficial del mundo con acceso a herramientas de edición.",
        "border": "border-yellow-500/40",
        "badge": "bg-yellow-950 border border-yellow-500/40 text-yellow-300",
    },
]


class LuckPermsService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @property
    def _config_file(self) -> Path:
        from app.core.config import settings
        assert settings.panel_directory is not None
        return settings.panel_directory / ".luckperms_config.json"

    @property
    def _presets_directory(self) -> Path:
        from app.core.config import settings
        assert settings.panel_directory is not None
        return settings.panel_directory / "config" / "presets" / "luckperms"

    def _is_mod_installed(self) -> bool:
        from app.core.config import settings
        if settings.mods_directory and settings.mods_directory.is_dir():
            for p in settings.mods_directory.glob("*.jar"):
                if "luckperms" in p.name.lower():
                    return True
        return False

    def get_configuration(self) -> LuckPermsAvailability:
        """Read only local configuration or detect mod presence in server/mods."""
        if not self._config_file.is_file():
            if self._is_mod_installed():
                return LuckPermsAvailability(
                    enabled=True,
                    message="LuckPerms detectado en el servidor de Minecraft.",
                    primary_ranks=DEFAULT_PRIMARY_RANKS,
                    secondary_roles=DEFAULT_SECONDARY_ROLES,
                )
            return LuckPermsAvailability(
                enabled=False,
                message="Los rangos son opcionales. Necesitan el mod LuckPerms; tocá \"Activar rangos\" para empezar.",
            )
        try:
            raw = json.loads(self._config_file.read_text(encoding="utf-8"))
            config = LuckPermsPanelConfig(**raw)
        except (OSError, json.JSONDecodeError, ValueError):
            return LuckPermsAvailability(enabled=False, message="No se pudo leer la configuración local de LuckPerms.")

        primary_ranks = config.primary_ranks
        secondary_roles = config.secondary_roles
        if config.preset:
            preset_path = self._presets_directory / f"{Path(config.preset).name}.json"
            try:
                preset = json.loads(preset_path.read_text(encoding="utf-8"))
                primary_ranks = preset.get("primary_ranks", primary_ranks)
                secondary_roles = preset.get("secondary_roles", secondary_roles)
            except (OSError, json.JSONDecodeError):
                return LuckPermsAvailability(enabled=False, message="El preset de LuckPerms indicado no existe o no es válido.")

        if not config.enabled:
            return LuckPermsAvailability(enabled=False, message="LuckPerms está desactivado en la configuración local.")

        if not primary_ranks and not config.preset:
            primary_ranks = DEFAULT_PRIMARY_RANKS
        if not secondary_roles and not config.preset:
            secondary_roles = DEFAULT_SECONDARY_ROLES

        return LuckPermsAvailability(
            enabled=True,
            message="LuckPerms está configurado para esta instalación.",
            primary_ranks=primary_ranks,
            secondary_roles=secondary_roles,
            custom_ranks=config.custom_ranks,
        )

    def save_configuration(self, config: LuckPermsPanelConfig) -> None:
        # Turning ranks on again must not forget the ranks created from the panel.
        if "custom_ranks" not in config.model_fields_set:
            with contextlib.suppress(OSError, ValueError):
                config.custom_ranks = self._load_config().custom_ranks
        self._write_config(config)

    def _load_config(self) -> LuckPermsPanelConfig:
        """The local file; with none yet, the integration is on by detection, so start from that."""
        try:
            raw = json.loads(self._config_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return LuckPermsPanelConfig(enabled=True)
        return LuckPermsPanelConfig(**raw)

    def _write_config(self, config: LuckPermsPanelConfig) -> None:
        target = self._config_file
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(config.model_dump_json(indent=2), encoding="utf-8")
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

    def save_custom_rank(self, rank: LuckPermsCustomRank) -> LuckPermsAvailability:
        """Remember a rank created from the panel, replacing one with the same id."""
        config = self._load_config()
        config.custom_ranks = [existing for existing in config.custom_ranks if existing.id != rank.id] + [rank]
        self._write_config(config)
        return self.get_configuration()

    def delete_custom_rank(self, rank_id: str) -> LuckPermsAvailability:
        config = self._load_config()
        config.custom_ranks = [existing for existing in config.custom_ranks if existing.id != rank_id]
        self._write_config(config)
        return self.get_configuration()

    def _primary_ladder(self, availability: LuckPermsAvailability) -> list[tuple[str, str]]:
        """Primary ranks as (id, name), lowest weight first: the steps for "Subir" and "Bajar"."""
        ranks: dict[str, tuple[float, str]] = {}
        for rank in availability.primary_ranks:
            rank_id = str(rank.get("id", ""))
            if rank_id:
                ranks[rank_id] = (float(rank.get("weight") or 0), str(rank.get("name") or rank_id))
        for custom in availability.custom_ranks:
            if custom.type == "primary":
                ranks[custom.id] = (float(custom.weight), custom.name)
        return [(rank_id, name) for rank_id, (_, name) in sorted(ranks.items(), key=lambda item: item[1][0])]

    async def _primary_group(self, player: str) -> str | None:
        """Ask LuckPerms for the player's primary group and read it from the console."""
        sent_at = datetime.now(UTC).isoformat()
        await server_manager.send_command(f"/lp user {player} info")
        deadline = asyncio.get_running_loop().time() + 6.0
        while asyncio.get_running_loop().time() < deadline:
            for entry in reversed(server_manager.history[-40:]):
                message = _COLOR_CODE.sub("", str(entry.get("message", "")))
                if str(entry.get("timestamp", "")) < sent_at or _CHAT_LINE.search(message):
                    continue
                if match := _PRIMARY_GROUP.search(message):
                    return match.group(1).lower()
            await asyncio.sleep(0.3)
        return None

    async def change_primary_rank(self, player: str, direction: str) -> dict[str, Any]:
        """Move a player one step up or down the panel's primary ranks, or back to the initial one.

        Uses ``parent set`` instead of a LuckPerms track, so it works with no track set up.
        """
        availability = self.get_configuration()
        if not availability.enabled:
            return {"success": False, "message": "LuckPerms no está habilitado para esta instalación."}
        if not server_manager.is_running:
            return {"success": False, "message": "Encendé el servidor para cambiarle el rango a alguien."}
        ladder = self._primary_ladder(availability)
        names = dict(ladder)
        if direction == "initial":
            target = "default"
        else:
            async with self._lock:
                try:
                    current = await self._primary_group(player)
                except Exception as error:  # noqa: BLE001 - shown to the person as is
                    return {"success": False, "message": f"No se pudo preguntar el rango: {error}"}
            if current is None:
                return {
                    "success": False,
                    "message": f"No pudimos saber el rango de {player}. ¿Ya entró alguna vez al servidor?",
                }
            ids = [rank_id for rank_id, _ in ladder]
            if current not in ids:
                return {
                    "success": False,
                    "message": f"{player} tiene el rango «{current}», que no está en tu lista de rangos. Dale uno de la lista.",
                }
            index = ids.index(current) + (1 if direction == "up" else -1)
            if not 0 <= index < len(ids):
                where = "el más alto" if direction == "up" else "el más bajo"
                return {"success": False, "message": f"{player} ya tiene {where} de tus rangos ({names[current]})."}
            target = ids[index]
        try:
            await server_manager.send_command(f"/lp user {player} parent set {target}")
        except Exception as error:  # noqa: BLE001
            return {"success": False, "message": f"Error al ejecutar: {error}"}
        return {"success": True, "message": f"{player} ahora tiene el rango {names.get(target, target)}."}

    def _is_enabled(self) -> bool:
        return self.get_configuration().enabled

    async def get_editor_url(self) -> LuckPermsEditorResponse:
        if not self._is_enabled():
            return LuckPermsEditorResponse(success=False, message="LuckPerms no está habilitado para esta instalación.")
        if not server_manager.is_running:
            return LuckPermsEditorResponse(
                success=False,
                message="El servidor de Minecraft debe estar encendido para generar el enlace del editor web de LuckPerms.",
            )

        async with self._lock:
            sent_at = datetime.now(UTC).isoformat()
            try:
                # Ask LuckPerms for a web editor session.
                await server_manager.send_command("/lp editor")
            except Exception as e:
                return LuckPermsEditorResponse(
                    success=False,
                    message=f"No se pudo enviar el comando a la consola: {e}",
                )

            # Wait up to 8 seconds for the URL to show up in the log buffer
            url_pattern = re.compile(r"(https://luckperms\.net/editor/[a-zA-Z0-9]+)")
            deadline = asyncio.get_running_loop().time() + 8.0

            while asyncio.get_running_loop().time() < deadline:
                history = server_manager.history
                # Check the last 25 lines
                for entry in reversed(history[-25:]):
                    msg = entry.get("message", "")
                    # Ignore older lines and player chat: anyone in game could
                    # post their own editor link to hijack the admin's session.
                    if str(entry.get("timestamp", "")) < sent_at or _CHAT_LINE.search(msg):
                        continue
                    match = url_pattern.search(msg)
                    if match:
                        editor_url = match.group(1)
                        return LuckPermsEditorResponse(
                            success=True,
                            editor_url=editor_url,
                            message="Enlace generado con éxito. Hacé clic para abrir el editor web de LuckPerms.",
                        )
                await asyncio.sleep(0.3)

            return LuckPermsEditorResponse(
                success=False,
                message="Se envió /lp editor pero no se detectó el enlace en la consola. Podés revisar la pestaña 'Consola en vivo'.",
            )

    async def execute_command(self, cmd: str) -> dict[str, Any]:
        if not self._is_enabled():
            return {"success": False, "message": "LuckPerms no está habilitado para esta instalación."}
        cleaned = cmd.strip()
        if not cleaned.startswith("/lp") and not cleaned.startswith("lp"):
            cleaned = f"/lp {cleaned.lstrip('/')}"
        else:
            if not cleaned.startswith("/"):
                cleaned = f"/{cleaned}"

        if not server_manager.is_running:
            return {
                "success": False,
                "message": "El servidor está apagado. Iniciá el servidor para ejecutar comandos de LuckPerms.",
            }

        try:
            await server_manager.send_command(cleaned)
            return {
                "success": True,
                "command": cleaned,
                "message": f"Comando '{cleaned}' enviado a la consola.",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error al ejecutar: {e}",
            }

    @property
    def _state_file(self) -> Path:
        from app.core.config import settings
        base = settings.panel_directory or Path(".")
        return base / ".worldedit_state.json"

    def _worldedit_is_installed(self) -> bool:
        """WorldEdit stays optional; only expose its controls when its JAR exists."""
        from app.core.config import settings

        mods_directory = settings.mods_directory
        if mods_directory is None or not mods_directory.is_dir():
            return False
        return any(
            entry.is_file() and entry.suffix.casefold() == ".jar" and "worldedit" in entry.name.casefold()
            for entry in mods_directory.iterdir()
        )

    def get_worldedit_status(self) -> dict[str, Any]:
        """Get the state of the WorldEdit hot toggle."""
        state_file = self._state_file
        installed = self._worldedit_is_installed()
        enabled = False
        last_updated = None
        method = "LuckPerms Live"
        if state_file.is_file():
            try:
                import json
                data = json.loads(state_file.read_text(encoding="utf-8"))
                enabled = bool(data.get("enabled", False))
                last_updated = data.get("last_updated")
                method = data.get("method", "LuckPerms Live")
            except Exception:
                pass
        return {
            "enabled": enabled,
            "available": installed,
            "status_label": "ACTIVADO" if enabled else "DESACTIVADO",
            "server_running": server_manager.is_running,
            "last_updated": last_updated,
            "method": method,
        }

    async def set_worldedit_status(self, enabled: bool) -> dict[str, Any]:
        """Apply the permission rule live through LuckPerms without restarting Java."""
        if not self._is_enabled():
            return {"success": False, "enabled": enabled, "message": "WorldEdit en vivo necesita habilitar LuckPerms para esta instalación.", "executed_live": False, "method": "LuckPerms desactivado"}
        if not self._worldedit_is_installed():
            return {
                "success": False,
                "enabled": False,
                "message": "WorldEdit no está instalado. No hace falta instalarlo para usar este panel.",
                "executed_live": False,
                "method": "WorldEdit no instalado",
            }
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        state_file = self._state_file
        try:
            import json
            state_file.write_text(json.dumps({
                "enabled": enabled,
                "last_updated": now_iso,
                "method": "LuckPerms Live (0.1s)",
            }, indent=2), encoding="utf-8")
        except Exception:
            pass

        if not server_manager.is_running:
            return {
                "success": True,
                "enabled": enabled,
                "status_label": "ACTIVADO" if enabled else "DESACTIVADO",
                "message": f"Estado de WorldEdit guardado como {'ACTIVADO' if enabled else 'DESACTIVADO'}. Se aplicará automáticamente cuando el servidor inicie.",
                "executed_live": False,
                "last_updated": now_iso,
                "method": "Guardado en reposo",
            }

        try:
            if enabled:
                # WorldEdit ON: Otorgar a admin / constructores
                await server_manager.send_command("/lp group admin permission set worldedit.* true")
                msg = "WorldEdit ACTIVADO en caliente: Permisos concedidos al grupo admin instantáneamente."
            else:
                # WorldEdit OFF: deny in default and in admin
                await server_manager.send_command("/lp group default permission set worldedit.* false")
                await server_manager.send_command("/lp group admin permission set worldedit.* false")
                msg = "WorldEdit DESACTIVADO en caliente: Comandos // y varita bloqueados sin reiniciar el servidor."

            return {
                "success": True,
                "enabled": enabled,
                "status_label": "ACTIVADO" if enabled else "DESACTIVADO",
                "message": msg,
                "executed_live": True,
                "last_updated": now_iso,
                "method": "LuckPerms Live (0.1s)",
            }
        except Exception as e:
            return {
                "success": False,
                "enabled": enabled,
                "message": f"Error al enviar comandos en caliente a LuckPerms: {e}",
                "executed_live": False,
                "last_updated": now_iso,
                "method": "Error",
            }


luckperms_service = LuckPermsService()
