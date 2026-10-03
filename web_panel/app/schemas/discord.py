"""Esquemas Pydantic para la configuración y alertas de Discord."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DiscordConfig(BaseModel):
    """Configuración persistente para las alertas y webhooks de Discord."""

    webhook_url: str = Field(default="", description="URL del webhook principal de Discord")
    events_webhook_url: str = Field(
        default="",
        description="URL opcional para feed de jugadores, muertes y logros (si está vacía se usa la principal)",
    )
    notify_server_lifecycle: bool = Field(default=True, description="Notificar encendido, apagado y reinicios")
    notify_crashes: bool = Field(default=True, description="Notificar caídas y análisis de crashes")
    notify_backups: bool = Field(default=True, description="Notificar backups del mundo creados")
    notify_player_join_leave: bool = Field(default=True, description="Notificar conexiones y desconexiones")
    notify_player_deaths: bool = Field(default=True, description="Notificar muertes de jugadores en el juego")
    notify_advancements: bool = Field(default=True, description="Notificar logros y desafíos completados")
    mention_role: str = Field(
        default="",
        description="Rol o mención opcional al encender el servidor (ej: @everyone o <@&123456789>)",
    )
    server_name: str = Field(
        default="",
        max_length=80,
        description="Nombre visible del servidor en alertas; vacío usa MINECRAFT_DISCORD_SERVER_NAME",
    )
    server_software_label: str = Field(
        default="",
        max_length=120,
        description="Etiqueta de software/versiones para alertas; vacío usa la configuración del panel",
    )
    world_name: str = Field(
        default="",
        max_length=80,
        description="Nombre del mundo mostrado en alertas; vacío usa MINECRAFT_DISCORD_WORLD_NAME",
    )
    test_player_name: str = Field(
        default="",
        max_length=64,
        description="Nombre ficticio usado únicamente al probar el feed de eventos",
    )
    player_avatar_url_template: str = Field(
        default="",
        max_length=500,
        description="URL de avatar con {player_name}; vacío desactiva avatares o usa la configuración del panel",
    )


class DiscordTestRequest(BaseModel):
    """Solicitud para enviar un mensaje de prueba al webhook."""

    webhook_url: str = Field(default="", description="URL de webhook a probar (opcional, si vacía usa la guardada)")
    test_type: str = Field(default="status", description="Tipo de prueba: 'status', 'events' o 'mention'")
    mention_role: str = Field(default="", description="Mención o rol a probar cuando test_type es 'mention'")


class DiscordActionResponse(BaseModel):
    """Respuesta a acciones de Discord."""

    success: bool
    message: str
