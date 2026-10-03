"""Generación de esquemas NBT compactos para Create y Schematicannon."""

from __future__ import annotations

import asyncio
import math
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import nbtlib
import numpy as np
from nbtlib import ByteArray, Compound, Int, IntArray, List, Long, String

from app.core.config import Settings, settings
from app.schemas.schematic import SchematicItem

_KIBIBYTE = 1024
_DATA_VERSION_1_21_1 = 3953


class SchematicServiceError(RuntimeError):
    status_code = 400


class SchematicNotFoundError(SchematicServiceError):
    status_code = 404


class _SchematicBuilder:
    """Paleta de bloques y datos varint del formato Sponge/Create schematic v2."""

    def __init__(self, width: int, height: int, length: int) -> None:
        self.width = width
        self.height = height
        self.length = length
        self._blocks = np.zeros((height, length, width), dtype=np.uint16)
        self._palette: dict[str, int] = {"minecraft:air": 0}

    def block(self, x: int, y: int, z: int, state: str) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height and 0 <= z < self.length):
            return
        palette_id = self._palette.setdefault(state, len(self._palette))
        self._blocks[y, z, x] = palette_id

    def fill(self, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, state: str) -> None:
        palette_id = self._palette.setdefault(state, len(self._palette))
        lower_x, upper_x = max(0, min(x1, x2)), min(self.width - 1, max(x1, x2))
        lower_y, upper_y = max(0, min(y1, y2)), min(self.height - 1, max(y1, y2))
        lower_z, upper_z = max(0, min(z1, z2)), min(self.length - 1, max(z1, z2))
        if lower_x <= upper_x and lower_y <= upper_y and lower_z <= upper_z:
            self._blocks[lower_y : upper_y + 1, lower_z : upper_z + 1, lower_x : upper_x + 1] = palette_id

    def build(self, name: str) -> nbtlib.File:
        packed_data: list[int] = []
        # El orden X/Z/Y coincide con el usado por Schematicannon/Sponge Schematic.
        for palette_id in self._blocks.reshape(-1):
            packed_data.extend(_encode_varint(int(palette_id)))

        now = int(datetime.now(UTC).timestamp() * 1000)
        root = Compound(
            {
                "Version": Int(2),
                "DataVersion": Int(_DATA_VERSION_1_21_1),
                "Width": Int(self.width),
                "Height": Int(self.height),
                "Length": Int(self.length),
                "Offset": IntArray([0, 0, 0]),
                "PaletteMax": Int(len(self._palette)),
                "Palette": Compound({state: Int(value) for state, value in self._palette.items()}),
                "BlockData": ByteArray(packed_data),
                "BlockEntities": List[Compound]([]),
                "Entities": List[Compound]([]),
                "Metadata": Compound(
                    {
                        "Name": String(name),
                        "Author": String("Panel Minecraft"),
                        "RegionCount": Int(1),
                        "EnclosingSize": Compound({"x": Int(self.width), "y": Int(self.height), "z": Int(self.length)}),
                        "TotalBlocks": Int(int(np.count_nonzero(self._blocks))),
                        "TotalVolume": Int(self.width * self.height * self.length),
                        "TimeCreated": Long(now),
                        "TimeModified": Long(now),
                    }
                ),
            }
        )
        return nbtlib.File(root, gzipped=True)


def _encode_varint(value: int) -> list[int]:
    """Codifica un entero de paleta como bytes firmados del tag ByteArray."""
    encoded: list[int] = []
    while True:
        current = value & 0x7F
        value >>= 7
        if value:
            current |= 0x80
        encoded.append(current if current < 128 else current - 256)
        if not value:
            return encoded


