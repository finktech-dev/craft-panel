"""Switch the server between premium (online-mode) and no-premium without losing progress.

Minecraft stores each player's data under their UUID, and that UUID is different in
online mode (the real Mojang account) and offline mode (a deterministic offline UUID).
When the owner flips the mode, this service moves every known player's files from the
old UUID to the new one so nobody is treated as a brand-new player.

Known limitations (not guaranteed):
- Only the standard per-player files are moved: playerdata/<uuid>.dat (+ .dat_old),
  advancements/<uuid>.json and stats/<uuid>.json, in every world. Some mods keep data
  under a player's UUID somewhere else (their own files, scoreboard/teams, LuckPerms,
  region claims, etc.); that data is NOT migrated, so those mods may still see the player
  as new.
- Going to premium needs the internet, to ask Mojang each real account's UUID; a player
  whose account cannot be resolved is reported as not migrated.
- If a player already has a save under the target UUID (they played in both modes), their
  files are left untouched rather than overwritten, and they are reported as a collision.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import Settings, settings
from app.services.progress import ProgressCallback, StepPlan, report
from app.services.runtime_guard import ServerActiveError, require_server_stopped
from app.services.server_process import MinecraftServerManager, server_manager
from app.services.server_properties_service import ServerPropertiesService
from app.services.whitelist_service import WhitelistService, WhitelistServiceError, offline_uuid

# Per-player files Minecraft keeps under a UUID inside each world folder.
_PLAYER_FILES: tuple[tuple[str, str], ...] = (
    ("playerdata", ".dat"),
    ("playerdata", ".dat_old"),
    ("advancements", ".json"),
    ("stats", ".json"),
)

# Steps announced through the progress callback (keys stay distinct from BACKUP_STEPS).
ACCOUNT_MODE_STEPS: StepPlan = (
    ("migrate", "Moviendo el progreso de los jugadores"),
    ("apply", "Guardando el modo del servidor"),
)


class AccountModeError(RuntimeError):
    status_code = 409


@dataclass
class MigrationReport:
    to_online: bool
    migrated: list[str] = field(default_factory=list)      # players whose files were moved
    collisions: list[str] = field(default_factory=list)    # players that already had a save in the new mode
    undetermined: list[str] = field(default_factory=list)   # players whose new UUID could not be found
    files_moved: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "to_online": self.to_online,
            "migrated": self.migrated,
            "collisions": self.collisions,
            "undetermined": self.undetermined,
            "files_moved": self.files_moved,
        }


class AccountModeService:
    def __init__(
        self,
        configured_settings: Settings = settings,
        manager: MinecraftServerManager = server_manager,
    ) -> None:
        self._settings = configured_settings
        self._manager = manager
        self._whitelist = WhitelistService(configured_settings, manager)
        self._properties = ServerPropertiesService(configured_settings, manager)

    @property
    def _server_dir(self) -> Path:
        assert self._settings.server_directory is not None
        return self._settings.server_directory

    def current_online_mode(self) -> bool:
        return self._properties.read_properties().get("online-mode", "true").lower() == "true"

    async def change(
        self, *, online_mode: bool, migrate: bool, progress: ProgressCallback | None = None
    ) -> dict[str, object]:
        """Write the new online-mode and, when asked, move players' progress to their new UUID."""
        try:
            require_server_stopped(self._manager, "change the account mode")
        except ServerActiveError as error:
            raise AccountModeError(str(error)) from error

        current = self.current_online_mode()
        migration = MigrationReport(to_online=online_mode)
        if migrate and current != online_mode:
            report(progress, "migrate", "Moviendo el progreso de los jugadores.")
            migration = await self._migrate(to_online=online_mode, current_online=current)

        report(progress, "apply", "Guardando el modo del servidor.")
        await self._properties.update_properties({"online-mode": "true" if online_mode else "false"})
        await self._resync_whitelist(online_mode)
        return {"online_mode": online_mode, "migration": migration.as_dict()}

    async def _migrate(self, *, to_online: bool, current_online: bool) -> MigrationReport:
        report = MigrationReport(to_online=to_online)
        names = await asyncio.to_thread(self._known_player_names)
        world_dirs = await asyncio.to_thread(self._world_dirs)
        for name in names:
            old_uuid, new_uuid = await self._uuid_pair(name, to_online=to_online, current_online=current_online)
            if not old_uuid or not new_uuid or old_uuid.lower() == new_uuid.lower():
                report.undetermined.append(name)
                continue
            outcome, moved = await asyncio.to_thread(self._move_player, old_uuid, new_uuid, world_dirs)
            report.files_moved += moved
            if outcome == "collision":
                report.collisions.append(name)
            elif moved:
                report.migrated.append(name)
        return report

    async def _uuid_pair(self, name: str, *, to_online: bool, current_online: bool) -> tuple[str | None, str | None]:
        if to_online:
            return offline_uuid(name), await self._online_uuid(name, current_online)
        return await self._online_uuid(name, current_online), offline_uuid(name)

    async def _online_uuid(self, name: str, current_online: bool) -> str | None:
        """The real Mojang UUID; falls back to usercache only when it currently holds online UUIDs."""
        try:
            player_uuid, _exact = await self._whitelist._mojang_uuid(name)  # noqa: SLF001 - reuse resolution
            return player_uuid
        except ValueError:
            return None  # no Mojang account with this name
        except WhitelistServiceError:
            if current_online:
                return await asyncio.to_thread(self._whitelist._cached_uuid, name)  # noqa: SLF001
            return None

    def _move_player(self, old_uuid: str, new_uuid: str, world_dirs: list[Path]) -> tuple[str, int]:
        moved = 0
        collided = False
        for world in world_dirs:
            if (world / "playerdata" / f"{new_uuid}.dat").exists():
                collided = True  # the player already has a save in the new mode; never overwrite it
                continue
            for folder, suffix in _PLAYER_FILES:
                source = world / folder / f"{old_uuid}{suffix}"
                target = world / folder / f"{new_uuid}{suffix}"
                if source.is_file() and not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), str(target))
                    moved += 1
        if collided and moved == 0:
            return "collision", 0
        return "migrated", moved

    def _world_dirs(self) -> list[Path]:
        root = self._server_dir
        if not root.is_dir():
            return []
        active = self._properties.read_properties().get("level-name", "world")
        worlds = []
        for entry in root.iterdir():
            if entry.is_dir() and ((entry / "level.dat").is_file() or entry.name == active):
                worlds.append(entry)
        return worlds

    def _known_player_names(self) -> list[str]:
        """Every player the panel knows: whitelist, usercache and ops, de-duplicated by name."""
        names: dict[str, str] = {}
        for filename, key in (("whitelist.json", "name"), ("usercache.json", "name"), ("ops.json", "name")):
            path = self._server_dir / filename
            if not path.is_file():
                continue
            try:
                entries = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict):
                    name = str(entry.get(key, "")).strip()
                    if name:
                        names.setdefault(name.lower(), name)
        return list(names.values())

    async def _resync_whitelist(self, online_mode: bool) -> None:
        """Rewrite whitelist.json UUIDs for the new mode so entries keep matching the players."""
        path = self._server_dir / "whitelist.json"
        if not path.is_file():
            return
        try:
            entries = await asyncio.to_thread(lambda: json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(entries, list):
            return
        changed = False
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            name = str(entry["name"])
            new_uuid = offline_uuid(name) if not online_mode else await self._online_uuid(name, current_online=False)
            if new_uuid and entry.get("uuid") != new_uuid:
                entry["uuid"] = new_uuid
                changed = True
        if changed:
            await asyncio.to_thread(self._write_json, path, entries)

    @staticmethod
    def _write_json(path: Path, data: object) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)


account_mode_service = AccountModeService()
