"""Fast structural checks for Point Blank Armory resources.

This deliberately avoids Minecraft runtime classes so contributors can run it
before a full NeoForge build. It catches the common release mistake: registering
an item without its recipe, model, translation or parsable resource JSON.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "pointblank_durability_mod"
JAVA = MOD / "src/main/java/com/servidor/durability/PointBlankDurabilityMod.java"
RES = MOD / "src/main/resources"
ASSET_ROOT = RES / "assets/pointblank_durability"
DATA_ROOT = RES / "data/pointblank_durability"


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"Invalid JSON {path.relative_to(ROOT)}: {error}")


def main() -> None:
    source = JAVA.read_text(encoding="utf-8")
    registered = sorted(set(re.findall(r'ITEMS\.register\("([a-z0-9_]+)"', source)))
    if not registered:
        fail("No item registrations found; update the verifier regex if registry style changed.")
    retired = {"ammo_case", "gunsmith_case", "armory_manual", "gun_cabinet", "gunsmith_bench"}
    lingering = retired.intersection(registered)
    if lingering:
        fail(f"Retired visual-content items are still registered: {', '.join(sorted(lingering))}.")

    es = load_json(ASSET_ROOT / "lang/es_es.json")
    en = load_json(ASSET_ROOT / "lang/en_us.json")
    if not isinstance(es, dict) or not isinstance(en, dict):
        fail("Language files must be JSON objects.")

    resource_json = list(RES.rglob("*.json"))
    for path in resource_json:
        load_json(path)

    model_root = ASSET_ROOT / "models"
    for model_path in model_root.rglob("*.json"):
        model_data = load_json(model_path)
        if not isinstance(model_data, dict):
            fail(f"Model must be a JSON object: {model_path.relative_to(ROOT)}")
        parent = model_data.get("parent")
        if isinstance(parent, str) and parent.startswith("pointblank_durability:"):
            parent_path = parent.removeprefix("pointblank_durability:")
            if not (model_root / f"{parent_path}.json").exists():
                fail(f"Missing custom model parent '{parent}' referenced by {model_path.relative_to(ROOT)}.")
        textures = model_data.get("textures", {})
        if isinstance(textures, dict):
            for texture in textures.values():
                if not isinstance(texture, str) or not texture.startswith("pointblank_durability:"):
                    continue
                texture_path = texture.removeprefix("pointblank_durability:")
                if not (ASSET_ROOT / "textures" / f"{texture_path}.png").exists():
                    fail(f"Missing custom texture '{texture}' referenced by {model_path.relative_to(ROOT)}.")

    for item_id in registered:
        model = ASSET_ROOT / "models/item" / f"{item_id}.json"
        recipe = DATA_ROOT / "recipe" / f"{item_id}.json"
        translation = f"item.pointblank_durability.{item_id}"
        if not model.exists():
            fail(f"Missing item model for '{item_id}'.")
        if not recipe.exists():
            fail(f"Missing crafting recipe for '{item_id}'.")
        if translation not in es or translation not in en:
            fail(f"Missing Spanish or English translation for '{item_id}'.")

        recipe_data = load_json(recipe)
        if not isinstance(recipe_data, dict) or recipe_data.get("result", {}).get("id") != f"pointblank_durability:{item_id}":
            fail(f"Recipe for '{item_id}' does not produce its registered item.")

    print(f"OK: {len(registered)} item registrations, recipes, models and bilingual translations verified.")
    print(f"OK: {len(resource_json)} resource JSON files parsed and custom model references resolved.")


if __name__ == "__main__":
    main()
