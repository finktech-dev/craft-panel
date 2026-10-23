# Block textures

These 16x16 textures are original artwork made for Craft Panel. They are drawn
procedurally (simple shapes, a few hand-picked colours and deterministic noise)
by `web_panel/frontend/generate_block_textures.py`; no Minecraft or mod assets
are included. They share the panel's license.

The filenames match the block ids the schematic 3D preview looks up, so keep
them when editing. To regenerate every file, run from the repository root:

```
python web_panel/frontend/generate_block_textures.py
```
