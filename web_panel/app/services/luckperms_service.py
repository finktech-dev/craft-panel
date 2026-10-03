"""Integración con LuckPerms para generación de enlaces del editor web y comandos rápidos."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
from typing import Any

from app.schemas.luckperms import LuckPermsAvailability, LuckPermsEditorResponse, LuckPermsPanelConfig
from app.services.server_process import server_manager


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

    def get_configuration(self) -> LuckPermsAvailability:
        """Read only local configuration; LuckPerms is off until opted into."""
        if not self._config_file.is_file():
            return LuckPermsAvailability(enabled=False, message="LuckPerms es opcional. Creá web_panel/.luckperms_config.json para activarlo.")
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
        return LuckPermsAvailability(enabled=True, message="LuckPerms está configurado para esta instalación.", primary_ranks=primary_ranks, secondary_roles=secondary_roles)

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
            try:
                # Enviar comando /lp editor
                await server_manager.send_command("/lp editor")
            except Exception as e:
                return LuckPermsEditorResponse(
                    success=False,
                    message=f"No se pudo enviar el comando a la consola: {e}",
                )

            # Esperar hasta 8 segundos a que aparezca la URL en el buffer de logs
            url_pattern = re.compile(r"(https://luckperms\.net/editor/[a-zA-Z0-9]+)")
            deadline = asyncio.get_running_loop().time() + 8.0

            while asyncio.get_running_loop().time() < deadline:
                history = server_manager.history
                # Revisar las últimas 25 líneas
                for entry in reversed(history[-25:]):
                    msg = entry.get("message", "")
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
        """Obtiene el estado del Hot-Toggle de WorldEdit."""
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
        """Aplica la regla de permisos en caliente con LuckPerms sin reiniciar Java."""
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
                # WorldEdit OFF: Bloquear en default y en admin
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
