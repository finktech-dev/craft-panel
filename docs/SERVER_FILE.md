# `server/craftpanel.txt`: settings for one server

`craftpanel.txt` lives inside the server folder and holds the settings that belong to that server. You can edit it with Notepad or from **"Ajustes" › "Tu servidor"** (Settings › Your server) in the panel; both edit the same file. Supported and tested on Windows 10 and Windows 11.

- The panel never creates the file on its own: until you save from "Ajustes" it uses its defaults.
- The file belongs to you. The panel never deletes or renames it, keeps your comments and blank lines, and only rewrites the lines whose value you changed. Keys or sections it does not know are left exactly as they are.
- If a line is wrong, the panel ignores only that line (and uses its default), lists the problem in "Ajustes" with its line number, and refuses to save new text with mistakes. A wrong `start_script` or `java` blocks starting the server until it is fixed, so the panel never starts the wrong thing.

## Format

```ini
# Lines starting with # are comments.
key = value          # (comments only at the start of a line)

[section]
one entry per line
```

- Keys and section names are English `snake_case`; `[backup-exclude]` and `[backup_exclude]` are the same.
- Switches: `true` or `false`.
- Durations: a number and `s`, `m`, `h` or `d`, such as `90s`, `10m`, `6h`, `2d`.
- Sizes: `512MB`, `15GB`, `2TB`.
- Gitignore-style lists (`[backup_exclude]`, `[protected]`) support `*`, `?`, `**`, a trailing `/` for folders, `!` to bring something back, and `#` comments. Matching ignores upper/lower case, as Windows does.
- UTF-8, Windows (CRLF) or Unix line endings.

## Keys

