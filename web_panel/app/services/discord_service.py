"""Servicio ampliado de Discord: webhooks, alertas en tiempo real y eventos."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

import httpx

from app.core.config import Settings, settings
from app.schemas.backup import BackupItem
from app.schemas.crash import CrashReportSummary
from app.schemas.discord import DiscordConfig

logger = logging.getLogger(__name__)
_DISCORD_MAX_FIELD_LENGTH: Final = 1024


class DiscordService:
    """Cliente de webhook tolerante a fallos para alertas operativas y eventos del juego."""

    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings
        self._cached_config: DiscordConfig | None = None

    @property
    def _config_file(self) -> Path | None:
        if self._settings.panel_directory:
            return self._settings.panel_directory / ".discord_config.json"
        return None

    def get_config(self) -> DiscordConfig:
        """Carga la configuración persistente desde .discord_config.json."""
        if self._cached_config is not None:
            return self._cached_config

        target = self._config_file
        if target and target.is_file():
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
                self._cached_config = DiscordConfig(**data)
                return self._cached_config
            except Exception as error:
                logger.warning("Error al leer .discord_config.json: %s", error)

        self._cached_config = DiscordConfig(webhook_url=self._settings.discord_webhook_url or "")
        return self._cached_config

    def _display_value(self, configured: str, setting_name: str, fallback: str = "") -> str:
        """Resolve presentation data without baking a particular host into alerts."""
        return configured.strip() or str(getattr(self._settings, setting_name, "") or "").strip() or fallback

    def _server_name(self, cfg: DiscordConfig) -> str:
        return self._display_value(cfg.server_name, "discord_server_name", "Servidor Minecraft")

    def _software_label(self, cfg: DiscordConfig) -> str:
        configured = self._display_value(cfg.server_software_label, "discord_server_software_label")
        if configured:
            return configured
        return f"Minecraft {self._settings.minecraft_version}"

    def _world_name(self, cfg: DiscordConfig) -> str:
        return self._display_value(cfg.world_name, "discord_world_name", "No configurado")

    def _avatar_url(self, cfg: DiscordConfig, player_name: str) -> str | None:
        template = self._display_value(cfg.player_avatar_url_template, "discord_player_avatar_url_template")
        if not template:
            return None
        try:
            return template.format(player_name=quote(player_name, safe=""))
        except (KeyError, ValueError):
            logger.warning("La plantilla de avatar de Discord debe incluir solo {player_name}.")
            return None

    def _format_msg(self, template: str | None, default: str, **kwargs: Any) -> str:
        raw = template.strip() if template and template.strip() else default
        try:
            return raw.format(**kwargs)
        except Exception:
            return raw

    def save_config(self, new_config: DiscordConfig) -> DiscordConfig:
        """Guarda la configuración persistente en .discord_config.json."""
        target = self._config_file
        if target:
            try:
                target.write_text(new_config.model_dump_json(indent=2), encoding="utf-8")
            except Exception as error:
                logger.error("No se pudo guardar .discord_config.json: %s", error)
                raise RuntimeError("No se pudo guardar la configuración de Discord en disco.") from error

        self._cached_config = new_config
        return self._cached_config

    def _resolve_url(self, *, for_events: bool = False, override_url: str | None = None) -> str | None:
        if override_url and override_url.strip():
            return override_url.strip()

        cfg = self.get_config()
        if for_events and cfg.events_webhook_url and cfg.events_webhook_url.strip():
            return cfg.events_webhook_url.strip()

        if cfg.webhook_url and cfg.webhook_url.strip():
            return cfg.webhook_url.strip()

        return self._settings.discord_webhook_url

    async def _send_embed(
        self,
        *,
        title: str,
        description: str,
        color: int,
        fields: Sequence[tuple[str, str]] = (),
        content: str | None = None,
        thumbnail_url: str | None = None,
        for_events: bool = False,
        override_url: str | None = None,
    ) -> tuple[bool, str]:
        webhook_url = self._resolve_url(for_events=for_events, override_url=override_url)
        if not webhook_url:
            return False, "No hay ninguna URL de Webhook de Discord configurada."

        if not webhook_url.startswith("https://discord.com/api/webhooks/") and not webhook_url.startswith("https://discordapp.com/api/webhooks/"):
            return False, "La URL del webhook debe comenzar con https://discord.com/api/webhooks/"

        embed_obj: dict[str, Any] = {
            "title": title,
            "description": description[:4096],
            "color": color,
            "fields": [
                {"name": name[:256], "value": val[:_DISCORD_MAX_FIELD_LENGTH], "inline": False}
                for name, val in fields
            ],
            "footer": {"text": self._server_name(self.get_config())},
        }

        if thumbnail_url:
            embed_obj["thumbnail"] = {"url": thumbnail_url}

        payload: dict[str, Any] = {
            "embeds": [embed_obj],
            "allowed_mentions": {
                "parse": ["roles", "users", "everyone"]
            }
        }
        if content:
            payload["content"] = content[:2000]

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.post(webhook_url, json=payload)
                if resp.status_code in {200, 204}:
                    return True, "Alerta enviada correctamente a Discord."
                return False, f"Discord respondió con error HTTP {resp.status_code}: {resp.text[:200]}"
        except httpx.HTTPError as error:
            logger.warning("Error al enviar webhook a Discord: %s", error)
            return False, f"Error de conexión al enviar webhook: {error}"

    async def send_test(
        self,
        webhook_url: str | None = None,
        test_type: str = "status",
        mention_role: str = "",
    ) -> tuple[bool, str]:
        """Envía una alerta de prueba inmediata para validar la URL del webhook."""
        cfg = self.get_config()
        if test_type == "events":
            player_name = self._display_value(cfg.test_player_name, "discord_test_player_name", "Jugador de prueba")
            return await self._send_embed(
                override_url=webhook_url,
                for_events=True,
                title=f"💀 [Prueba de Feed] {player_name} fue volado en pedazos por un Creeper",
                description="¡El canal de muertes, conexiones y logros está funcionando correctamente!",
                color=0x992D22,
                thumbnail_url=self._avatar_url(cfg, player_name),
                fields=(
                    ("Tipo de Alerta", "Feed en Vivo de Jugadores (Muertes / Logros / Conexiones)"),
                    ("Avatar 3D", "Cada aviso mostrará la cara real de la skin del jugador"),
                ),
            )
        elif test_type == "mention":
            raw_mention = (mention_role or "").strip()
            if not raw_mention:
                mention = "@everyone"
            elif raw_mention.isdigit():
                mention = f"<@&{raw_mention}>"
            elif raw_mention.startswith("<@") and not raw_mention.startswith("<@&") and not raw_mention.startswith("<@#"):
                clean_id = "".join(c for c in raw_mention if c.isdigit())
                mention = f"<@&{clean_id}>" if clean_id else raw_mention
            else:
                mention = raw_mention

            return await self._send_embed(
                override_url=webhook_url,
                content=mention,
                title="📢 [Prueba de Mención] ¡Aviso de Servidor en Línea!",
                description=f"Esta es una prueba de la mención que se enviará automáticamente cuando el servidor pase a estado ONLINE.\n\nMención: {mention}",
                color=0x5865F2,
                fields=(
                    ("Mención probada", f"`{mention}`"),
                    ("Verificación", "Si recibiste la notificación o ping en Discord, el rol está configurado correctamente."),
                ),
            )
        else:
            return await self._send_embed(
                override_url=webhook_url,
                title="🟢 [Prueba de Estado] Webhook Principal Conectado",
                description="¡El Webhook de Estado y Alertas del servidor está funcionando correctamente!",
                color=0x2ECC71,
                fields=(
                    ("Panel Web", "Centro de control conectado"),
                    ("Servidor", self._software_label(cfg)),
                ),
            )

    async def send_server_starting(self) -> bool:
        cfg = self.get_config()
        if not cfg.notify_server_lifecycle:
            return False

        title = self._format_msg(
            cfg.msg_server_starting_title,
            "🟡 Iniciando Servidor de Minecraft...",
            server_name=self._server_name(cfg),
            world_name=self._world_name(cfg),
        )
        description = self._format_msg(
            cfg.msg_server_starting_desc,
            "El servidor se está encendiendo y cargando los mods. Avisaremos apenas los puertos estén abiertos y se pueda entrar.",
            server_name=self._server_name(cfg),
            world_name=self._world_name(cfg),
        )

        success, _ = await self._send_embed(
            title=title,
            description=description,
            color=0xF1C40F,
            fields=(
                ("Estado", "⏳ Cargando mods, chunks y dimensiones..."),
                ("Servidor", self._software_label(cfg)),
                ("Mundo Activo", self._world_name(cfg)),
            ),
        )
        return success

    async def send_server_started(self, public_address: str | None = None, elapsed_seconds: float | None = None) -> bool:
        cfg = self.get_config()
        if not cfg.notify_server_lifecycle:
            return False

        addr = public_address or self._settings.server_public_address or "IP en el panel"
        raw_mention = (cfg.mention_role or "").strip()
        mention = None
        if raw_mention:
            if raw_mention.isdigit():
                mention = f"<@&{raw_mention}>"
            elif raw_mention.startswith("<@") and not raw_mention.startswith("<@&") and not raw_mention.startswith("<@#"):
                clean_id = "".join(c for c in raw_mention if c.isdigit())
                mention = f"<@&{clean_id}>" if clean_id else raw_mention
            else:
                mention = raw_mention

        fields_list: list[tuple[str, str]] = [
            ("Dirección para conectarse", f"```{addr}```"),
            ("Servidor", self._software_label(cfg)),
            ("Mundo Activo", self._world_name(cfg)),
        ]
        if elapsed_seconds is not None:
            fields_list.append(("Tiempo de Arranque", f"Listo en {elapsed_seconds:.1f} segundos"))

        title = self._format_msg(
            cfg.msg_server_started_title,
            "🟢 ¡Servidor Listo para Jugar!",
            server_name=self._server_name(cfg),
            world_name=self._world_name(cfg),
            addr=addr,
        )
        description = self._format_msg(
            cfg.msg_server_started_desc,
            "¡El servidor de Minecraft ya terminó de cargar y los puertos están abiertos! ¡Ya se puede entrar!",
            server_name=self._server_name(cfg),
            world_name=self._world_name(cfg),
            addr=addr,
        )

        success, _ = await self._send_embed(
            title=title,
            description=description,
            color=0x2ECC71,
            content=mention,
            fields=tuple(fields_list),
        )
        return success

    async def send_server_stopped(self) -> bool:
        cfg = self.get_config()
        if not cfg.notify_server_lifecycle:
            return False

        title = self._format_msg(
            cfg.msg_server_stopped_title,
            "🔴 Servidor Detenido",
            server_name=self._server_name(cfg),
            world_name=self._world_name(cfg),
        )
        description = self._format_msg(
            cfg.msg_server_stopped_desc,
            "El servidor de Minecraft se ha apagado ordenadamente. Todos los mundos y progresos fueron guardados en el disco.",
            server_name=self._server_name(cfg),
            world_name=self._world_name(cfg),
        )

        success, _ = await self._send_embed(
            title=title,
            description=description,
            color=0xE74C3C,
        )
        return success

    async def send_crash(self, report: CrashReportSummary | None) -> bool:
        cfg = self.get_config()
        if not cfg.notify_crashes:
            return False

        fields: list[tuple[str, str]] = []
        if report is not None:
            fields.append(("Causa", report.cause))
            fields.append(("Mod sospechoso", report.suspected_mod or "No identificado"))
            fields.append(("Sugerencia", report.suggestion))

        success, _ = await self._send_embed(
            title="⚠️ Caída Inesperada del Servidor (Crash)",
            description="El proceso del servidor finalizó de forma anómala. El panel analizó el reporte de choque:",
            color=0xF1C40F,
            fields=fields,
        )
        return success

    async def send_backup_created(self, backup: BackupItem) -> bool:
        cfg = self.get_config()
        if not cfg.notify_backups:
            return False

        success, _ = await self._send_embed(
            title="💾 Copia de Seguridad Creada",
            description=f"Se completó exitosamente la copia de seguridad del mundo `{backup.filename}`.",
            color=0x3498DB,
            fields=(
                ("Archivo", backup.filename),
                ("Tamaño", f"{backup.size_mb:.2f} MB"),
            ),
        )
        return success

    async def send_player_join(self, player_name: str) -> bool:
        cfg = self.get_config()
        if not cfg.notify_player_join_leave:
            return False

        avatar_url = self._avatar_url(cfg, player_name)
        title = self._format_msg(
            cfg.msg_player_join_title,
            "👋 {player_name} entró al servidor",
            player_name=player_name,
            server_name=self._server_name(cfg),
            world_name=self._world_name(cfg),
        )
        description = self._format_msg(
            cfg.msg_player_join_desc,
            "**{player_name}** se unió a la partida.",
            player_name=player_name,
            server_name=self._server_name(cfg),
            world_name=self._world_name(cfg),
        )

        success, _ = await self._send_embed(
            for_events=True,
            title=title,
            description=description,
            color=0x2ECC71,
            thumbnail_url=avatar_url,
        )
        return success

    async def send_player_leave(self, player_name: str) -> bool:
        cfg = self.get_config()
        if not cfg.notify_player_join_leave:
            return False

        avatar_url = self._avatar_url(cfg, player_name)
        title = self._format_msg(
            cfg.msg_player_leave_title,
            "🚪 {player_name} salió del servidor",
            player_name=player_name,
            server_name=self._server_name(cfg),
            world_name=self._world_name(cfg),
        )
        description = self._format_msg(
            cfg.msg_player_leave_desc,
            "**{player_name}** abandonó la partida.",
            player_name=player_name,
            server_name=self._server_name(cfg),
            world_name=self._world_name(cfg),
        )

        success, _ = await self._send_embed(
            for_events=True,
            title=title,
            description=description,
            color=0x95A5A6,
            thumbnail_url=avatar_url,
        )
        return success

    async def send_player_death(self, player_name: str, death_message: str) -> bool:
        cfg = self.get_config()
        if not cfg.notify_player_deaths:
            return False

        avatar_url = self._avatar_url(cfg, player_name)
        title = self._format_msg(
            cfg.msg_player_death_title,
            "💀 Baja en el Servidor",
            player_name=player_name,
            death_message=death_message,
            server_name=self._server_name(cfg),
        )
        description = self._format_msg(
            cfg.msg_player_death_desc,
            "**{death_message}**",
            player_name=player_name,
            death_message=death_message,
            server_name=self._server_name(cfg),
        )

        success, _ = await self._send_embed(
            for_events=True,
            title=title,
            description=description,
            color=0x992D22,
            thumbnail_url=avatar_url,
        )
        return success

    async def send_advancement(self, player_name: str, advancement_title: str, adv_kind: str = "logro") -> bool:
        cfg = self.get_config()
        if not cfg.notify_advancements:
            return False

        avatar_url = self._avatar_url(cfg, player_name)
        title = self._format_msg(
            cfg.msg_advancement_title,
            "🏆 ¡{player_name} completó un {adv_kind}!",
            player_name=player_name,
            advancement_title=advancement_title,
            adv_kind=adv_kind,
            server_name=self._server_name(cfg),
        )
        description = self._format_msg(
            cfg.msg_advancement_desc,
            "**{player_name}** ha desbloqueado: **[{advancement_title}]**",
            player_name=player_name,
            advancement_title=advancement_title,
            adv_kind=adv_kind,
            server_name=self._server_name(cfg),
        )

        success, _ = await self._send_embed(
            for_events=True,
            title=title,
            description=description,
            color=0xF1C40F,
            thumbnail_url=avatar_url,
        )
        return success


discord_service = DiscordService()
