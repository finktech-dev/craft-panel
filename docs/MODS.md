# Installing mods from the panel

The panel supports a clean owner workflow: install the server first, stop it, add compatible mods, then start it again. It does not include this repository owner's private modpack, worlds, configs, or player data.

## Before adding mods

1. Start the panel and complete the guided server setup.
2. Choose the server runtime you want to run: Vanilla, NeoForge, Fabric, or an imported existing server.
3. Stop the Minecraft server before changing mods. The panel blocks mod installation, deletion, and enable/disable actions while the server is running.

Mods must match the server loader and Minecraft version. A NeoForge server needs NeoForge-compatible mods; a Fabric server needs Fabric-compatible mods.

## Install from Modrinth

1. Open the panel.
2. Go to the **"Mods"** page.
3. Open the **"Buscar mods nuevos"** (Find new mods) tab.
4. In **"Nombre del mod"** (Mod name), search for a mod, for example `Create`, `JEI`, or `Waystones`.
5. Keep the loader and Minecraft version on auto-detect, or choose them manually under **"Opciones avanzadas"** (Advanced options) if you are preparing a specific server version.
6. Click **"Instalar"** (Install).

The panel downloads the selected Modrinth file into `server/mods/`. When Modrinth declares required dependencies, the panel tries to install those required dependencies too.

## Upload local `.jar` files

1. Open the **"Mods"** page.
2. Click **"Agregar desde archivo"** (Add from file).
3. Select or drag one or more compatible `.jar` files.
4. Wait for the upload to finish.

Uploaded files are stored in `server/mods/`. They are local runtime files and are ignored by Git.

## Enable, disable, update, or delete mods

On the **"Mods"** page, under **"Tus mods"** (Your mods), installed mods can be:

- Enabled or disabled with the switch on each row.
- Enabled, disabled, or deleted in bulk by selecting multiple rows and clicking **"Encender"** (Turn on), **"Apagar"** (Turn off) or **"Quitar"** (Remove).
- Checked for Modrinth updates with **"Ver si hay actualizaciones"** (Check for updates). When newer versions exist, the **"Actualizaciones"** (Updates) tab lists them with **"Actualizar"** (Update) per mod and **"Actualizar todos"** (Update all). A newer version is not always better for an existing world, so read the changes first.
- Removed with **"Quitar"** (Remove).

Before every change the panel saves the state of the mods folder, keeping a copy of each jar in `web_panel/.mod_history`. The **"Historial"** (History) tab can put things back as they were with **"Volver a este punto"** (Go back to this point), including removed or updated mods.

The panel only changes mods while the server is stopped: stop it, change mods, start it again, then watch the console for loader errors.

## Give friends the client modpack

Many modded servers also require players to install matching client-side mods.

1. Open the **"Mods"** page and find **"Paquete para tus amigos"** (Pack for your friends).
2. Click **"Preparar paquete"** (Prepare pack).
3. Download the generated ZIP with **"Descargar paquete"** (Download pack).
4. Send it to players so they can copy its `mods/` and included client configuration into their Minecraft instance.

The exporter excludes common server-only tools such as Spark, LuckPerms, WorldEdit, Chunky, BlueMap, and similar admin/server utilities. The **"Solo del servidor"** (Server only) filter shows which mods are left out. To mark more of them, list them under [`[server_only_mods]`](SERVER_FILE.md) in `craftpanel.txt`. If a special mod is still wrongly included or excluded, adjust the pack by hand before sharing it.

## Bring an existing modpack

If you already have a working server modpack, copy its server files into `server/` before starting from the panel. The panel detects existing launch scripts and runtime files instead of replacing them.

Do not commit mod JARs, generated libraries, worlds, logs, backups, or local config files.
