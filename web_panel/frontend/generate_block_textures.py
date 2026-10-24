"""Generate the original 16x16 block textures used by the schematic 3D preview.

Every texture is drawn procedurally from simple shapes, a few hand-picked colours
and deterministic hash noise, so the output is identical on every run and no
third-party artwork is involved. Standard library only.

Usage (from the repository root):
    python web_panel/frontend/generate_block_textures.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIZE = 16
OUTPUT = Path(__file__).resolve().parent.parent / "static" / "textures" / "blocks"

Pixel = tuple[int, int, int, int]
Grid = list[list[Pixel]]


# --- helpers -----------------------------------------------------------------

def noise(x: int, y: int, seed: int) -> float:
    """Deterministic value in [0, 1) for a pixel and seed."""
    n = (x * 374761393 + y * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFF) / 65536.0


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def shade(colour: str, amount: float, alpha: int = 255) -> Pixel:
    """Lighten (amount > 0) or darken (amount < 0) a colour by a fraction."""
    r, g, b = hex_rgb(colour)
    if amount >= 0:
        r, g, b = (int(c + (255 - c) * amount) for c in (r, g, b))
    else:
        r, g, b = (int(c * (1 + amount)) for c in (r, g, b))
    return r, g, b, alpha


def blank() -> Grid:
    return [[(0, 0, 0, 0)] * SIZE for _ in range(SIZE)]


def fill(base: str, seed: int, spread: float = 0.08) -> Grid:
    """A solid surface with gentle per-pixel noise."""
    return [[shade(base, (noise(x, y, seed) - 0.5) * 2 * spread) for x in range(SIZE)] for y in range(SIZE)]


def put(grid: Grid, x: int, y: int, pixel: Pixel) -> None:
    if 0 <= x < SIZE and 0 <= y < SIZE:
        grid[y][x] = pixel


def write_png(path: Path, grid: Grid) -> None:
    raw = b"".join(b"\x00" + bytes(channel for pixel in row for channel in pixel) for row in grid)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", len(grid[0]), len(grid), 8, 6, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# --- building blocks ---------------------------------------------------------

def masonry(base: str, mortar: str, seed: int, rows: tuple[int, ...], offsets: tuple[int, ...], width: int) -> Grid:
    """Courses of blocks separated by mortar lines; each block gets its own tone."""
    grid = fill(base, seed, 0.06)
    edges = (0,) + rows
    for index, top in enumerate(edges):
        bottom = edges[index + 1] if index + 1 < len(edges) else SIZE
        offset = offsets[index % len(offsets)]
        for y in range(top, bottom):
            for x in range(SIZE):
                column = (x + offset) % SIZE
                block = (column // width, index)
                tone = (noise(*block, seed + 7) - 0.5) * 0.12
                if y == top or column % width == 0:
                    grid[y][x] = shade(mortar, (noise(x, y, seed + 3) - 0.5) * 0.1)
                else:
                    edge_light = 0.06 if y == top + 1 else (-0.08 if y == bottom - 1 else 0.0)
                    grid[y][x] = shade(base, tone + edge_light + (noise(x, y, seed) - 0.5) * 0.1)
    return grid


def planks(base: str, seed: int) -> Grid:
    """Four horizontal boards with grain streaks and staggered butt joints."""
    grid = blank()
    joints = (5, 11, 2, 9)
    for y in range(SIZE):
        board = y // 4
        for x in range(SIZE):
            if y % 4 == 3:
                grid[y][x] = shade(base, -0.35)
            elif x == joints[board]:
                grid[y][x] = shade(base, -0.28)
            else:
                streak = noise(x // 3, y, seed + board) - 0.5
                grid[y][x] = shade(base, streak * 0.16 + (noise(x, y, seed) - 0.5) * 0.06 + board * 0.015)
    for board in range(4):
        knot_x = int(noise(board, 1, seed + 40) * 13) + 1
        put(grid, knot_x, board * 4 + 1, shade(base, -0.22))
    return grid


def add_cracks(grid: Grid, colour: str, path: list[tuple[int, int]]) -> Grid:
    for x, y in path:
        put(grid, x, y, shade(colour, 0.0))
    return grid


# --- textures ----------------------------------------------------------------

def stone_bricks() -> Grid:
    return masonry("#8c8a85", "#5c5a56", 11, (8,), (0, 4), 8)


def cracked_stone_bricks() -> Grid:
    grid = masonry("#84827d", "#55534f", 12, (8,), (0, 4), 8)
    return add_cracks(grid, "#46443f", [(3, 2), (4, 3), (4, 4), (5, 5), (11, 9), (12, 10), (12, 11), (13, 12), (10, 13)])


def mossy_stone_bricks() -> Grid:
    grid = masonry("#8a8882", "#5a5853", 13, (8,), (0, 4), 8)
    for y in range(SIZE):
        for x in range(SIZE):
            weight = noise(x // 2, y // 2, 99) + (0.35 if y in (0, 1, 8, 9) else 0.0)
            if weight > 0.78:
                grid[y][x] = shade("#5f7a3e", (noise(x, y, 98) - 0.5) * 0.3)
    return grid


def chiseled_stone_bricks() -> Grid:
    grid = fill("#88867f", 14, 0.05)
    for i in range(SIZE):
        for edge in (0, SIZE - 1):
            grid[edge][i] = shade("#5c5a55", 0.0)
            grid[i][edge] = shade("#5c5a55", 0.0)
    for i in range(3, 13):
        for edge in (3, 12):
            grid[edge][i] = shade("#6c6a64", 0.0)
            grid[i][edge] = shade("#6c6a64", 0.0)
    for y in range(6, 10):
        for x in range(6, 10):
            grid[y][x] = shade("#9d9b94", (noise(x, y, 15) - 0.5) * 0.1)
    for x, y in ((6, 6), (9, 9)):
        put(grid, x, y, shade("#6c6a64", 0.0))
    return grid


def deepslate_bricks() -> Grid:
    return masonry("#4a4a4f", "#2c2c30", 21, (4, 8, 12), (0, 3, 0, 3), 6)


def cracked_deepslate_bricks() -> Grid:
    grid = masonry("#45454a", "#29292d", 22, (4, 8, 12), (0, 3, 0, 3), 6)
    return add_cracks(grid, "#1f1f22", [(2, 1), (3, 2), (3, 3), (9, 5), (10, 6), (10, 7), (6, 10), (7, 11), (13, 13), (14, 14)])


def deepslate_tiles() -> Grid:
    return masonry("#3c3c41", "#222226", 23, (4, 8, 12), (0, 0, 0, 0), 4)


def polished_deepslate() -> Grid:
    grid = fill("#505056", 24, 0.04)
    for i in range(SIZE):
        grid[0][i] = shade("#505056", 0.12)
        grid[i][0] = shade("#505056", 0.08)
        grid[SIZE - 1][i] = shade("#505056", -0.3)
        grid[i][SIZE - 1] = shade("#505056", -0.25)
    return grid


def andesite() -> Grid:
    grid = fill("#8b8d89", 31, 0.1)
    for y in range(SIZE):
        for x in range(SIZE):
            value = noise(x, y, 32)
            if value > 0.9:
                grid[y][x] = shade("#b4b6b2", 0.0)
            elif value < 0.08:
                grid[y][x] = shade("#686a66", 0.0)
    return grid


def polished_andesite() -> Grid:
    grid = fill("#8e908c", 33, 0.04)
    for i in range(SIZE):
        grid[0][i] = shade("#8e908c", 0.14)
        grid[i][0] = shade("#8e908c", 0.1)
        grid[SIZE - 1][i] = shade("#8e908c", -0.22)
        grid[i][SIZE - 1] = shade("#8e908c", -0.18)
    return grid


def gravel() -> Grid:
    grid = fill("#7f7a74", 41, 0.06)
    stones = ("#9a948c", "#6a655f", "#8c8279", "#5a5651")
    for cell_y in range(0, SIZE, 3):
        for cell_x in range(0, SIZE, 3):
            colour = stones[int(noise(cell_x, cell_y, 42) * len(stones))]
            ox = int(noise(cell_x, cell_y, 43) * 2)
            oy = int(noise(cell_x, cell_y, 44) * 2)
            for dy in range(2):
                for dx in range(2):
                    if noise(cell_x + dx, cell_y + dy, 45) > 0.2:
                        put(grid, cell_x + ox + dx, cell_y + oy + dy, shade(colour, (noise(dx, dy, cell_x + cell_y) - 0.5) * 0.12))
    return grid


def oak_planks() -> Grid:
    return planks("#a8834f", 51)


def spruce_planks() -> Grid:
    return planks("#6f5132", 52)


def dark_oak_planks() -> Grid:
    return planks("#46301d", 53)


def glass() -> Grid:
    grid = blank()
    frame = "#d6e6ea"
    for i in range(SIZE):
        for x, y in ((i, 0), (i, SIZE - 1), (0, i), (SIZE - 1, i)):
            grid[y][x] = shade(frame, 0.0, 230)
    for y in range(1, SIZE - 1):
        for x in range(1, SIZE - 1):
            grid[y][x] = shade("#c8dde2", 0.0, 40)
    # Two short diagonal glints in opposite corners.
    for x, y in ((3, 4), (4, 3), (4, 5), (5, 4), (11, 12), (12, 11)):
        grid[y][x] = shade("#ffffff", 0.0, 170)
    return grid


def iron_bars() -> Grid:
    grid = blank()
    for x in (1, 5, 10, 14):
        for y in range(SIZE):
            grid[y][x] = shade("#9b9fa3", 0.12 if y % 5 == 0 else (noise(x, y, 61) - 0.5) * 0.1)
            put(grid, x + 1, y, shade("#6c7074", 0.0))
    for y in (2, 13):
        for x in range(SIZE):
            grid[y][x] = shade("#a7abaf", (noise(x, y, 62) - 0.5) * 0.1)
    return grid


def chain() -> Grid:
    grid = blank()
    # Alternating front-facing rings and edge-on links down the centre.
    for top in (0, 8):
        for y in range(top, top + 5):
            for x in (6, 9):
                put(grid, x, y, shade("#5d636b", 0.0))
        for x in (7, 8):
            put(grid, x, top, shade("#7a818a", 0.0))
            put(grid, x, top + 4, shade("#474c52", 0.0))
        for y in range(top + 4, top + 9):
            put(grid, 7, y, shade("#6a7079", 0.08))
            put(grid, 8, y, shade("#4b5056", 0.0))
    return grid


def lantern() -> Grid:
    grid = blank()
    metal, dark, glow = "#3d3f44", "#26272b", "#f2b54a"
    for x in range(7, 9):
        put(grid, x, 1, shade(metal, 0.1))
    for x in range(5, 11):
        put(grid, x, 3, shade(metal, 0.05))
        put(grid, x, 4, shade(dark, 0.0))
    for y in range(5, 13):
        put(grid, 4, y, shade(metal, 0.0))
        put(grid, 11, y, shade(dark, 0.0))
        for x in range(5, 11):
            core = abs(x - 7.5) + abs(y - 8.5) * 0.6
            put(grid, x, y, shade(glow, max(-0.3, 0.35 - core * 0.12)))
    for x in range(4, 12):
        put(grid, x, 13, shade(metal, 0.05))
        put(grid, x, 14, shade(dark, 0.0))
    return grid


def create_track() -> Grid:
    grid = blank()
    for y in range(SIZE):
        for x in range(SIZE):
            if y % 4 in (1, 2):
                grid[y][x] = shade("#7a5530", (noise(x // 2, y, 71) - 0.5) * 0.2)
    for x in (3, 12):
        for y in range(SIZE):
            put(grid, x, y, shade("#8e9196", 0.15 if y % 2 else 0.0))
            put(grid, x + 1, y, shade("#5d6065", 0.0))
    return grid


def create_andesite_scaffold() -> Grid:
    grid = blank()
    frame = "#7e817c"
    for i in range(SIZE):
        for x, y in ((i, 0), (i, 1), (i, SIZE - 2), (i, SIZE - 1), (0, i), (1, i), (SIZE - 2, i), (SIZE - 1, i)):
            grid[y][x] = shade(frame, (noise(x, y, 81) - 0.5) * 0.14)
    for i in range(2, SIZE - 2):
        put(grid, i, i, shade("#6a6d68", 0.0))
        put(grid, i + 1, i, shade("#5a5d58", 0.0))
    return grid


def create_andesite_casing() -> Grid:
    grid = fill("#8a8c86", 91, 0.06)
    wood = "#a57c48"
    for i in range(SIZE):
        for x, y in ((i, 0), (i, 1), (i, SIZE - 2), (i, SIZE - 1), (0, i), (1, i), (SIZE - 2, i), (SIZE - 1, i)):
            grid[y][x] = shade(wood, (noise(x, y, 92) - 0.5) * 0.16)
    for x, y in ((2, 2), (13, 2), (2, 13), (13, 13)):
        put(grid, x, y, shade("#585a55", 0.0))
    return grid


TEXTURES = {
    "andesite": andesite,
    "chain": chain,
    "chiseled_stone_bricks": chiseled_stone_bricks,
    "cracked_deepslate_bricks": cracked_deepslate_bricks,
    "cracked_stone_bricks": cracked_stone_bricks,
    "create_andesite_casing": create_andesite_casing,
    "create_andesite_scaffold": create_andesite_scaffold,
    "create_track": create_track,
    "dark_oak_planks": dark_oak_planks,
    "deepslate_bricks": deepslate_bricks,
    "deepslate_tiles": deepslate_tiles,
    "glass": glass,
    "gravel": gravel,
    "iron_bars": iron_bars,
    "lantern": lantern,
    "mossy_stone_bricks": mossy_stone_bricks,
    "oak_planks": oak_planks,
    "polished_andesite": polished_andesite,
    "polished_deepslate": polished_deepslate,
    "spruce_planks": spruce_planks,
    "stone_bricks": stone_bricks,
}


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, draw in TEXTURES.items():
        write_png(OUTPUT / f"{name}.png", draw())
    print(f"Wrote {len(TEXTURES)} textures to {OUTPUT}")


if __name__ == "__main__":
    main()
