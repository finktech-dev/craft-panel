"""Catálogo local de capacidades para interfaces y adaptadores del panel."""

from __future__ import annotations

from app.schemas.access import PanelAccessProfile, PanelCapability


class AccessService:
    """Expone el perfil del dueño sin inspeccionar ni modificar el host."""

    _OWNER_CAPABILITIES: tuple[PanelCapability, ...] = (
        PanelCapability(
            id="dashboard:view",
            label="Resumen del servidor",
            description="Consultar el estado, alertas y próximos pasos.",
            risk="read",
        ),
        PanelCapability(
            id="runtime:discover",
            label="Detectar el equipo",
            description="Comprobar Java, el servidor y la protección de cuentas sin cambiarlos.",
            risk="read",
        ),
        PanelCapability(
            id="server:control",
            label="Controlar el servidor",
            description="Iniciar o detener el proceso que administra el panel.",
            risk="operate",
        ),
        PanelCapability(
            id="console:interact",
            label="Usar la consola",
            description="Ver la salida y enviar comandos al servidor administrado.",
            risk="operate",
        ),
        PanelCapability(
            id="players:manage",
            label="Gestionar jugadores",
            description="Administrar lista blanca, restricciones y rangos disponibles.",
            risk="operate",
        ),
        PanelCapability(
            id="worlds:manage",
            label="Gestionar mundos",
            description="Crear o cambiar mundos solamente cuando el servidor está detenido.",
            risk="destructive",
        ),
        PanelCapability(
            id="backups:manage",
            label="Gestionar copias",
            description="Crear, verificar y restaurar copias con las protecciones del panel.",
            risk="destructive",
        ),
        PanelCapability(
            id="connections:manage",
            label="Gestionar conexiones",
            description="Configurar túneles compatibles, como Playit.gg, sin abrir puertos del router.",
            risk="operate",
        ),
    )

    def owner_profile(self) -> PanelAccessProfile:
        """Devuelve datos estáticos; no lee cuentas, sesiones ni secretos."""
        return PanelAccessProfile(capabilities=self._OWNER_CAPABILITIES)


access_service = AccessService()
