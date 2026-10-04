"""Configuración tipada y centralizada del panel web."""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, PrivateAttr, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Valores configurables mediante variables de entorno ``MINECRAFT_*``.

    Las rutas derivadas se mantienen dentro de la raíz del proyecto para evitar
    que una configuración accidental apunte a directorios ajenos al servidor.
    """

    model_config = SettingsConfigDict(
        env_prefix="MINECRAFT_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    project_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[3])
    server_directory: Path | None = None
    server_log_file: Path | None = None
    world_directory: Path | None = None
    crash_reports_directory: Path | None = None
    mods_directory: Path | None = None
    config_directory: Path | None = None
    schematics_directory: Path | None = None
    defaultconfigs_directory: Path | None = None
    panel_directory: Path | None = None
    static_directory: Path | None = None
    client_pack_directory: Path | None = None
    client_config_directory: Path | None = None
    client_pack_filename: str = "modpack.zip"
    client_pack_extra_directories: list[str] = Field(
        default_factory=list,
        description="Directorios adicionales del servidor a empaquetar en el cliente (ej. pointblank, resourcepacks)"
    )
    backups_directory: Path | None = None
    tools_directory: Path | None = None
    totp_secret_path: Path | None = None
    playit_secret_path: Path | None = None
    local_secrets_path: Path | None = None

    panel_host: str = "127.0.0.1"
    panel_port: int = Field(default=8080, ge=1, le=65535)
    panel_mode: Literal["local", "internet"] = "local"
    admin_pin: SecretStr | None = Field(default=None, min_length=12, max_length=128)
    session_secret: SecretStr | None = None
    session_max_age_seconds: int = Field(default=28_800, ge=300, le=604_800)
    cookie_secure: bool | None = None
    discord_webhook_url: str | None = None
    discord_server_name: str = "Servidor Minecraft"
    discord_server_software_label: str = ""
    discord_world_name: str = ""
    discord_test_player_name: str = "Jugador de prueba"
    discord_player_avatar_url_template: str = "https://mc-heads.net/avatar/{player_name}/100.png"
    banner_title: str = "Minecraft server status"
    server_public_address: str | None = None
    minecraft_version: str = "1.21.1"
    neoforge_version: str = "21.1.250"
    allocated_ram_gb: int = Field(default=5, ge=1, le=64)
    playit_enabled: bool = True
    graceful_stop_timeout_seconds: int = Field(default=30, ge=1, le=300)
    log_buffer_size: int = Field(default=500, ge=1, le=5_000)
    auto_backup_interval_hours: int = Field(default=6, ge=1, le=168)
    backup_retention_count: int = Field(default=4, ge=1, le=100)
    backup_max_disk_gb: int = Field(default=15, ge=1, le=10_000)
    backup_integrity_check_interval_hours: int = Field(default=168, ge=24, le=8760)

    _admin_pin_generated_this_start: bool = PrivateAttr(default=False)

    aikar_g1gc_flags: tuple[str, ...] = (
        "-XX:+UseG1GC",
        "-XX:+ParallelRefProcEnabled",
        "-XX:MaxGCPauseMillis=200",
        "-XX:+UnlockExperimentalVMOptions",
        "-XX:+DisableExplicitGC",
        "-XX:+AlwaysPreTouch",
        "-XX:G1NewSizePercent=30",
        "-XX:G1MaxNewSizePercent=40",
        "-XX:G1HeapRegionSize=8M",
        "-XX:G1ReservePercent=20",
        "-XX:G1HeapWastePercent=5",
        "-XX:G1MixedGCCountTarget=4",
        "-XX:InitiatingHeapOccupancyPercent=15",
        "-XX:G1MixedGCLiveThresholdPercent=90",
        "-XX:G1RSetUpdatingPauseTimePercent=5",
        "-XX:SurvivorRatio=32",
        "-XX:+PerfDisableSharedMem",
        "-XX:MaxTenuringThreshold=1",
    )

    @field_validator("client_pack_extra_directories", mode="before")
    @classmethod
    def _parse_client_pack_extra_directories(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("[") and v.endswith("]"):
                with contextlib.suppress(Exception):
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
            return [part.strip() for part in v.split(",") if part.strip()]
        if isinstance(v, (list, tuple)):
            return [str(item).strip() for item in v if str(item).strip()]
        return []

    @model_validator(mode="after")
    def resolve_project_paths(self) -> "Settings":
        self.project_root = self.project_root.expanduser().resolve()
        self.server_directory = self._project_path(self.server_directory, "server")
        self.world_directory = self._server_path(self.world_directory, "world")
        self.crash_reports_directory = self._server_path(self.crash_reports_directory, "crash-reports")
        self.mods_directory = self._server_path(self.mods_directory, "mods")
        self.config_directory = self._server_path(self.config_directory, "config")
        self.schematics_directory = self._server_path(self.schematics_directory, "schematics")
        self.defaultconfigs_directory = self._server_path(self.defaultconfigs_directory, "defaultconfigs")
        self.panel_directory = self._project_path(self.panel_directory, "web_panel")
        self.static_directory = self._panel_path(self.static_directory, "static")
        self.client_pack_directory = self._project_path(self.client_pack_directory, "client_pack")
        if self.client_config_directory is not None:
            self.client_config_directory = self.client_config_directory.expanduser().resolve()
        self.backups_directory = self._project_path(self.backups_directory, "backups")
        self.tools_directory = self._project_path(self.tools_directory, "tools")
        self.totp_secret_path = self._panel_path(self.totp_secret_path, ".totp_secret")
        self.playit_secret_path = self._panel_path(self.playit_secret_path, ".playit_agent_secret")
        self.local_secrets_path = self._panel_path(self.local_secrets_path, ".panel_secrets.json")

        log_file = self.server_log_file or self.server_directory / "logs" / "latest.log"
        self.server_log_file = self._child_path(log_file, self.server_directory, "server_log_file")
        self._load_or_create_local_secrets()
        self._load_launch_settings()

        if self.panel_mode == "internet" and self.panel_host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("En modo internet, panel_host debe ser una dirección de loopback.")
        return self

    def _load_or_create_local_secrets(self) -> None:
        """Mantiene secretos persistentes, fuera de Git, sin un PIN débil por defecto."""
        assert self.local_secrets_path is not None
        stored: dict[str, str] = {}
        if self.local_secrets_path.is_file():
            try:
                raw = json.loads(self.local_secrets_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    stored = {key: value for key, value in raw.items() if isinstance(value, str)}
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("No se pudo leer web_panel/.panel_secrets.json.") from error

        changed = False
        if self.admin_pin is None:
            saved_pin = stored.get("admin_pin")
            if saved_pin and len(saved_pin) >= 12:
                self.admin_pin = SecretStr(saved_pin)
            else:
                self.admin_pin = SecretStr(secrets.token_urlsafe(18))
                self._admin_pin_generated_this_start = True
                changed = True

        if self.session_secret is None:
            saved_session_secret = stored.get("session_secret")
            if saved_session_secret and len(saved_session_secret) >= 32:
                self.session_secret = SecretStr(saved_session_secret)
            else:
                self.session_secret = SecretStr(secrets.token_urlsafe(48))
                changed = True

        if changed:
            stored.update(
                {
                    "admin_pin": self.admin_pin.get_secret_value(),
                    "session_secret": self.session_secret.get_secret_value(),
                }
            )
            self._write_local_secrets(stored)

    def _load_launch_settings(self) -> None:
        """Loads the non-secret RAM preference saved from the local panel."""
        assert self.panel_directory is not None
        target = self.panel_directory / ".launch_settings.json"
        if not target.is_file():
            return
        try:
            stored = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(stored, dict):
                return
            value = stored.get("allocated_ram_gb")
            if isinstance(value, int) and 1 <= value <= 64:
                self.allocated_ram_gb = value
            enabled = stored.get("playit_enabled")
            if isinstance(enabled, bool):
                self.playit_enabled = enabled
        except (OSError, json.JSONDecodeError):
            return
    def _write_local_secrets(self, values: dict[str, str]) -> None:
        assert self.local_secrets_path is not None
        self.local_secrets_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.local_secrets_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(values, indent=2), encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, self.local_secrets_path)

    @property
    def effective_cookie_secure(self) -> bool:
        return self.cookie_secure if self.cookie_secure is not None else self.panel_mode == "internet"

    @property
    def admin_pin_generated_this_start(self) -> bool:
        return self._admin_pin_generated_this_start

    def _project_path(self, configured_path: Path | None, default_name: str) -> Path:
        return self._child_path(
            configured_path or self.project_root / default_name,
            self.project_root,
            default_name,
        )

    def _panel_path(self, configured_path: Path | None, default_name: str) -> Path:
        assert self.panel_directory is not None
        return self._child_path(
            configured_path or self.panel_directory / default_name,
            self.panel_directory,
            default_name,
        )

    def _server_path(self, configured_path: Path | None, default_name: str) -> Path:
        assert self.server_directory is not None
        return self._child_path(
            configured_path or self.server_directory / default_name,
            self.server_directory,
            default_name,
        )

    @staticmethod
    def _child_path(path: Path, parent: Path, field_name: str) -> Path:
        resolved_path = path.expanduser().resolve()
        resolved_parent = parent.expanduser().resolve()
        if not resolved_path.is_relative_to(resolved_parent):
            raise ValueError(f"{field_name} debe estar dentro de {resolved_parent}")
        return resolved_path

    @property
    def server_start_script(self) -> Path:
        """Use the native launch script generated for this operating system."""
        assert self.server_directory is not None
        return self.server_directory / ("run.bat" if sys.platform == "win32" else "run.sh")
    @property
    def local_java_executable_path(self) -> Path:
        """Optional portable Java unpacked at tools/java/bin inside this clone."""
        assert self.tools_directory is not None
        return self.tools_directory / "java" / "bin" / ("java.exe" if os.name == "nt" else "java")
    @property
    def neoforge_installer_path(self) -> Path:
        assert self.tools_directory is not None
        return self.tools_directory / "neoforge-installer.jar"

    @property
    def playit_executable_path(self) -> Path:
        assert self.tools_directory is not None
        return self.tools_directory / ("playit.exe" if os.name == "nt" else "playit")

    @property
    def cloudflared_executable_path(self) -> Path:
        assert self.tools_directory is not None
        return self.tools_directory / "cloudflared.exe"

    @property
    def server_start_command(self) -> tuple[str, ...]:
        """Run the native generated script without relying on a Windows-only shell."""
        if self.server_start_script.suffix.casefold() == ".bat":
            return ("cmd.exe", "/d", "/s", "/c", "call run.bat nogui")
        return ("sh", "./run.sh", "nogui")
settings = Settings()
