"""Typed, centralized configuration for the web panel."""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, PrivateAttr, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Values configurable through ``MINECRAFT_*`` environment variables.

    Derived paths stay inside the project root so an accidental setting cannot
    point at directories unrelated to the server.
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
    defaultconfigs_directory: Path | None = None
    panel_directory: Path | None = None
    static_directory: Path | None = None
    client_pack_directory: Path | None = None
    client_config_directory: Path | None = None
    client_pack_filename: str = "modpack.zip"
    client_pack_extra_directories: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="Directorios adicionales del servidor a empaquetar en el cliente (ej. resourcepacks, datapacks)"
    )
    backups_directory: Path | None = None
    tools_directory: Path | None = None
    totp_secret_path: Path | None = None
    playit_secret_path: Path | None = None
    local_secrets_path: Path | None = None

    panel_host: str = "127.0.0.1"
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="Extra domain names allowed in the Host header (e.g. a reverse proxy domain or *.example.com)",
    )
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
    # Empty means the server's name, or "Servidor de Minecraft".
    banner_title: str = ""
    banner_subtitle: str = ""
    server_public_address: str | None = None
    # Optional overrides; by default the panel reads both from the installed server.
    minecraft_version: str | None = None
    neoforge_version: str | None = None
    allocated_ram_gb: int = Field(default=5, ge=1, le=64)
    playit_enabled: bool = True
    graceful_stop_timeout_seconds: int = Field(default=30, ge=1, le=300)
    log_buffer_size: int = Field(default=500, ge=1, le=5_000)
    auto_backup_interval_hours: int = Field(default=6, ge=1, le=168)
    backup_retention_count: int = Field(default=4, ge=1, le=100)
    backup_max_disk_gb: int = Field(default=15, ge=1, le=10_000)
    backup_min_free_disk_gb: int = Field(default=10, ge=0, le=10_000)
    backup_integrity_check_interval_hours: int = Field(default=168, ge=24, le=8760)

    _admin_pin_generated_this_start: bool = PrivateAttr(default=False)
    _admin_password_hash: str | None = PrivateAttr(default=None)
    _initial_admin_password: str | None = PrivateAttr(default=None)

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

    @field_validator("client_pack_extra_directories", "allowed_hosts", mode="before")
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
        """Keep persistent secrets out of Git, with no weak default PIN.

        The administrator password is only ever stored as a scrypt hash
        (``admin_password_hash``). A password generated on first run is kept in
        plain text in memory only, so the login page can show it once to a
        browser on this PC; it is forgotten after the first successful login.
        If the panel restarts before anyone signed in with a generated
        password, a new one is generated (nobody can be using the old one yet).
        A plain ``admin_pin`` left by an older version is hashed and removed
        from the file on startup. ``MINECRAFT_ADMIN_PIN`` is hashed in memory
        and never written to disk.
        """
        from app.core.passwords import hash_password, is_password_hash

        assert self.local_secrets_path is not None
        stored: dict[str, object] = {}
        if self.local_secrets_path.is_file():
            try:
                raw = json.loads(self.local_secrets_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    stored = {key: value for key, value in raw.items() if isinstance(value, (str, bool))}
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("No se pudo leer web_panel/.panel_secrets.json.") from error

        changed = False
        legacy_pin = stored.pop("admin_pin", None)
        if legacy_pin is not None:
            changed = True  # never leave a plain-text password on disk
            if isinstance(legacy_pin, str) and len(legacy_pin) >= 12:
                # A plain value only comes from an older version or a manual
                # edit; either way it is the password the owner expects.
                stored["admin_password_hash"] = hash_password(legacy_pin)
                stored.pop("admin_password_unclaimed", None)

        if self.admin_pin is not None:
            # Environment override: hash it and drop the plain value.
            self._admin_password_hash = hash_password(self.admin_pin.get_secret_value())
            self.admin_pin = None
        else:
            saved_hash = stored.get("admin_password_hash")
            if is_password_hash(saved_hash) and stored.get("admin_password_unclaimed") is not True:
                self._admin_password_hash = str(saved_hash)
            else:
                generated = secrets.token_urlsafe(18)
                self._initial_admin_password = generated
                self._admin_password_hash = hash_password(generated)
                self._admin_pin_generated_this_start = True
                stored["admin_password_hash"] = self._admin_password_hash
                stored["admin_password_unclaimed"] = True
                changed = True

        if self.session_secret is None:
            saved_session_secret = stored.get("session_secret")
            if isinstance(saved_session_secret, str) and len(saved_session_secret) >= 32:
                self.session_secret = SecretStr(saved_session_secret)
            else:
                self.session_secret = SecretStr(secrets.token_urlsafe(48))
                stored["session_secret"] = self.session_secret.get_secret_value()
                changed = True

        if changed:
            self._write_local_secrets(stored)

    def _read_local_secrets(self) -> dict[str, object]:
        assert self.local_secrets_path is not None
        try:
            raw = json.loads(self.local_secrets_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def mark_admin_password_claimed(self) -> None:
        """Forget the first-run password after the owner signed in with it."""
        self._initial_admin_password = None
        if not self._admin_pin_generated_this_start:
            return
        self._admin_pin_generated_this_start = False
        assert self.local_secrets_path is not None
        stored = self._read_local_secrets()
        if stored.pop("admin_password_unclaimed", None) is not None:
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
    def _write_local_secrets(self, values: dict[str, object]) -> None:
        from app.core.path_safety import write_private_text

        assert self.local_secrets_path is not None
        write_private_text(self.local_secrets_path, json.dumps(values, indent=2))

    @property
    def effective_cookie_secure(self) -> bool:
        return self.cookie_secure if self.cookie_secure is not None else self.panel_mode == "internet"

    @property
    def admin_pin_generated_this_start(self) -> bool:
        return self._admin_pin_generated_this_start

    @property
    def admin_password_hash(self) -> str | None:
        return self._admin_password_hash

    @property
    def initial_admin_password(self) -> str | None:
        """Generated first-run password, in memory only until the first login."""
        return self._initial_admin_password

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

    def _server_file_settings(self):  # noqa: ANN202 - avoids importing services at module load
        from app.services.server_settings_file import read_server_settings

        return read_server_settings(self)

    @property
    def default_server_start_script_name(self) -> str:
        return "run.bat" if sys.platform == "win32" else "run.sh"

    @property
    def server_start_script(self) -> Path:
        """The ``inicio`` script from craftpanel.txt, or the native generated launch script."""
        assert self.server_directory is not None
        configured = self._server_file_settings().start_script
        return self.server_directory / (configured or self.default_server_start_script_name)

    @property
    def server_java_executable(self) -> Path | None:
        """The ``java`` chosen in craftpanel.txt, when it is set and still exists."""
        configured = self._server_file_settings().java
        if configured and Path(configured).is_file():
            return Path(configured)
        return None

    @property
    def server_java_bin_directory(self) -> Path | None:
        """Folder put first on PATH for the server: craftpanel.txt's Java, else tools/java."""
        if (chosen := self.server_java_executable) is not None:
            return chosen.parent
        if self.local_java_executable_path.is_file():
            return self.local_java_executable_path.parent
        return None

    # craftpanel.txt values that replace a panel setting when they are written in the file.

    @property
    def effective_backups_directory(self) -> Path:
        """``backup_location`` from craftpanel.txt, else the panel's backups folder."""
        assert self.backups_directory is not None
        location = self._server_file_settings().value("backup_location")
        return Path(location) if location else self.backups_directory

    @property
    def effective_backup_retention_count(self) -> int:
        return self._server_file_settings().value("backup_keep") or self.backup_retention_count

    @property
    def effective_backup_max_disk_gb(self) -> int:
        return self._server_file_settings().value("backup_max_size") or self.backup_max_disk_gb

    @property
    def effective_ram_gb(self) -> int:
        """``memory`` from craftpanel.txt, else the RAM chosen in the panel."""
        return self._server_file_settings().value("memory") or self.allocated_ram_gb

    @property
    def effective_server_name(self) -> str | None:
        return self._server_file_settings().value("server_name") or None

    @property
    def effective_public_address(self) -> str | None:
        """``public_address`` from craftpanel.txt, else the configured address."""
        return self._server_file_settings().value("public_address") or self.server_public_address

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
        return self.tools_directory / ("cloudflared.exe" if os.name == "nt" else "cloudflared")

    @property
    def server_start_command(self) -> tuple[str, ...]:
        """Run the launch script without relying on a Windows-only shell.

        The name is either the built-in default or an ``inicio`` value that
        craftpanel.txt validation limited to letters, digits, ``.``, ``_`` and
        ``-``, so it cannot carry cmd.exe metacharacters.
        """
        script = self.server_start_script.name
        if self.server_start_script.suffix.casefold() in {".bat", ".cmd"}:
            # An explicit .\ path works even when NoDefaultCurrentDirectoryInExePath stops
            # cmd.exe from looking for commands in the current folder.
            return ("cmd.exe", "/d", "/s", "/c", f"call .\\{script} nogui")
        return ("sh", f"./{script}", "nogui")
settings = Settings()