class SchematicService:
    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings
        self._operation_lock = asyncio.Lock()

    @property
    def schematics_directory(self) -> Path:
        assert self._settings.schematics_directory is not None
        return self._settings.schematics_directory

    async def list_schematics(self) -> list[SchematicItem]:
        if not self.schematics_directory.is_dir():
            return []
        return await asyncio.to_thread(self._list_schematics_sync)

    async def generate_railway_viaduct(self, length_blocks: int = 60) -> SchematicItem:
        if not 20 <= length_blocks <= 256:
            raise SchematicServiceError("La longitud del viaducto debe estar entre 20 y 256 bloques.")
        return await self._generate("viaducto_medieval.nbt", self._build_viaduct, length_blocks)

    async def generate_train_station(self) -> SchematicItem:
        return await self._generate("estacion_central.nbt", self._build_station)

    async def _generate(self, filename: str, build_function, *args: object) -> SchematicItem:
        async with self._operation_lock:
            await asyncio.to_thread(self.schematics_directory.mkdir, parents=True, exist_ok=True)
            target = self.schematics_directory / filename
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            try:
                await asyncio.to_thread(self._save_generated_sync, temporary, build_function, *args)
                await asyncio.to_thread(os.replace, temporary, target)
            except OSError as error:
                raise SchematicServiceError(f"No se pudo guardar el esquema: {error}") from error
            finally:
                if temporary.exists():
                    await asyncio.to_thread(temporary.unlink)
        return await asyncio.to_thread(self._item_from_path, target)

    @staticmethod
    def _save_generated_sync(target: Path, build_function, *args: object) -> None:
        schematic = build_function(*args)
        schematic.save(target)

    @staticmethod
    def _build_viaduct(length_blocks: object) -> nbtlib.File:
        length = int(length_blocks)
        height = 24
        width_z = 7
        builder = _SchematicBuilder(length, height, width_z)
        deck_y = 18

        # Pilares robustos y arcos de medio punto abiertos
        pier_width = 3
        arch_span = 11
        period = pier_width + arch_span  # 14

        x = 0
        while x < length:
            p_end = min(x + pier_width, length)

            # --- PILAR (PIER) ---
            # Zapata ensanchada de pizarra profunda (y=0..2)
            builder.fill(max(0, x - 1), 0, 0, min(length - 1, p_end), 2, 6, "minecraft:deepslate_bricks")
            # Fuste macizo de pizarra profunda (y=3..13)
            builder.fill(x, 3, 1, p_end - 1, 13, 5, "minecraft:deepslate_bricks")
            # Pilastras frontales decorativas de piedra labrada (z=0 y z=6)
            builder.fill(x, 3, 0, p_end - 1, 13, 0, "minecraft:stone_bricks")
            builder.fill(x, 3, 6, p_end - 1, 13, 6, "minecraft:stone_bricks")
            # Imposta / capitel de arranque de arco en pizarra pulida (y=13)
            builder.fill(max(0, x - 1), 13, 0, min(length - 1, p_end), 13, 6, "minecraft:polished_deepslate")

            # --- ARCO HUECO ABIERTO ---
            arch_start = p_end
            arch_end = min(x + period, length)
            span_len = arch_end - arch_start

            if span_len > 0:
                r = span_len / 2.0
                for ax in range(arch_start, arch_end):
                    dx = abs((ax - arch_start) - (span_len - 1) / 2.0)
                    if dx < r:
                        curve_h = math.sqrt(max(0.0, r * r - dx * dx))
                        arch_y = 10 + int(round((curve_h / r) * 6))  # bóveda de y=10 a y=16
                    else:
                        arch_y = 10

                    # Por debajo de arch_y queda 100% AIRE ABIERTO (se ve a través de los vanos)

                    # Dovelas y rosca del arco en pizarra profunda
                    for z in range(0, 7):
                        builder.block(ax, arch_y, z, "minecraft:deepslate_bricks")
                        # Clave de bóveda esculpida en el centro
                        if int(dx) == 0 and z in (0, 6):
                            builder.block(ax, arch_y, z, "minecraft:chiseled_stone_bricks")

                    # Enjutas (muros que sostienen el tablero desde arch_y + 1 hasta deck_y - 1)
                    if arch_y + 1 <= deck_y - 1:
                        for z in (0, 6):
                            builder.fill(ax, arch_y + 1, z, ax, deck_y - 1, z, "minecraft:stone_bricks")
                        builder.fill(ax, arch_y + 1, 1, ax, deck_y - 1, 5, "minecraft:stone_bricks")

            x += period

        # 2. TABLERO VOLADO (DECK)
        # Hilera de ménsulas de baldosas de pizarra bajo el voladizo (y=17)
        builder.fill(0, deck_y - 1, 0, length - 1, deck_y - 1, 6, "minecraft:deepslate_tiles")
        # Losa base de piedra labrada (y=18)
        builder.fill(0, deck_y, 0, length - 1, deck_y, 6, "minecraft:stone_bricks")

        # 3. SUPERFICIE FERROVIARIA (y=19..21)
        # Pretiles / Parapetos de seguridad laterales (z=0 y z=6)
        builder.fill(0, deck_y + 1, 0, length - 1, deck_y + 1, 0, "minecraft:stone_bricks")
        builder.fill(0, deck_y + 1, 6, length - 1, deck_y + 1, 6, "minecraft:stone_bricks")
        builder.fill(0, deck_y + 2, 0, length - 1, deck_y + 2, 0, "minecraft:deepslate_bricks")
        builder.fill(0, deck_y + 2, 6, length - 1, deck_y + 2, 6, "minecraft:deepslate_bricks")

        # Pasarelas peatonales de inspección (z=1 y z=5)
        builder.fill(0, deck_y + 1, 1, length - 1, deck_y + 1, 1, "minecraft:polished_andesite")
        builder.fill(0, deck_y + 1, 5, length - 1, deck_y + 1, 5, "minecraft:polished_andesite")

        # Lecho de balasto de grava (z=2, 3, 4)
        builder.fill(0, deck_y + 1, 2, length - 1, deck_y + 1, 4, "minecraft:gravel")

        # Tendido de dos vías de Create (z=2 y z=4 a y=20)
        builder.fill(0, deck_y + 2, 2, length - 1, deck_y + 2, 2, "create:track[shape=straight_x]")
        builder.fill(0, deck_y + 2, 4, length - 1, deck_y + 2, 4, "create:track[shape=straight_x]")

        # Pasarela técnica con andamios de andesita (z=3 a y=20)
        builder.fill(0, deck_y + 2, 3, length - 1, deck_y + 2, 3, "create:andesite_scaffolding")

        # Faroles medievales sobre pedestales encima de cada pilar
        for lx in range(1, length, period):
            for lz in (0, 6):
                builder.block(lx, deck_y + 2, lz, "minecraft:chiseled_stone_bricks")
                builder.block(lx, deck_y + 3, lz, "minecraft:lantern")

        return builder.build("Viaducto ferroviario medieval")

    @staticmethod
    def _build_station() -> nbtlib.File:
        width, height, length = 36, 18, 25
        builder = _SchematicBuilder(width, height, length)

        # Cimientos de piedra labrada
        builder.fill(0, 0, 0, width - 1, 0, length - 1, "minecraft:stone_bricks")

        # Foso de vías hundido (z=10..14)
        builder.fill(0, 1, 10, width - 1, 1, 14, "minecraft:gravel")
        builder.fill(0, 2, 11, width - 1, 2, 11, "create:track[shape=straight_x]")
        builder.fill(0, 2, 12, width - 1, 2, 12, "minecraft:polished_andesite")
        builder.fill(0, 2, 13, width - 1, 2, 13, "create:track[shape=straight_x]")

        # Andén Norte (z=2..9) y Andén Sur (z=15..22) elevados a ras de vagón
        builder.fill(0, 1, 2, width - 1, 1, 9, "minecraft:stone_bricks")
        builder.fill(0, 2, 2, width - 1, 2, 8, "minecraft:stone_bricks")
        builder.fill(0, 2, 9, width - 1, 2, 9, "minecraft:polished_andesite")

        builder.fill(0, 1, 15, width - 1, 1, 22, "minecraft:stone_bricks")
        builder.fill(0, 2, 15, width - 1, 2, 15, "minecraft:polished_andesite")
        builder.fill(0, 2, 16, width - 1, 2, 22, "minecraft:stone_bricks")

        # Cenefas decorativas de baldosas de pizarra en el suelo de los andenes
        builder.fill(0, 2, 5, width - 1, 2, 6, "minecraft:deepslate_tiles")
        builder.fill(0, 2, 18, width - 1, 2, 19, "minecraft:deepslate_tiles")

        # Columnas de pizarra y tirantes de hierro forjado cada 6 bloques
        for x in (3, 9, 15, 21, 27, 32):
            for z in (3, 21):
                builder.block(x, 2, z, "minecraft:chiseled_stone_bricks")
                builder.fill(x, 3, z, x, 10, z, "minecraft:deepslate_bricks")
                builder.block(x, 11, z, "minecraft:polished_deepslate")
            builder.fill(x, 10, 3, x, 10, 21, "minecraft:iron_bars")

        # Faroles colgantes con cadenas sobre los andenes
        for x in (6, 12, 18, 24, 30):
            for z in (6, 18):
                builder.block(x, 9, z, "minecraft:chain")
                builder.block(x, 8, z, "minecraft:lantern")

        # Bancos de espera de roble oscuro
        for x_start in (6, 16, 26):
            builder.fill(x_start, 3, 5, x_start + 2, 3, 5, "minecraft:dark_oak_planks")
            builder.fill(x_start, 3, 19, x_start + 2, 3, 19, "minecraft:dark_oak_planks")

        # Techo abovedado con pendientes de baldosas de pizarra
        for z in range(1, 10):
            y_roof = 12 + int((z - 1) * 0.45)
            builder.fill(0, y_roof, z, width - 1, y_roof, z, "minecraft:deepslate_tiles")
        for z in range(15, 24):
            y_roof = 12 + int((23 - z) * 0.45)
            builder.fill(0, y_roof, z, width - 1, y_roof, z, "minecraft:deepslate_tiles")

        # Claraboya cenital de cristal sobre las vías
        builder.fill(0, 16, 10, width - 1, 16, 14, "minecraft:glass")
        builder.fill(0, 16, 9, width - 1, 16, 9, "minecraft:dark_oak_planks")
        builder.fill(0, 16, 15, width - 1, 16, 15, "minecraft:dark_oak_planks")

        return builder.build("Estación central medieval")

    def get_schematic_path(self, filename: str) -> Path:
        if not filename or Path(filename).name != filename or not filename.lower().endswith(".nbt"):
            raise SchematicServiceError("El nombre del esquema no es válido.")
        candidate = (self.schematics_directory / filename).resolve()
        if not candidate.is_relative_to(self.schematics_directory.resolve()):
            raise SchematicServiceError("La ruta del esquema no es válida.")
        return candidate

    def get_schematic_voxels(self, filename: str) -> dict[str, object]:
        path = self.get_schematic_path(filename)
        if not path.is_file():
            raise SchematicNotFoundError("No existe el esquema indicado.")
        return self._decode_nbt_to_voxels(path)

    @staticmethod
    def _decode_nbt_to_voxels(path: Path) -> dict[str, object]:
        nbt = nbtlib.load(path)
        w, h, l = int(nbt["Width"]), int(nbt["Height"]), int(nbt["Length"])
        palette = {int(v): str(k) for k, v in nbt["Palette"].items()}
        block_data = list(nbt["BlockData"])

        voxels: list[list[int]] = []
        idx = 0
        y = z = x = 0
        b_len = len(block_data)
        while idx < b_len and y < h:
            val = 0
            shift = 0
            while True:
                b = block_data[idx]
                if b < 0:
                    b += 256
                idx += 1
                val |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            if val != 0:
                voxels.append([x, y, z, val])
            x += 1
            if x >= w:
                x = 0
                z += 1
                if z >= l:
                    z = 0
                    y += 1

        return {
            "filename": path.name,
            "width": w,
            "height": h,
            "length": l,
            "palette": palette,
            "voxels": voxels,
            "total_voxels": len(voxels),
        }

    def _list_schematics_sync(self) -> list[SchematicItem]:
        items = [self._item_from_path(path) for path in self.schematics_directory.glob("*.nbt") if path.is_file()]
        return sorted(items, key=lambda item: item.modified_at, reverse=True)

    @staticmethod
    def _item_from_path(path: Path) -> SchematicItem:
        return SchematicItem(
            filename=path.name,
            size_kb=round(path.stat().st_size / _KIBIBYTE, 2),
            modified_at=datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        )


schematic_service = SchematicService()
