# Optional LuckPerms integration per installation

The panel does not assume LuckPerms is installed and does not keep a server's groups in JavaScript. To enable it, copy `web_panel/config/luckperms.json.example` to `web_panel/.luckperms_config.json` and set `enabled` to `true`.

`preset` can point to a JSON file in `web_panel/config/presets/luckperms/`. A preset is optional. For a new server, create your own local preset or define `primary_ranks` and `secondary_roles` directly in the local file.

The local file is ignored by Git. While LuckPerms is disabled, the panel hides its module and its endpoints never send commands to the server.
