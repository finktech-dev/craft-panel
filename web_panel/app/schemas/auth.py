"""Authentication and TOTP setup contracts."""

from pydantic import BaseModel, Field


class TOTPCurrentCodeRequest(BaseModel):
    """Changing an active second factor needs a code from the current app."""

    code: str | None = Field(default=None, pattern=r"^\d{6}$")


class TOTPSetupResponse(BaseModel):
    qr_code_base64: str
    manual_entry_key: str
    message: str


class TOTPVerifyRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class TwoFactorStatus(BaseModel):
    enabled: bool
