"""
Script de descarga e instalación automatizada de mods para el servidor y cliente NeoForge 1.21.1.
"""

import asyncio
import json
import os
import shutil
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parent.parent
SERVER_MODS_DIR = ROOT / "server" / "mods"
POINTBLANK_DIR = ROOT / "server" / "pointblank"
CLIENT_ONLY_DIR = ROOT / "server" / "client_only_mods"

# Slugs de Modrinth para mods de SERVIDOR (compartidos o server-side)
MODRINTH_SERVER_MODS = [
    # Contenido, Estructuras y Dimensiones
    "advanced-netherite",
    "amplified-nether",
    "stack-refill",
    "clifftree",
    "dungeons-and-taverns",
    "small-ships",
    "enderman-overhaul",
    "regions-unexplored",
    "towns-and-towers",
    "mns-moogs-nether-structures",
    "moogs-structure-lib",
    "kaleidoscope-cookery",
    "kaleidoscopetavern",
    "hellish-trials",
    "architectury-api",
    "shulkerboxtooltip",
    "yungs-better-end-island",
    "yungs-api",
    "incendium",
    "evilcraft",
    "cyclops-core",
    "artifacts",
    "the-great-outdoors",
    "security-craft",
    "rechiseled",
    "rechiseled-create",
    "chisel-reborn",
    "xaeros-minimap",
    "xaeros-world-map",
    "useful-backpacks",
    "u-team-core",
    "jei",
    "waystones",
    "balm",
    "l_enders-cataclysm",
    "lionfish-api",
    "curios",
    "corpse",
    "comforts",
    "jade",

    # Decoración, Muebles y Construcción
    "supplementaries",
    "moonlight",
    "amendments",
    "macaws-roofs",
    "macaws-doors",
    "macaws-windows",
    "macaws-bridges",
    "macaws-fences-and-walls",
    "create-deco",

    # Cocina y Gastronomía
    "farmers-delight",
    "brewin-and-chewin",
    "crabbers-delight",

    # Núcleo Mecánico, Ferrocarril y Combate
    "create",
    "create-steam-n-rails-1.21.1",
    "vics-point-blank",
    "playeranimator",
    "simply-swords",
    "geckolib",
    "cloth-config",
    "aether",
    "the-undergarden",
    "simple-voice-chat",
    "sound-physics-remastered",

    # Optimización y Utilidades Servidor
    "modernfix",
    "ferrite-core",
    "chunky",
    "noisium",
    "alternate-current",
    "clumps",
    "ai-improvements",
    "fastsuite",
    "spark",
    "bluemap",
    "luckperms",
    "skinrestorer",

    # Construcción y Decoración
    "chipped",
    "athena-ctm",
    "paladins-furniture",
    "urban-decor",
    "runiclib",
    "diagonal-fences",
    "puzzles-lib",
    "immersive-paintings",
]

# Mods exclusivos de CLIENTE (no deben ir al servidor para no romper el entorno headless)
MODRINTH_CLIENT_MODS = [
    "immediatelyfast",
    "entityculling",
    "dynamic-fps",
    "embeddium",
    "distanthorizons",
    "konkrete",
    "appleskin",
    "moreculling",
]

# Descargas directas de CurseForge (Servidor)
CURSEFORGE_MODS = [
    ("Nenu's Pop Plushies", "https://edge.forgecdn.net/files/8813/400/nenus_pop_plushies-2.9.0-neoforge-1.21.1.jar", "nenus_pop_plushies-2.9.0-neoforge-1.21.1.jar"),
    ("Chimes", "https://edge.forgecdn.net/files/7573/270/Chimes-v2.1.1-1.21.1-NeoForge.jar", "Chimes-v2.1.1-1.21.1-NeoForge.jar"),
    ("Connectivity", "https://edge.forgecdn.net/files/7367/221/connectivity-1.21.1-7.6.jar", "connectivity-1.21.1-7.6.jar"),
    ("Cupboard (Dependency)", "https://edge.forgecdn.net/files/8889/50/cupboard-1.21.1-4.2.jar", "cupboard-1.21.1-4.2.jar"),
    ("Terralith", "https://edge.forgecdn.net/files/8222/737/Terralith_1.21.x_v2.6.2.jar", "Terralith_1.21.x_v2.6.2.jar"),
    ("Mowzie's Mobs", "https://edge.forgecdn.net/files/7760/267/mowziesmobs-1.21.1-1.8.2.jar", "mowziesmobs-1.21.1-1.8.2.jar"),
    ("Lithium", "https://edge.forgecdn.net/files/8330/365/lithium-neoforge-0.15.4%2bmc1.21.1.jar", "lithium-neoforge-0.15.4+mc1.21.1.jar"),
]

