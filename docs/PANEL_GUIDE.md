# Panel guide

A tour of everything Craft Panel can do, page by page. The panel's screens are in Spanish, so each control is quoted as it appears, with an English translation the first time it shows up.

For the settings file see [SERVER_FILE.md](SERVER_FILE.md); for what the panel protects and how, [SECURITY.md](SECURITY.md).

## Contents

- [Opening the panel](#opening-the-panel)
- [The menu](#the-menu)
- [First-time setup](#first-time-setup)
- [Inicio (Home)](#inicio-home)
- [Consola (Console)](#consola-console)
- [Mods](#mods)
- [Copias (Backups)](#copias-backups)
- [Mundo (World) and Jugadores (Players)](#mundo-world-and-jugadores-players)
- [Problemas (Problems)](#problemas-problems)
- [Ajustes (Settings)](#ajustes-settings)
- [Closing the panel](#closing-the-panel)
- [Things that need the server off](#things-that-need-the-server-off)
- [The scripts in the main folder](#the-scripts-in-the-main-folder)

## Opening the panel

1. Run `iniciar_panel.bat`. The first time it finds or installs Python, prepares the panel and opens your browser at `http://127.0.0.1:8080`. Keep that window open while you use the panel.
2. The first time, the login page shows a box **"Guardá esta contraseña"** (Save this password) with a generated password and **"Copiar"** (Copy). It is shown only in a browser on this PC and only until you log in once, so save it somewhere safe.
3. Type it in **"Contraseña"** (Password) and click **"Entrar"** (Enter). With two-step verification on, the page also asks for the 6-digit code from your phone.

After logging in, the panel opens the setup wizard while the server has never been played, and the home screen otherwise.

Forgot the password? Close the panel and run `restablecer_contrasena_panel.bat`.

## The menu

The bar at the top shows:

| Item | Goes to |
|---|---|
| **"Inicio"** (Home) | Start and stop the server, and the address for your friends |
| **"Jugadores"** (Players) | Who can join (the friends list) |
| **"Mundo"** (World) | Your worlds and their settings |
| **"Mods"** | Add, remove and update mods |
| **"Copias"** (Backups) | Backups of your world |
| **"Consola"** (Console) | What the server says, live |
| **"Problemas"** (Problems) | Why the server stopped or someone was disconnected |
| **"Ajustes"** (Settings) | Access, Discord, ranks and more |

"Problemas" and "Ajustes" sit under **"Más ▾"** (More). **"Personalizar el menú"** (Customize the menu), also under "Más", lets you choose which items go in the bar and which under "Más". The choice is kept in this browser only.

On the right, a pill shows the server state: **"Encendido"** (On), **"Apagado"** (Off), **"Encendiendo…"** (Starting) or **"Se cerró solo"** (Stopped by itself). **"Salir"** logs you out.

Throughout the panel, **"?"** buttons explain a control, and every action that cannot be undone asks first.

## First-time setup

The wizard (`/onboarding`) has four short steps and never deletes anything you already have. If the server is already on, it skips the steps and offers **"Ir al inicio"** (Go home) or **"Revisar cómo entran tus amigos"** (Check how your friends join). For a server that was already played, it shows a summary such as how many players joined and when it was last played.

1. **"Preparar tu computadora"** (Get your computer ready). **"Descargar Java"** downloads the Java that Minecraft needs into the panel's folder. Nothing is installed in Windows.
2. **"¿Cómo quieren jugar?"** (How do you want to play?). Choose:
   - **"Minecraft normal"**: no mods.
   - **"Con mods"** (With mods): NeoForge, the usual choice for modpacks.
   - **"Con mods livianos"** (With light mods): Fabric.
   - **"Ya tengo un servidor"** (I already have a server): copy it into the `server` folder and click **"Ya lo copié"** (Done).

   Pick the **"Versión de Minecraft"** (it must match the one your friends play), accept the EULA and click **"Instalar"** (Install). If that version needs a newer Java, the panel downloads it first.
3. **"¿Quién puede entrar?"** (Who can join?). Add your friends' Minecraft names; the first name turns the friends list on. Then set up how they reach you from their homes:
   - With the official Playit app, the panel detects it and can turn it on (**"Encender Playit"**) and read its address (**"Usar la dirección de mi Playit"**).
   - Without it, follow the download steps, or open **"Otras opciones"** (Other options) to link Playit from the panel or to choose **"Jugar solo en esta casa"** (Play only in this house).
4. **"¡Todo listo para jugar!"** (All set!). Choose the **"Memoria para el juego"** (Memory for the game) and click **"Encender"** (Start). The first start creates the world, and a backup is made right after.

## Inicio (Home)

- **The big button** changes with the state: **"Encender"** (Start), **"Reiniciar"** (Restart, with a chat warning and a 10-second countdown) or **"Volver a encender"** (Start again). Progress shows step by step under it, and **"Lo que está pasando"** (What is happening) lists anything still running, even after reloading the page.
- **"+"** opens more actions, each with a "?" explanation:
  - **"Reiniciar avisando a los jugadores"**: warn in the chat, wait 10 seconds and restart.
  - **"Apagar"** (Stop): save the world and stop.
  - **"Encender sin avisar en Discord"** (Start without the Discord notice): the header then shows **"Modo de prueba"** (Test mode).
  - **"Forzar cierre"** (Force close): only when "Apagar" does not respond; it does not save.
- **If a server is already open outside the panel** (for example from `run.bat`), a box explains how it was recognised. **"Cerrarlo desde acá"** (Close it from here) asks it to save and stop, like pressing Ctrl+C in its window, and forces it only if it does not stop within a minute.
- **"Hay una versión nueva del panel"** (A new panel version is out) appears at the top when GitHub has a newer release, with a link to what changed and how to update. **"Ahora no"** (Not now) hides it until the next version. Turn the check off with `check_updates = false` in [the settings file](SERVER_FILE.md).
- **"Jugando ahora"** (Playing now) lists who is in the game, with their skin's face and how many of the server's slots are used. It shows only while the server is on.
- **"Para que tus amigos entren"** (So your friends can join) shows the address to share, with **"Copiar"**. It comes from Playit, from what you wrote in the settings, or from a VPN found on this PC. Other VPN addresses appear below it ("También por Tailscale: …", also through Tailscale).
- **"Cosas para revisar"** (Things to check) warns about what needs attention: who can join, disk space, missing backups, a server open outside the panel, recent crashes, automatic restarts that stopped. Each warning has a link to fix it and **"Ocultar este aviso"** (Hide this notice). A hidden notice comes back if things get worse.
- **"Copias de tu mundo"** (Backups of your world): when the last backup was made, and **"Hacer una copia ahora"** (Back up now). Players can keep playing meanwhile.

## Consola (Console)

Everything the server writes, live. The badge says whether the page is connected; it reconnects by itself.

- **Tabs**: **"Todo"** (All), **"Errores y avisos"** (Errors and warnings) and **"Chat y jugadores"** (Chat and players). Errors are recognised by their real log level, not by the word "error".
- **Long errors are folded**: the lines of a Java error sit under it, behind **"Ver N líneas más"** (Show N more lines).
- **Repeated lines** in a row become one line with **"× N"**.
- **"Buscar"** (Search) highlights matches without hiding the rest. Move between them with ↑ ↓, Enter or Shift+Enter.
- **Reading old lines**: when you scroll up, the console stays put and **"N líneas nuevas ↓"** (N new lines) takes you back to the end. **"Pausar"** (Pause) stops following new lines even at the bottom.
- **Player names** can be clicked: **"Escribirle un mensaje"** (Message them), **"Ver por qué se desconectó"** (See why they disconnected), **"Copiar el nombre"** and **"Echarlo del servidor"** (Kick them).
- **Sending**: choose **"Comando"** (Command) or **"Chat"**. Chat sends your text to everyone in the game. ↑ ↓ bring back commands you already used. Commands that cannot be undone ask first: `stop`, `op`, `deop`, `ban`, `pardon`, `kill @e` without a type, `kill @a`, `whitelist off`, `save-off`, `fill` and `clone`.
- **"Atajos"** (Shortcuts): one click writes a common command, a double click sends it. "Medir el lag" and the other lag tools need the Spark mod; the Chunky ones need Chunky.
- **"Copiar"** copies the lines on screen, **"Descargar registro"** (Download log) saves the whole session log with players' addresses and your Windows user name hidden, ready to share when you ask for help. **"Limpiar"** (Clear) only clears the screen.

## Mods

See [MODS.md](MODS.md) for how mods are handled.

- **"Tus mods"** (Your mods): search, filter (**"Encendidos"** on, **"Apagados"** off, **"Solo del servidor"** server-only) and sort. Each mod has an on/off switch and **"Quitar"** (Remove). Select several to turn them on, off or remove them together; **"Elegir todos"** (Select all) picks every mod that matches the search.
- **"Agregar desde archivo"** (Add from file): drop one or more `.jar` files.
- **"Actualizaciones"** (Updates): appears when newer versions exist on Modrinth. **"Actualizar"** updates one mod and **"Actualizar todos"** updates them all. A newer version is not always better for your world, so read what changed first.
- **"Buscar mods nuevos"** (Find new mods): search Modrinth, showing only mods that work with your server. Required libraries are installed too.
- **"Paquete para tus amigos"** (Pack for your friends): **"Preparar paquete"** builds a ZIP with the mods your friends need, leaving out the server-only ones.
- **"Historial"** (History): the panel saves the state of your mods before every change. **"Volver a este punto"** (Go back to this point) undoes that change and every later one, and the undo itself can be undone too.

## Copias (Backups)

- **"Hacer una copia ahora"** (Back up now) copies the world; players can keep playing.
- Each backup in **"Tus copias"** (Your backups) can be restored, downloaded or deleted. **"Volver a esta copia"** (Restore this backup) stops the server and replaces the world. With **"También volver la configuración"** (Restore the settings too), it also brings back the extra files the backup included, never touching anything you protected.
- **"Último cierre inesperado"** (Last unexpected stop) explains the last crash, with the mod it suspects.
- **"Opciones avanzadas"** (Advanced options): **"Guardar el mundo en el disco ahora"** (Save the world to disk now), and **"Revisar copias y borrar las que sobran"** (Check backups and delete the extra ones). Damaged backups are never deleted automatically.

How often backups are made, how many are kept and where they go is set in **Ajustes → Tu servidor → Copias**.

## Mundo (World) and Jugadores (Players)

- **"Mundos"** (Worlds): every world in the server folder, with its size. **"Usar este mundo"** (Use this world) makes it the active one. **"Crear un mundo nuevo"** (Create a new world) asks for a name, an optional seed, game mode, difficulty, structures and hardcore.
- **"Jugadores"** (Players): the **"Lista de amigos"** (Friends list) switch and the names on it. With the list on, only those players can join.
- **"Lugares guardados"** (Saved places): bookmark coordinates. **"Llevar a todos"** (Take everyone there) teleports all players online.
- **"Ajustes"** (Settings): the `server.properties` editor, in plain words, with what is recommended and what each setting changes. Changes apply on the next start.
- **"Logros"** (Advancements): see a player's advancements, remove one, a branch or all of them, or give them all.

## Problemas (Problems)

Why the server stopped or why someone was disconnected, explained in plain words: kicked, banned, not on the friends list, game closed, connection lost, a mod error.

- Filter by player, by reason or by word. **"Ocultar las salidas normales"** (Hide normal exits) is on by default.
- Each event shows what happened, what to do, how long the player was on, and **"Qué estaba pasando"** (What was going on) just before.
- **"Ver el registro completo"** (See the full log) opens the log lines around the event. **"Copiar todo"** copies a report ready to share when you ask for help.
- **"Buscar problemas nuevos"** (Look for new problems) reads only what the server logged since the last check.

## Ajustes (Settings)

The settings page lists its sections like a phone's settings app. Each one opens as its own screen, with **"← Volver"** (Back).

### Tu servidor (Your server)

The settings in `server/craftpanel.txt`, in groups. Every key, with its default, is in [SERVER_FILE.md](SERVER_FILE.md). Invalid lines are listed at the top, and meanwhile the panel uses the defaults for them.

- **"Encender y apagar"** (Start and stop): the start script, Java, memory, starting with the panel and stopping when it closes, how long to wait for the world to load, starting again after a crash, a daily restart, and stopping when there are too few players.
- **"Copias"** (Backups): how often, how many, how much space, where, and what to leave out or add.
- **"Mods y amigos"** (Mods and friends): the server name, the address for your friends and the server-only mods.
- **"Protección"** (Protection): files and folders the panel must never touch, and words that help it recognise your server when you open it outside the panel.
- **"El archivo"** (The file): edit `craftpanel.txt` as text.

### Rangos y permisos (Ranks and permissions)

Ranks with LuckPerms: create a rank with its chat tag and colours, give a rank to a player, and choose what each rank can do (fly, teleport, change game mode and more), applied at once without restarting. See [LUCKPERMS_CONFIGURATION.md](LUCKPERMS_CONFIGURATION.md).

### Avisos en Discord (Discord notices)

A message in your Discord channel when the server starts or stops, crashes, a backup is made, or a player joins, leaves, dies or earns an advancement. Each message's text can be changed. The panel also detects a mod that links the game chat with Discord and helps you install and set it up. **"Cartel del servidor"** (Server banner) makes an image with the server's state. See [DISCORD_CONFIGURATION.md](DISCORD_CONFIGURATION.md).

### Reglas del servidor (Server rules)

- **"Objetos prohibidos"** (Banned items): items nobody can use (needs the Item Obliterator mod).
- **"Criaturas"** (Creatures): creatures that no longer appear.
- **"Aldeanos"** (Villagers): turn villager professions off.
- **"Herramientas de construcción"** (Building tools): turn WorldEdit on or off, when it is installed.

**"Aplicar ahora"** (Apply now) reloads the rules on a running server.

### Mods y mundo (Mods and world)

- **"Ajustes de los mods"** (Mod settings): find a mod's config file and change it in a form. On this PC, **"Abrir en el Bloc de notas"** (Open in Notepad) opens it in Notepad instead. The panel refuses to save over changes made elsewhere since you opened it.
- **"Reglas del juego"** (Game rules): keep inventory, mob griefing, the daylight cycle and the rest, applied live.
- **"Jugadores"**: players who already joined, with **"Mandar al inicio"** (Send to spawn) and **"Hacer admin"** (Make admin).
- **"Si anda lento"** (If it lags): measure for 30 seconds (needs Spark).

### Acceso por Internet (Internet access)

The current address for friends and **"Revisar el acceso"** (Check access), which opens the friends step of the wizard.

**"Por una VPN"** (Through a VPN): when you and your friends use the same VPN (Tailscale, ZeroTier, Radmin VPN, Hamachi, NetBird or WireGuard), the panel finds it and shows the address to play through it. **"Abrir el panel desde otra compu de la VPN"** (Open the panel from another computer on the VPN) lets you manage the server from your phone or laptop with your usual password. It can only be turned on from this PC and applies after restarting the panel. Turn on two-step verification first.

### Verificación en dos pasos (Two-step verification)

Besides the password, the login asks for a 6-digit code from an authenticator app on your phone. **"Activarla"** (Turn it on) shows a QR code to scan. Moving it to another phone or turning it off asks for a current code first.

## Closing the panel

The server runs on its own, apart from the panel, so a frozen or closed panel never freezes the game. What closing the panel does depends on **"Apagarlo al cerrar el panel"** (Stop it when the panel closes), in **Ajustes → Tu servidor → Encender y apagar**:

- **On (default)**: Ctrl+C in the panel's window, its close button or signing out of Windows all stop the server, saving the world first.
- **Off**: the server keeps running. When you open the panel again it takes the server back, with its console, commands and players, and says so in the console.

## Things that need the server off

These change files the running server is using, so the panel asks you to stop it first:

- Turning mods on or off, adding, removing or updating them, and going back in the mod history.
- Using, creating or deleting a world, and saving `server.properties`.
- Saving a mod's config file.
- Restoring a backup.
- Installing a server or changing its memory, its start script or its Java.

## The scripts in the main folder

| Script | What it does |
|---|---|
| `iniciar_panel.bat` | Starts the panel. Prepares Python and the panel the first time, then opens the browser. Keep its window open. |
| `restablecer_contrasena_panel.bat` | Sets a new panel password (or generates one) and signs out every session. Close the panel first. |
| `iniciar_tunel_panel.bat` | Optional: a temporary HTTPS link to reach the panel from outside your home, through Cloudflare. See [SECURITY.md](SECURITY.md) before using it. |
| `iniciar_panel.sh` | The same as `iniciar_panel.bat` for Linux and macOS (not tested; only Windows 10 and 11 are supported). |
