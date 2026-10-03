"""Contratos de la API para estado, métricas y acciones del servidor."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ServerMetrics(BaseModel):
    cpu_percent: float = Field(ge=0)
    ram_used_mb: float = Field(ge=0)
    ram_total_mb: float = Field(ge=0)
    ram_percent: float = Field(ge=0, le=100)
    uptime_seconds: int = Field(ge=0)
    is_running: bool
    state: str
    dev_mode: bool = False


class ServerActionResponse(BaseModel):
    success: bool
    message: str
    state: str


class PublicServerStatus(BaseModel):
    """Estado mínimo y seguro para una web pública."""

    online: bool
    state: str
    address: str | None = None


class LoginRequest(BaseModel):
    pin: str = Field(min_length=1, max_length=128)
    totp_code: str | None = Field(default=None, pattern=r"^\d{6}$")


class LoginResponse(BaseModel):
    success: bool
    message: str
