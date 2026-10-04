# Installing mods from the panel

The panel supports a clean owner workflow: install the server first, stop it, add compatible mods, then start it again. It does not include this repository owner's private modpack, worlds, configs, or player data.

## Before adding mods

1. Start the panel and complete the guided server setup.
2. Choose the server runtime you want to run: Vanilla, NeoForge, Fabric, or an imported existing server.
3. Stop the Minecraft server before changing mods. The panel blocks mod installation, deletion, and enable/disable actions while the server is running.

Mods must match the server loader and Minecraft version. A NeoForge server needs NeoForge-compatible mods; a Fabric server needs Fabric-compatible mods.

## Install from Modrinth

1. Open the panel.
2. Go to **Gestor de Mods**.
3. Open **Explorar Catalogo Modrinth**.
4. Search for a mod, for example `Create`, `JEI`, or `Waystones`.
5. Keep the loader and Minecraft version on auto-detect, or choose them manually if you are preparing a specific server version.
6. Click **Instalar Mod**.

The panel downloads the selected Modrinth file into `server/mods/`. When Modrinth declares required dependencies, the panel tries to install those required dependencies too.

## Upload local `.jar` files

1. Open **Gestor de Mods**.
2. Click **Subir .jar**.
3. Select or drag one or more compatible `.jar` files.
4. Wait for the upload to finish.

Uploaded files are stored in `server/mods/`. They are local runtime files and are ignored by Git.

## Enable, disable, update, or delete mods

In **Gestor de Mods**, installed mods can be:

- Enabled or disabled with the switch on each row.
- Enabled, disabled, or deleted in bulk by selecting multiple rows.
- Checked for Modrinth updates with **Buscar Actualizaciones**.
- Deleted permanently from `server/mods/`.

Most mod changes require a server restart. The safest flow is: stop server, change mods, start server, then watch the console for loader errors.

## Give friends the client modpack

Many modded servers also require players to install matching client-side mods.

1. Open **Gestor de Mods**.
2. Click **Generar Modpack ZIP**.
3. Download the generated ZIP.
4. Send it to players so they can copy its `mods/` and included client configuration into their Minecraft instance.

The exporter excludes common server-only tools such as Spark, LuckPerms, WorldEdit, Chunky, BlueMap, and similar admin/server utilities. If a special mod is incorrectly included or excluded, adjust the modpack manually before sharing it.

## Bring an existing modpack

If you already have a working server modpack, copy its server files into `server/` before starting from the panel. The panel detects existing launch scripts and runtime files instead of replacing them.

Do not commit mod JARs, generated libraries, worlds, logs, backups, or local config files.
