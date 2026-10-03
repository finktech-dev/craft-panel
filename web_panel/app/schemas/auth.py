"""Contratos de autenticación y configuración TOTP."""

from pydantic import BaseModel, Field


class TOTPSetupResponse(BaseModel):
    qr_code_base64: str
    message: str


class TOTPVerifyRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class TwoFactorStatus(BaseModel):
    enabled: bool
