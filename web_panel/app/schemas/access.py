"""Contratos declarativos para las capacidades del panel.

No representan usuarios persistidos ni cambian la sesión actual. Sirven como
base estable para que la UI y futuros adaptadores hablen de permisos por
capacidad, en vez de asumir rutas, sistemas operativos o un único servidor.
"""

from typing import Literal

from pydantic import BaseModel, Field


class PanelCapability(BaseModel):
    """Una acción o área que una interfaz puede mostrar al anfitrión."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$")
    label: str
    description: str
    risk: Literal["read", "operate", "destructive"]


class PanelAccessProfile(BaseModel):
    """Perfil efectivo de la sesión administrativa actual.

    Por ahora el panel conserva exactamente su modelo de una única sesión de
    administrador. ``role`` no se almacena ni se usa para autorizar acciones:
    la respuesta permite que clientes nuevos preparen una UI basada en
    capacidades sin introducir cuentas, secretos o migraciones.
    """

    role: Literal["owner"] = "owner"
    capabilities: tuple[PanelCapability, ...]
    authorization_model: Literal["single_admin_session"] = "single_admin_session"

