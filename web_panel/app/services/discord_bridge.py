"""Find a mod that links the game chat with Discord.

The panel's own Discord notices need no mod (it reads the console and posts to a webhook).
A chat bridge, a bot with commands or linked accounts do need one, so the panel only
detects it and helps install it; it never reads or stores the bot's token.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings, settings
from app.schemas.discord import DiscordBridgeStatus, DiscordBridgeSuggestion
from app.services.mod_service import ModService, mod_service


@dataclass(frozen=True, slots=True)
class BridgeMod:
    name: str
    mod_ids: frozenset[str]
    project_id: str
    slug: str
    # Folder or file name the mod uses inside config/.
    config_hint: str


KNOWN_BRIDGES: tuple[BridgeMod, ...] = (
    BridgeMod("Simple Discord Link", frozenset({"sdlink"}), "Sh0YauEf", "sdlink", "simple-discord-link"),
    BridgeMod("Mc2Discord", frozenset({"mc2discord"}), "Cfbcv7uF", "mc2discord", "mc2discord"),
    BridgeMod("Discord Integration", frozenset({"dcintegration"}), "rbJ7eS5V", "dcintegration", "Discord-Integration"),
)
RECOMMENDED = KNOWN_BRIDGES[0]


class DiscordBridgeService:
    def __init__(self, configured_settings: Settings = settings, mods: ModService = mod_service) -> None:
        self._settings = configured_settings
        self._mods = mods

    async def status(self) -> DiscordBridgeStatus:
        suggestion = DiscordBridgeSuggestion(
            name=RECOMMENDED.name,
            project_id=RECOMMENDED.project_id,
            modrinth_url=f"https://modrinth.com/mod/{RECOMMENDED.slug}",
        )
        for mod in await self._mods.list_mods():
            bridge = self._match(mod.mod_id, mod.filename)
            if bridge is None:
                continue
            return DiscordBridgeStatus(
                installed=True,
                enabled=mod.is_enabled,
                name=bridge.name,
                filename=mod.filename,
                modrinth_url=f"https://modrinth.com/mod/{bridge.slug}",
                config_file=self._config_file(bridge),
                suggestion=suggestion,
            )
        return DiscordBridgeStatus(installed=False, enabled=False, suggestion=suggestion)

    @staticmethod
    def _match(mod_id: str | None, filename: str) -> BridgeMod | None:
        lowered_id = (mod_id or "").lower()
        compact_name = filename.lower().replace("-", "").replace("_", "")
        for bridge in KNOWN_BRIDGES:
            if lowered_id in bridge.mod_ids:
                return bridge
            # Jars without readable metadata: fall back to the file name.
            if compact_name.startswith(bridge.name.lower().replace(" ", "")):
                return bridge
        return None

    def _config_file(self, bridge: BridgeMod) -> str | None:
        """The mod's main settings file, relative to config/, once the server created it."""
        root = self._settings.config_directory
        if root is None or not root.is_dir():
            return None
        hint = bridge.config_hint.lower()
        candidates: list[Path] = []
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".toml", ".json", ".json5", ".cfg", ".conf", ".properties"}:
                relative = path.relative_to(root).as_posix()
                if hint in relative.lower():
                    candidates.append(path)
        if not candidates:
            return None
        # Prefer the file named like the mod over embed templates or backups.
        candidates.sort(key=lambda path: (hint not in path.stem.lower(), len(path.relative_to(root).parts), path.name))
        return candidates[0].relative_to(root).as_posix()


discord_bridge_service = DiscordBridgeService()