# Descargas directas de CurseForge (Exclusivos de Cliente)
CURSEFORGE_CLIENT_MODS = [
    ("Just Zoom", "https://edge.forgecdn.net/files/6290/230/justzoom_neoforge_2.1.0_MC_1.21.1.jar", "justzoom_neoforge_2.1.0_MC_1.21.1.jar"),
    ("Dynamic Lights", "https://edge.forgecdn.net/files/6182/439/dynamiclights-1.21.1.2NF.jar", "dynamiclights-1.21.1.2NF.jar"),
]


async def get_modrinth_download_info(client: httpx.AsyncClient, slug: str):
    url = f"https://api.modrinth.com/v2/project/{slug}/version"
    # Intentar NeoForge 1.21.1
    resp = await client.get(url, params={"loaders": json.dumps(["neoforge"]), "game_versions": json.dumps(["1.21.1"])})
    if resp.status_code == 200 and resp.json():
        v = resp.json()[0]
        f = v["files"][0]
        return f["filename"], f["url"], v["version_number"]
    
    # Intentar NeoForge 1.21
    resp2 = await client.get(url, params={"loaders": json.dumps(["neoforge"]), "game_versions": json.dumps(["1.21"])})
    if resp2.status_code == 200 and resp2.json():
        v = resp2.json()[0]
        f = v["files"][0]
        return f["filename"], f["url"], v["version_number"]
    
    # Intentar genérico
    resp3 = await client.get(url)
    if resp3.status_code == 200 and resp3.json():
        for v in resp3.json():
            if any(g in ["1.21.1", "1.21"] for g in v.get("game_versions", [])):
                f = v["files"][0]
                return f["filename"], f["url"], v["version_number"]
    return None, None, None


async def download_file(client: httpx.AsyncClient, url: str, dest_path: Path, name: str):
    if dest_path.exists() and dest_path.stat().st_size > 1024:
        print(f"[YA EXISTE] {name} ({dest_path.name})")
        return True
    
    temp_path = dest_path.with_suffix(".downloading")
    try:
        async with client.stream("GET", url, follow_redirects=True) as resp:
            resp.raise_for_status()
            with open(temp_path, "wb") as f:
                async for chunk in resp.aiter_bytes(64 * 1024):
                    f.write(chunk)
        temp_path.replace(dest_path)
        size_mb = round(dest_path.stat().st_size / (1024 * 1024), 2)
        print(f"[DESCARGADO] {name} -> {dest_path.name} ({size_mb} MB)")
        return True
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        print(f"[ERROR] {name}: {e}")
        return False


async def main():
    SERVER_MODS_DIR.mkdir(parents=True, exist_ok=True)
    POINTBLANK_DIR.mkdir(parents=True, exist_ok=True)
    CLIENT_ONLY_DIR.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": "Antigravity/1.0 (Minecraft Server Manager)"}
    async with httpx.AsyncClient(timeout=90.0, headers=headers) as client:
        print("--- 1. DESCARGANDO MODS DE SERVIDOR (MODRINTH) ---")
        for slug in MODRINTH_SERVER_MODS:
            fname, url, ver = await get_modrinth_download_info(client, slug)
            if url:
                await download_file(client, url, SERVER_MODS_DIR / fname, slug)
            else:
                print(f"[NO ENCONTRADO EN MODRINTH] {slug}")

        print("\n--- 2. DESCARGANDO MODS DE SERVIDOR (CURSEFORGE) ---")
        for name, url, fname in CURSEFORGE_MODS:
            await download_file(client, url, SERVER_MODS_DIR / fname, name)

        print("\n--- 3. DESCARGANDO MODS EXCLUSIVOS DE CLIENTE (MODRINTH) ---")
        for slug in MODRINTH_CLIENT_MODS:
            fname, url, ver = await get_modrinth_download_info(client, slug)
            if url:
                await download_file(client, url, CLIENT_ONLY_DIR / fname, slug)
            else:
                print(f"[NO ENCONTRADO EN MODRINTH CLIENTE] {slug}")

        print("\n--- 3.1 DESCARGANDO MODS EXCLUSIVOS DE CLIENTE (CURSEFORGE) ---")
        for name, url, fname in CURSEFORGE_CLIENT_MODS:
            await download_file(client, url, CLIENT_ONLY_DIR / fname, name)

    print("\n=== RESUMEN ===")
    server_mods = list(SERVER_MODS_DIR.glob("*.jar"))
    client_mods = list(CLIENT_ONLY_DIR.glob("*.jar"))
    pb_files = list(POINTBLANK_DIR.glob("*"))
    print(f"Total mods en server/mods: {len(server_mods)}")
    print(f"Total mods en client_only_mods: {len(client_mods)}")
    print(f"Total packs en server/pointblank: {len(pb_files)}")


if __name__ == "__main__":
    asyncio.run(main())
