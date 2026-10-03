from __future__ import annotations
import asyncio, json, os, uuid
from pathlib import Path
from app.core.config import Settings, settings
from app.schemas.universal import BlacklistState
from app.services.server_process import MinecraftServerManager, server_manager

class BlacklistService:
    def __init__(self, configured_settings: Settings = settings, manager: MinecraftServerManager = server_manager):
        self.s = configured_settings
        self.m = manager
        self.lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        assert self.s.config_directory
        return self.s.config_directory / 'panel-item-blacklist.json'

    @property
    def oblit_path(self) -> Path:
        assert self.s.config_directory
        return self.s.config_directory / 'item_obliterator.json5'

    def _adapter(self) -> bool:
        assert self.s.mods_directory
        return any('item-oblit' in x.name.lower() for x in self.s.mods_directory.glob('*.jar'))

    async def status(self) -> BlacklistState:
        items = await asyncio.to_thread(self._items)
        available = self._adapter()
        return BlacklistState(
            items=items,
            enforcement_available=available,
            message='Protección de ítems activa.' if available else 'Tu lista ya está guardada. Para aplicar el bloqueo real dentro del juego falta agregar el complemento de protección; el panel lo detectará automáticamente.'
        )

    def _items(self) -> list[str]:
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                items = data.get('blacklisted_items', [])
                if items:
                    return sorted(set(items))
            except (OSError, json.JSONDecodeError):
                pass
        if self.oblit_path.is_file():
            try:
                data = json.loads(self.oblit_path.read_text(encoding='utf-8'))
                items = data.get('blacklisted_items', [])
                if items:
                    return sorted(set(items))
            except (OSError, json.JSONDecodeError):
                pass
        return []

    async def add(self, item: str) -> BlacklistState:
        return await self._change(item, True)

    async def remove(self, item: str) -> BlacklistState:
        return await self._change(item, False)

    async def _change(self, item: str, add: bool) -> BlacklistState:
        async with self.lock:
            items = set(await asyncio.to_thread(self._items))
            if add:
                items.add(item)
            else:
                items.discard(item)

            data = {
                'blacklisted_items': sorted(items),
                'hide_from_creative': True,
                'hide_from_jei': True,
                'remove_recipes': True,
                'prevent_use': True,
            }
            await asyncio.to_thread(self.path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(self._write, data)
            await asyncio.to_thread(self._sync_obliterator, items)

            if self.m.is_running:
                await self.m.send_command('/reload')

        return await self.status()

    def _write(self, data: dict) -> None:
        tmp = self.path.with_name(f'.{self.path.name}.{uuid.uuid4().hex}.tmp')
        tmp.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
        os.replace(tmp, self.path)

    def _sync_obliterator(self, items: set[str]) -> None:
        target = self.oblit_path
        data = {
            'configVersion': 0,
            'blacklisted_items': sorted(items),
            'blacklisted_nbt': [],
            'only_disable_interactions': [],
            'only_disable_attacks': [],
            'only_disable_recipes': [],
            'use_hashmap_optimizations': False,
        }
        if target.is_file():
            try:
                existing = json.loads(target.read_text(encoding='utf-8'))
                if isinstance(existing, dict):
                    existing['blacklisted_items'] = sorted(items)
                    data = existing
            except Exception:
                pass
        tmp = target.with_name(f'.{target.name}.{uuid.uuid4().hex}.tmp')
        tmp.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
        os.replace(tmp, target)

blacklist_service = BlacklistService()