| Key | Default | What it controls |
| --- | --- | --- |
| `start_script` | `run.bat` | Script that starts the server, a plain name inside the server folder (`.bat`/`.cmd`). Letters, digits, `.`, `_`, `-` only. Changes only while the server is off. |
| `java` | automatic | Full path to `java.exe`/`javaw.exe`. Its folder goes first on `PATH` for the server and it is the Java checked for version compatibility. Changes only while the server is off. |
| `memory` | RAM chosen in setup | Server RAM such as `6G`. Written into `user_jvm_args.txt` (`-Xmx`/`-Xms`) before each start and kept in step with the RAM selector. Limited to what the PC can spare. |
| `start_with_panel` | `false` | Start the server as a job when the panel opens (skipped if a server is already open outside the panel or Playit still needs setup). |
| `stop_with_panel` | `true` | Stop the server, saving the world, when the panel closes: with Ctrl+C, the window's close button or signing out of Windows. With `false` it keeps running on its own and the panel takes it back (console, commands and players) the next time it opens. |
| `startup_timeout` | `5m` | How long a start or restart waits for the world before saying it is still loading (30s to 60m). |
| `restart_on_crash` | `false` | Start the server again, as a job, 10 seconds after it ends on its own. Never after a requested stop or a forced close. |
| `max_crash_restarts` | `3` | After this many crashes within 10 minutes, automatic restarts stop; the console and the dashboard's "Cosas para revisar" (Things to check) say so. Starting the server by hand turns them back on. |
| `daily_restart` | off | Daily graceful restart at `HH:MM` (24 h, this PC's time). Skipped when the server is off. |
| `restart_warning` | `60s` | How long before a daily restart players are warned in the chat (10s to 10m). |
| `idle_shutdown` | off | Stop the server (saving the world) after fewer than `idle_min_players` players for this long (5m to 24h). The countdown starts once the world has loaded, resets when enough players are online, and players still online are warned in the chat one minute before. |
| `idle_min_players` | `1` | Players needed to keep the server on (1 to 100). `1` means it stops only when nobody is online. |
| `backup_interval` | `6h` | Time between automatic copies (at least `1h`). Set it in **"Ajustes" › "Tu servidor" › "Copias"** (Settings › Your server › Backups). An interval chosen with an older version of the panel still applies while this line is empty. |
| `backup_keep` | `4` | How many copies to keep. |
| `backup_max_size` | `15GB` | Space for all copies together; the newest copy is always kept. |
| `backup_location` | the panel's `backups` folder | Absolute folder for new copies, ideally on another drive. It must be outside the server folder, not a drive root, and writable. Copies left in the previous folder stay listed and restorable but are never purged; the free-space check follows the new folder. |
| `server_name` | panel default | Name in the panel header and page titles, Discord messages and the status image. |
| `public_address` | automatic | Address shown to friends (`host` or `host:port`) when Playit has no address of its own, for example when it runs as a Windows service. |

## Sections

| Section | What it controls |
| --- | --- |
| `[detect]` | Words from your server's command line (for example the name of its `.jar`) that identify it when it was opened outside the panel. Up to 20 lines, 4 to 100 characters each. |
| `[backup_exclude]` | Gitignore-style patterns, relative to the world folder, left out of copies and of the "world did not change" check. Patterns that would leave out the whole world, `level.dat` or `region` are rejected. Up to 200 lines. What is not copied does not come back when restoring. |
| `[backup_include]` | Extra files or folders relative to the server folder (for example `config/`, `server.properties`) added to every copy under `server_files/`. A restore only puts them back when you tick "También volver la configuración" (Also restore the settings), with the server off, and never over `[protected]` paths. Up to 50 lines. |
| `[server_only_mods]` | Mod file name patterns (`*-server.jar`) or mod ids left out of the friends' pack and marked "solo del servidor" (server only) on the "Mods" page. |
| `[protected]` | Gitignore-style patterns, relative to the server folder, that the panel never changes or deletes: mod changes, the config editor, `server.properties` edits, world deletion, restores, the installer and `user_jvm_args.txt`. The panel answers "Ese archivo está protegido en craftpanel.txt" (That file is protected in craftpanel.txt). Patterns that would protect almost everything (`*`, `**`, `/`) are rejected. |

## Full example

The two comment lines at the top are Spanish, like the comments the panel itself writes. They mean "Craft Panel · settings for this server" and "You can edit this file by hand or from Ajustes (Settings)."

```ini
# Craft Panel · ajustes de este servidor
# Podés editar este archivo a mano o desde Ajustes.

start_script = run.bat
java = C:\Program Files\Eclipse Adoptium\jdk-21\bin\java.exe
memory = 6G
start_with_panel = false
stop_with_panel = true
startup_timeout = 10m
restart_on_crash = true
max_crash_restarts = 3
daily_restart = 05:30
restart_warning = 2m
idle_shutdown = 30m
idle_min_players = 1

backup_interval = 6h
backup_keep = 6
backup_max_size = 40GB
backup_location = D:\Server copies

server_name = Friends server
public_address = play.example.com:25565

[detect]
my-modpack-server.jar

[backup_exclude]
logs/
*.tmp
**/cache/
!cache/keep-this.dat

[backup_include]
config/
server.properties

[server_only_mods]
*-server.jar
statsbridge

[protected]
config/my-tuned-mod.toml
```

## How the panel recognises a server opened outside it

A server the panel itself started and left running (with `stop_with_panel = false`, or because the panel closed unexpectedly) is not "outside": when the panel opens it finds that very process (same PID and start time) and takes it back, with its console, commands and players.

Before starting, the panel looks at Java processes and at whatever listens on `server-port`, and collects evidence: it has the active world's `session.lock` open, it was opened from the server folder, its command line mentions the server folder or one of your `[detect]` words, it looks like a Minecraft launch (`@user_jvm_args.txt`, Forge/NeoForge libraries, Fabric's launcher, `nogui`), or it was started by the panel last time. The dashboard lists those reasons in plain words. Only a Java process with confident evidence (world lock, folder, command line, `[detect]` word or previous panel session) can be closed from the panel; anything holding the world or the port still blocks starting a second copy.
