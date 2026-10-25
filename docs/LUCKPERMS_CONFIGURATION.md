# Optional LuckPerms integration per installation

The panel does not assume LuckPerms is installed and does not keep a server's groups in JavaScript.

## Turning it on

- **From the panel:** open **"Ajustes" › "Rangos y permisos"** (Settings › Ranks and permissions) and click **"Activar rangos"** (Turn on ranks).
- **Automatically:** with no local configuration yet, a LuckPerms jar in `server/mods` turns the integration on with the default ranks.
- **By hand (advanced):** copy `web_panel/config/luckperms.json.example` to `web_panel/.luckperms_config.json` and set `enabled` to `true`.

While the integration is off, the section shows the activation prompt instead, and its endpoints never send commands to the server.

## Ranks and presets

`preset` names a JSON file in `web_panel/config/presets/luckperms/`, written **without** `.json` (`"preset": "my-ranks"` reads `my-ranks.json`). That folder may not exist yet; create it if you use presets. A preset is optional: you can also define `primary_ranks` and `secondary_roles` directly in the local file.

The local file is ignored by Git, so a server's own ranks never end up in the repository.
