import json, os

base = 'pointblank_durability_mod/src/main/resources/data/pointblank_durability/recipe'
os.makedirs(base, exist_ok=True)

# 1. Gun Oil
r_oil = {
    "type": "minecraft:crafting_shapeless",
    "category": "misc",
    "ingredients": [
        {"item": "minecraft:glass_bottle"},
        {"item": "minecraft:honey_bottle"},
        {"item": "minecraft:copper_ingot"}
    ],
    "result": {
        "count": 1,
        "id": "pointblank_durability:gun_oil"
    }
}

# 2. Cleaning Rod
r_rod = {
    "type": "minecraft:crafting_shaped",
    "category": "misc",
    "pattern": [
        "  N",
        " C ",
        "C  "
    ],
    "key": {
        "N": {"item": "minecraft:iron_nugget"},
        "C": {"item": "minecraft:copper_ingot"}
    },
    "result": {
        "count": 1,
        "id": "pointblank_durability:cleaning_rod"
    }
}

# 3. Maintenance Kit
r_kit = {
    "type": "minecraft:crafting_shaped",
    "category": "misc",
    "pattern": [
        "LRL",
        "POP",
        "ICI"
    ],
    "key": {
        "L": {"item": "minecraft:leather"},
        "R": {"item": "pointblank_durability:cleaning_rod"},
        "P": {"item": "minecraft:paper"},
        "O": {"item": "pointblank_durability:gun_oil"},
        "I": {"item": "minecraft:iron_ingot"},
        "C": {"item": "minecraft:copper_ingot"}
    },
    "result": {
        "count": 1,
        "id": "pointblank_durability:maintenance_kit"
    }
}

# 4. Master Gunsmith Kit
r_master = {
    "type": "minecraft:crafting_shaped",
    "category": "misc",
    "pattern": [
        "BMB",
        "OCO",
        "IMI"
    ],
    "key": {
        "B": {"item": "minecraft:iron_block"},
        "M": {"item": "pointblank_durability:maintenance_kit"},
        "O": {"item": "pointblank_durability:gun_oil"},
        "C": {"item": "minecraft:copper_block"},
        "I": {"item": "minecraft:iron_ingot"}
    },
    "result": {
        "count": 1,
        "id": "pointblank_durability:master_gunsmith_kit"
    }
}

for fname, data in [("gun_oil.json", r_oil), ("cleaning_rod.json", r_rod), ("maintenance_kit.json", r_kit), ("master_gunsmith_kit.json", r_master)]:
    path = os.path.join(base, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print("Created recipe:", path)
