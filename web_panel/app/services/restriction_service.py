"""Servicio agnóstico de restricciones para Minecraft NeoForge 1.21.1.

Maneja:
1. Bloqueo de ítems y armas (compatible con Item Obliterator y comodines como !mod:.*).
2. Supresión de spawns de mobs mediante datapack nativo NeoForge 1.21.1 (neoforge:remove_spawns)
   en las carpetas de datapacks del servidor y moonlight-global-datapacks contra Overworld, Nether y End.
3. Desactivación de profesiones de aldeanos y mesas de trabajo vía datapack tag removal
   en data/minecraft/tags/point_of_interest_type/acquirable_job_site.json y pointblank-common.toml.
4. Descubrimiento dinámico 100% tipográfico (sin descargar texturas/PNGs).
5. Recarga en caliente automática mediante /reload cuando el servidor está encendido.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
import zipfile
from pathlib import Path
from typing import Any

import tomlkit

from app.core.config import Settings, settings
from app.services.server_process import MinecraftServerManager, server_manager
from app.services.server_properties_service import server_properties_service

logger = logging.getLogger(__name__)

# Catálogo predeterminado de profesiones y mesas de trabajo
KNOWN_VILLAGERS = [
    {
        "id": "pointblank:arms_dealer",
        "name": "Traficante de Armas (Point Blank)",
        "mod": "pointblank",
        "workstation": "Mesa de Trabajo de Armas",
        "description": "Vende armas de fuego, accesorios y municiones en aldeas.",
    },
    {
        "id": "minecraft:weaponsmith",
        "name": "Herrero de Armas",
        "mod": "minecraft",
        "workstation": "Afiladora (Grindstone)",
        "description": "Vende espadas, hachas de combate y campanas.",
    },
    {
        "id": "minecraft:armorer",
        "name": "Armero",
        "mod": "minecraft",
        "workstation": "Alto Horno (Blast Furnace)",
        "description": "Vende armaduras de hierro, cota de malla y diamante.",
    },
    {
        "id": "minecraft:toolsmith",
        "name": "Herrero de Herramientas",
        "mod": "minecraft",
        "workstation": "Mesa de Herrería (Smithing Table)",
        "description": "Vende picos, palas y azadas de diamante y hierro.",
    },
    {
        "id": "minecraft:fletcher",
        "name": "Flechero",
        "mod": "minecraft",
        "workstation": "Mesa de Flechería (Fletching Table)",
        "description": "Vende arcos, ballestas y flechas con efectos.",
    },
    {
        "id": "minecraft:cleric",
        "name": "Clérigo",
        "mod": "minecraft",
        "workstation": "Soporte para Pociones (Brewing Stand)",
        "description": "Vende perlas de Ender, redstone y pociones.",
    },
    {
        "id": "minecraft:librarian",
        "name": "Bibliotecario",
        "mod": "minecraft",
        "workstation": "Atril (Lectern)",
        "description": "Vende libros encantados (ej. Mending, Fortuna) y brújulas.",
    },
    {
        "id": "minecraft:farmer",
        "name": "Agricultor",
        "mod": "minecraft",
        "workstation": "Compostador (Composter)",
        "description": "Vende panes, tartas, manzanas doradas y esmeraldas.",
    },
    {
        "id": "minecraft:fisherman",
        "name": "Pescador",
        "mod": "minecraft",
        "workstation": "Barril (Barrel)",
        "description": "Vende cañas de pescar encantadas y pescado cocido.",
    },
    {
        "id": "minecraft:butcher",
        "name": "Carnicero",
        "mod": "minecraft",
        "workstation": "Ahumador (Smoker)",
        "description": "Vende carnes cocidas y guiso de conejo.",
    },
    {
        "id": "minecraft:leatherworker",
        "name": "Peletero",
        "mod": "minecraft",
        "workstation": "Caldero (Cauldron)",
        "description": "Vende armaduras de cuero y monturas.",
    },
    {
        "id": "minecraft:mason",
        "name": "Albañil",
        "mod": "minecraft",
        "workstation": "Cortapiedras (Stonecutter)",
        "description": "Vende terracota vidriada, ladrillos y cuarzo pulido.",
    },
    {
        "id": "minecraft:shepherd",
        "name": "Pastor",
        "mod": "minecraft",
        "workstation": "Telar (Loom)",
        "description": "Vende lanas teñidas, tijeras y estandartes.",
    },
    {
        "id": "minecraft:cartographer",
        "name": "Cartógrafo",
        "mod": "minecraft",
        "workstation": "Mesa de Cartografía (Cartography Table)",
        "description": "Vende mapas exploradores de monumentos oceánicos y mansiones.",
    },
]

# Vanilla mobs principales para selección inmediata
VANILLA_MOBS = [
    {"id": "minecraft:creeper", "name": "Creeper", "mod": "minecraft"},
    {"id": "minecraft:zombie", "name": "Zombi", "mod": "minecraft"},
    {"id": "minecraft:skeleton", "name": "Esqueleto", "mod": "minecraft"},
    {"id": "minecraft:spider", "name": "Araña", "mod": "minecraft"},
    {"id": "minecraft:enderman", "name": "Enderman", "mod": "minecraft"},
    {"id": "minecraft:witch", "name": "Bruja", "mod": "minecraft"},
    {"id": "minecraft:slime", "name": "Slime", "mod": "minecraft"},
    {"id": "minecraft:phantom", "name": "Fantasma (Phantom)", "mod": "minecraft"},
    {"id": "minecraft:warden", "name": "Warden (Guardián)", "mod": "minecraft"},
    {"id": "minecraft:wither", "name": "Wither", "mod": "minecraft"},
    {"id": "minecraft:ender_dragon", "name": "Dragón del Fin (Ender Dragon)", "mod": "minecraft"},
    {"id": "minecraft:pillager", "name": "Saqueador (Pillager)", "mod": "minecraft"},
    {"id": "minecraft:ravager", "name": "Devastador (Ravager)", "mod": "minecraft"},
    {"id": "minecraft:evoker", "name": "Evocador", "mod": "minecraft"},
    {"id": "minecraft:vindicator", "name": "Vindicador", "mod": "minecraft"},
    {"id": "minecraft:blaze", "name": "Blaze", "mod": "minecraft"},
    {"id": "minecraft:ghast", "name": "Ghast", "mod": "minecraft"},
    {"id": "minecraft:magma_cube", "name": "Cubo de Magma", "mod": "minecraft"},
    {"id": "minecraft:wither_skeleton", "name": "Esqueleto Wither", "mod": "minecraft"},
    {"id": "minecraft:hoglin", "name": "Hoglin", "mod": "minecraft"},
    {"id": "minecraft:piglin_brute", "name": "Piglin Bruto", "mod": "minecraft"},
    {"id": "minecraft:breeze", "name": "Breeze", "mod": "minecraft"},
    {"id": "minecraft:bogged", "name": "Bogged (Esqueleto Pantanoso)", "mod": "minecraft"},
    {"id": "minecraft:drowned", "name": "Ahogado (Drowned)", "mod": "minecraft"},
    {"id": "minecraft:husk", "name": "Husk (Zombi Momia)", "mod": "minecraft"},
    {"id": "minecraft:stray", "name": "Stray (Esqueleto Polar)", "mod": "minecraft"},
]


class RestrictionService:
    def __init__(
        self,
        configured_settings: Settings = settings,
        manager: MinecraftServerManager = server_manager,
    ) -> None:
        self._settings = configured_settings
        self._manager = manager
        self._lock = asyncio.Lock()
        self._catalog_cache: dict[str, Any] | None = None
        self._catalog_mtime: float = 0.0

    @property
    def server_dir(self) -> Path:
        assert self._settings.server_directory
        return self._settings.server_directory

    @property
    def config_dir(self) -> Path:
        assert self._settings.config_directory
        return self._settings.config_directory

    @property
    def mods_dir(self) -> Path:
        assert self._settings.mods_directory
        return self._settings.mods_directory

    @property
    def item_blacklist_file(self) -> Path:
        return self.config_dir / "panel-item-blacklist.json"

    @property
    def item_obliterator_file(self) -> Path:
        return self.config_dir / "item_obliterator.json5"

    @property
    def mob_blacklist_file(self) -> Path:
        return self.config_dir / "panel-mob-blacklist.json"

    @property
    def villager_blacklist_file(self) -> Path:
        return self.config_dir / "panel-villager-blacklist.json"

    @property
    def pointblank_config_file(self) -> Path:
        return self.config_dir / "pointblank-common.toml"

    def _get_datapack_targets(self) -> list[Path]:
        """Devuelve las carpetas del datapack panel_restrictions en el servidor y moonlight."""
        targets: list[Path] = []
        # Obtener nombre del mundo activo
        props = server_properties_service.read_properties()
        level_name = props.get("level-name", "world")
        world_datapacks = self.server_dir / level_name / "datapacks" / "panel_restrictions"
        targets.append(world_datapacks)

        # Datapack global de Moonlight
        global_datapacks = self.server_dir / "moonlight-global-datapacks" / "panel_restrictions"
        targets.append(global_datapacks)

        return targets

    # ==========================================
    # 1. ÍTEMS Y ARMAS
    # ==========================================
    def get_restricted_items(self) -> list[str]:
        if self.item_blacklist_file.is_file():
            try:
                data = json.loads(self.item_blacklist_file.read_text(encoding="utf-8"))
                items = data.get("blacklisted_items", [])
                if items:
                    return sorted(set(items))
            except Exception:
                pass
        if self.item_obliterator_file.is_file():
            try:
                data = json.loads(self.item_obliterator_file.read_text(encoding="utf-8"))
                items = data.get("blacklisted_items", [])
                if items:
                    return sorted(set(items))
            except Exception:
                pass
        return []

    async def add_restricted_item(self, item_id: str) -> list[str]:
        cleaned = item_id.strip()
        if not cleaned:
            return self.get_restricted_items()
        async with self._lock:
            items = set(self.get_restricted_items())
            items.add(cleaned)
            self._save_items(items)
            await self._hot_reload()
            return sorted(items)

    async def remove_restricted_item(self, item_id: str) -> list[str]:
        cleaned = item_id.strip()
        async with self._lock:
            items = set(self.get_restricted_items())
            items.discard(cleaned)
            self._save_items(items)
            await self._hot_reload()
            return sorted(items)

    def _save_items(self, items: set[str]) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "blacklisted_items": sorted(items),
            "hide_from_creative": True,
            "hide_from_jei": True,
            "remove_recipes": True,
            "prevent_use": True,
        }
        self._atomic_json_write(self.item_blacklist_file, data)

        oblit_data = {
            "configVersion": 0,
            "blacklisted_items": sorted(items),
            "blacklisted_nbt": [],
            "only_disable_interactions": [],
            "only_disable_attacks": [],
            "only_disable_recipes": [],
            "use_hashmap_optimizations": False,
        }
        if self.item_obliterator_file.is_file():
            try:
                existing = json.loads(self.item_obliterator_file.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    existing["blacklisted_items"] = sorted(items)
                    oblit_data = existing
            except Exception:
                pass
        self._atomic_json_write(self.item_obliterator_file, oblit_data)

    # ==========================================
    # 2. SPAWNS DE MOBS (BIOME MODIFIERS)
    # ==========================================
    def get_restricted_mobs(self) -> list[str]:
        if self.mob_blacklist_file.is_file():
            try:
                data = json.loads(self.mob_blacklist_file.read_text(encoding="utf-8"))
                mobs = data.get("restricted_mobs", [])
                if mobs:
                    return sorted(set(mobs))
            except Exception:
                pass
        return []

    async def add_restricted_mob(self, entity_id: str) -> list[str]:
        cleaned = entity_id.strip()
        if not cleaned:
            return self.get_restricted_mobs()
        async with self._lock:
            mobs = set(self.get_restricted_mobs())
            mobs.add(cleaned)
            self._save_mobs(mobs)
            self._sync_datapacks(mobs=sorted(mobs), villagers=self.get_restricted_villagers())
            await self._hot_reload()
            return sorted(mobs)

    async def remove_restricted_mob(self, entity_id: str) -> list[str]:
        cleaned = entity_id.strip()
        async with self._lock:
            mobs = set(self.get_restricted_mobs())
            mobs.discard(cleaned)
            self._save_mobs(mobs)
            self._sync_datapacks(mobs=sorted(mobs), villagers=self.get_restricted_villagers())
            await self._hot_reload()
            return sorted(mobs)

    def _save_mobs(self, mobs: set[str]) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        data = {"restricted_mobs": sorted(mobs)}
        self._atomic_json_write(self.mob_blacklist_file, data)

    # ==========================================
    # 3. ALDEANOS Y PROFESIONES (POI REMOVAL)
    # ==========================================
    def get_restricted_villagers(self) -> list[str]:
        if self.villager_blacklist_file.is_file():
            try:
                data = json.loads(self.villager_blacklist_file.read_text(encoding="utf-8"))
                professions = data.get("disabled_professions", [])
                if professions:
                    return sorted(set(professions))
            except Exception:
                pass
        return []

    async def set_villager_restricted(self, profession_id: str, disabled: bool) -> list[str]:
        cleaned = profession_id.strip()
        if not cleaned:
            return self.get_restricted_villagers()
        async with self._lock:
            professions = set(self.get_restricted_villagers())
            if disabled:
                professions.add(cleaned)
            else:
                professions.discard(cleaned)

            self._save_villagers(professions)
            self._sync_pointblank_config(professions)
            self._sync_datapacks(mobs=self.get_restricted_mobs(), villagers=sorted(professions))
            await self._hot_reload()
            return sorted(professions)

    def _save_villagers(self, professions: set[str]) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        data = {"disabled_professions": sorted(professions)}
        self._atomic_json_write(self.villager_blacklist_file, data)

    def _sync_pointblank_config(self, disabled_professions: set[str]) -> None:
        """Ajusta armsDealerHouse = 0 en pointblank-common.toml si pointblank:arms_dealer está bloqueado."""
        p = self.pointblank_config_file
        if not p.is_file():
            return
        try:
            raw = p.read_text(encoding="utf-8")
            doc = tomlkit.parse(raw)
            is_blocked = "pointblank:arms_dealer" in disabled_professions
            target_value = 0 if is_blocked else 10
            if doc.get("armsDealerHouse") != target_value:
                doc["armsDealerHouse"] = target_value
                tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex}.tmp")
                tmp.write_text(tomlkit.dumps(doc), encoding="utf-8")
                os.replace(tmp, p)
        except Exception as err:
            logger.warning("No se pudo actualizar pointblank-common.toml: %s", err)

    # ==========================================
    # 4. GENERADOR DE DATAPACK NATIVO NEOFORGE
    # ==========================================
    def _sync_datapacks(self, mobs: list[str], villagers: list[str]) -> None:
        """Escribe la estructura del datapack panel_restrictions en ambos directorios objetivo."""
        for root in self._get_datapack_targets():
            try:
                root.mkdir(parents=True, exist_ok=True)

                # pack.mcmeta (Formato 48 para 1.21.1)
                mcmeta = {
                    "pack": {
                        "pack_format": 48,
                        "description": "Panel Restrictions - Native NeoForge Mob & Villager Block",
                    }
                }
                (root / "pack.mcmeta").write_text(json.dumps(mcmeta, indent=2), encoding="utf-8")

                # Directorio de Biome Modifiers (Mob Spawns)
                biome_mod_dir = root / "data" / "panel_restrictions" / "neoforge" / "biome_modifier"
                biome_mod_dir.mkdir(parents=True, exist_ok=True)

                dimensions = [
                    ("overworld", "#minecraft:is_overworld"),
                    ("nether", "#minecraft:is_nether"),
                    ("end", "#minecraft:is_end"),
                ]

                if mobs:
                    for dim_name, biome_tag in dimensions:
                        mod_file = biome_mod_dir / f"remove_spawns_{dim_name}.json"
                        mod_content = {
                            "type": "neoforge:remove_spawns",
                            "biomes": biome_tag,
                            "entity_types": mobs,
                        }
                        mod_file.write_text(json.dumps(mod_content, indent=2), encoding="utf-8")
                else:
                    # Si no hay mobs restringidos, remover modificadores
                    for dim_name, _ in dimensions:
                        mod_file = biome_mod_dir / f"remove_spawns_{dim_name}.json"
                        if mod_file.is_file():
                            mod_file.unlink(missing_ok=True)

                # Directorio de Tags para Villagers (Workstations / POI removal)
                poi_dir = root / "data" / "minecraft" / "tags" / "point_of_interest_type"
                poi_dir.mkdir(parents=True, exist_ok=True)
                job_site_file = poi_dir / "acquirable_job_site.json"

                poi_tag_content = {
                    "replace": False,
                    "values": [],
                    "remove": villagers,
                }
                job_site_file.write_text(json.dumps(poi_tag_content, indent=2), encoding="utf-8")

            except Exception as err:
                logger.error("Error al sincronizar datapack en %s: %s", root, err)

    # ==========================================
    # 5. CATÁLOGO DINÁMICO Y DISCOVERY
    # ==========================================
    async def discover_catalog(self) -> dict[str, Any]:
        """Escanea JARs y registries de manera no bloqueante con caché en memoria."""
        return await asyncio.to_thread(self._scan_catalog_sync)

    def _scan_catalog_sync(self) -> dict[str, Any]:
        if not self.mods_dir.is_dir():
            return {
                "items": [],
                "mobs": list(VANILLA_MOBS),
                "mobs_by_mod": {"minecraft": VANILLA_MOBS},
                "villagers": KNOWN_VILLAGERS,
                "items_by_mod": {},
                "mods": ["minecraft"],
            }

        mtime = self.mods_dir.stat().st_mtime
        if self._catalog_cache is not None and mtime == self._catalog_mtime:
            return self._catalog_cache

        mobs_by_mod: dict[str, list[dict[str, str]]] = {"minecraft": list(VANILLA_MOBS)}
        items_by_mod: dict[str, list[dict[str, str]]] = {}
        seen_entities: set[str] = {m["id"] for m in VANILLA_MOBS}
        seen_items: set[str] = set()

        for jar in sorted(self.mods_dir.glob("*.jar")):
            try:
                with zipfile.ZipFile(jar) as z:
                    namelist = z.namelist()
                    # Buscar archivos de traducción en_us o es_es
                    lang_files = [n for n in namelist if n.endswith("/lang/en_us.json") or n.endswith("/lang/es_es.json")]
                    for lf in lang_files:
                        try:
                            data = json.loads(z.read(lf).decode("utf-8", errors="ignore"))
                            for k, v in data.items():
                                val_str = str(v).strip()
                                if not val_str or "%s" in val_str:
                                    continue

                                # Entidades / Mobs
                                if k.startswith("entity."):
                                    parts = k.split(".")
                                    if len(parts) >= 3:
                                        mod_id = parts[1]
                                        ent_id = parts[2]
                                        if ent_id not in ("description", "subtitle", "subtitles") and not ent_id.endswith("_subtitles"):
                                            full_id = f"{mod_id}:{ent_id}"
                                            if full_id not in seen_entities:
                                                seen_entities.add(full_id)
                                                mobs_by_mod.setdefault(mod_id, []).append(
                                                    {"id": full_id, "name": val_str, "mod": mod_id}
                                                )

                                # Ítems y Bloques
                                elif k.startswith("item.") or k.startswith("block."):
                                    parts = k.split(".")
                                    if len(parts) >= 3:
                                        mod_id = parts[1]
                                        it_id = parts[2]
                                        full_id = f"{mod_id}:{it_id}"
                                        if full_id not in seen_items:
                                            seen_items.add(full_id)
                                            items_by_mod.setdefault(mod_id, []).append(
                                                {"id": full_id, "name": val_str, "mod": mod_id}
                                            )
                        except Exception:
                            pass

                    # Fallback de modelos / items para mods sin lang o con ítems directos
                    for n in namelist:
                        if n.endswith(".json") and ("assets/" in n or "data/" in n):
                            parts = n.split("/")
                            mid = None
                            if len(parts) >= 5 and parts[0] == "assets" and parts[2] in {"models", "items"} and parts[3] == "item":
                                mid = parts[1]
                            elif len(parts) == 4 and parts[0] in {"data", "assets"} and parts[2] == "items":
                                mid = parts[1]
                            if mid:
                                iid = f"{mid}:{Path(n).stem}"
                                if iid not in seen_items:
                                    seen_items.add(iid)
                                    name_clean = Path(n).stem.replace("_", " ").title()
                                    items_by_mod.setdefault(mid, []).append(
                                        {"id": iid, "name": name_clean, "mod": mid}
                                    )

            except Exception:
                pass

        all_mods = sorted(set(mobs_by_mod.keys()) | set(items_by_mod.keys()))

        all_items: list[dict[str, str]] = []
        for m_items in items_by_mod.values():
            all_items.extend(m_items)

        all_mobs: list[dict[str, str]] = []
        for m_mobs in mobs_by_mod.values():
            all_mobs.extend(m_mobs)

        result = {
            "items": all_items,
            "mobs": all_mobs,
            "mobs_by_mod": mobs_by_mod,
            "villagers": KNOWN_VILLAGERS,
            "items_by_mod": items_by_mod,
            "mods": all_mods,
        }
        self._catalog_cache = result
        self._catalog_mtime = mtime
        return result

    # ==========================================
    # 6. RESUMEN COMPLETO Y RECARGA
    # ==========================================
    def get_summary(self) -> dict[str, Any]:
        """Retorna el estado actual de todas las restricciones aplicadas."""
        items = self.get_restricted_items()
        mobs = self.get_restricted_mobs()
        villagers = self.get_restricted_villagers()

        known_villagers_with_state = []
        for v in KNOWN_VILLAGERS:
            v_copy = dict(v)
            v_copy["disabled"] = v["id"] in villagers
            known_villagers_with_state.append(v_copy)

        return {
            "items": items,
            "blocked_items": items,
            "mobs": mobs,
            "blocked_mobs": mobs,
            "villagers": known_villagers_with_state,
            "disabled_villagers": villagers,
            "items_count": len(items),
            "mobs_count": len(mobs),
            "villagers_count": len(villagers),
            "server_running": self._manager.is_running,
            "message": (
                f"{len(items)} ítems restringidos, {len(mobs)} spawns de mobs suprimidos y {len(villagers)} profesiones bloqueadas."
            ),
        }

    async def _hot_reload(self) -> None:
        """Si el servidor está encendido, ejecuta /reload automáticamente."""
        if self._manager.is_running:
            try:
                await self._manager.send_command("/reload")
                logger.info("Comando /reload enviado a la consola de Minecraft.")
            except Exception as err:
                logger.warning("No se pudo ejecutar /reload en consola: %s", err)

    @staticmethod
    def _atomic_json_write(path: Path, data: dict[str, Any]) -> None:
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)


restriction_service = RestrictionService()
