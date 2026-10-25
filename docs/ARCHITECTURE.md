# Provider architecture

The panel separates the user experience from the concrete way Minecraft is hosted. The UI and API query declared capabilities; an adapter connects only when the host explicitly configures it.

```text
UI / API
  -> capability catalog
    -> configured provider
      -> local host | Docker | remote agent
```

`web_panel/app/providers/contracts.py` defines the minimum contract. A provider declares its identity, capabilities, and a read-only status. It must not assume Windows, `C:\\` paths, `.bat` scripts, one Java distribution, or a specific loader.

The current local runtime has not yet been migrated to this contract. This is intentional: the process, worlds, backups, and secrets are not altered during this stage. A later migration must preserve the current safeguards and add a local adapter behind integration tests.

Mutable actions will be enabled per capability and with specific confirmations. Declaring a capability does not grant authorization on its own.

## Current local runtime

Until that migration, `web_panel/app/services/server_process.py` runs the server on this PC:

- **Detached process.** Java is launched with its own hidden console (`CREATE_NO_WINDOW` on Windows, a new session elsewhere), so the panel's window, Ctrl+C or a frozen panel never reach it.
- **Console through a file.** Java's output goes to `web_panel/.server_console.log`, which the panel follows and streams to the browser over a WebSocket. Java never waits for the panel to read, so a busy or paged-out panel cannot freeze the game.
- **Commands.** While the panel session that started the server is alive, commands go to Java's standard input. Otherwise they go through RCON, which the panel turns on before a start with a random password (`web_panel/app/services/rcon.py`).
- **Taking the server back.** The launcher's PID and start time are kept in `web_panel/.server_process.json`. When the panel opens and that very process is still alive, it adopts it: it shows the recent console, follows the file and asks RCON who is online. The exit code of an adopted process is unknown, so its log decides between a stop and a crash.
- **Closing the panel.** `stop_with_panel` in `craftpanel.txt` decides: a clean shutdown stops the server, and closing the window or signing out sends `stop` through RCON (or Ctrl+C in the server's own console while it is still loading) before Windows ends the panel.
