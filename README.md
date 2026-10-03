# Local Minecraft Server Panel

A self-hosted control panel for starting and sharing a local Minecraft server with friends. It is designed for people who do not want to edit launch flags, run console commands, or manually manage Java processes.

The goal is simple: help a non-technical person host a private Minecraft server for friends in a few guided steps.

## Personal open-source project

I built this for my own server and am sharing it openly so friends can use it, adapt it, and improve it. It is a personal project, not a polished hosting product: expect rough edges and possible bugs. Back up your worlds before relying on it.

This project is not affiliated with, endorsed by, or associated with Mojang Studios, Microsoft, or Minecraft.

## Start in three steps

1. Clone this repository and open its folder.
2. Run `iniciar_panel.bat` on Windows, or `./iniciar_panel.sh` on Linux/macOS. It creates the local Python environment and installs panel dependencies the first time. On Windows, the launcher can install Python through Windows Package Manager if it is missing. On Linux/macOS it uses Homebrew, apt, dnf, or pacman when one is available.
3. The browser opens when the panel is ready. Save the one-time admin password shown on the first screen, then follow the guided setup to install Vanilla, NeoForge, or Fabric; choose RAM; and start playing.

The panel detects Java and the server installation before it starts Minecraft. If Java is missing, the wizard can download a compatible Adoptium runtime into `tools/java` without touching the global installation. You can also download one yourself, unpack it there so `tools/java/bin/java` (or `java.exe`) exists, and return to the panel. This does not touch worlds, backups, or player data.

## What the panel controls

- Minecraft server lifecycle: start, graceful restart, normal stop, and emergency stop.
- Launch RAM: stored locally in `web_panel/.launch_settings.json`, ignored by Git, and used on the next server start.
- Backups, mods, worlds, player access, console activity, and Playit.gg connection status.
- Optional integrations: LuckPerms and Discord. Their per-server settings are local and ignored by Git.

## Privacy and local configuration

This repository contains no webhook URLs, player names, world names, or machine-specific paths. Copy [`web_panel/.env.example`](web_panel/.env.example) to `web_panel/.env` only when you want to override defaults. Do not commit `.env`, webhook URLs, or the local panel settings files.

## Security and data safety

- The panel is intended to run on `127.0.0.1`. Do not expose port `8080` directly to the Internet.
- Keep Playit agent keys, Discord webhooks, passwords, worlds, backups, logs, and player data out of Git.
- Test a restore with a disposable copy before relying on a backup in an emergency. This project can contain bugs and does not replace an external backup.
- Review pull requests carefully when they change server lifecycle, restore, deletion, or public-access behavior.

## Requirements

- Python 3.11 or newer for the panel bootstrap. On Windows, `iniciar_panel.bat` can install it through Windows Package Manager when available.
- A Java runtime compatible with the Minecraft version selected. You can install it normally, or unpack it locally into `tools/java` with `bin/java` (or `bin/java.exe`); the panel and installers prefer that portable copy.
- Internet access while installing a server runtime. The wizard downloads only the server runtime you select; it never commits, replaces, or uploads worlds, backups, mod JARs, or generated libraries.

## Compatibility

- **Panel bootstrap:** Windows, Linux, and macOS with Python 3.11+.
- **Guided installation:** a clean clone can install Vanilla, NeoForge, or Fabric from the local wizard. It writes only the selected runtime files inside `server/`; it refuses to overwrite an existing runtime.
- **Existing servers:** copy a compatible existing server into `server/`, including `run.bat` on Windows or `run.sh` on Linux/macOS. The wizard detects it without moving, changing, or uploading worlds, settings, mods, or backups.
- **Server control:** Vanilla and Fabric receive native Windows and POSIX launch scripts. NeoForge uses its official installer-generated scripts. The panel launches the script native to the host OS.
- **Automatic Playit agent download:** Windows, Linux, and macOS on supported AMD64 or ARM64 hardware. The agent is downloaded from the official Playit release after you link your account.
- **Modpacks:** bring an existing modpack through the import flow. The wizard does not infer a modpack version or replace its files.

## Sharing with friends

Playit.gg is enabled by default. In the wizard, click **Link my Playit account** and approve this computer on Playit’s official claim page; the panel exchanges the short-lived claim code for a local agent key and downloads the agent if needed. A manually supplied agent secret remains available as an advanced fallback. Choose **Local network only** only when external friends should not join.

## Contributing

Issues and pull requests are welcome, especially improvements that make first-run hosting clearer and safer for non-technical players. Please read the [contribution guide](docs/CONTRIBUTING.md) before opening a PR. Never include secrets, worlds, backups, logs, player data, or downloaded JARs in a contribution.

## Credits

- [Minecraft](https://www.minecraft.net/) is a game by Mojang Studios and Microsoft.
- [Playit.gg](https://playit.gg/) provides the optional public connection agent used by the panel.
- This project also depends on the open-source libraries listed in `web_panel/requirements.txt`.

## License

Released under the [MIT License](LICENSE).
