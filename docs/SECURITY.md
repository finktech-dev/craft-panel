# Security

Craft Panel is a web panel that people run on their own PC to manage a Minecraft server. It is tested and supported on **Windows 10 and Windows 11**. Other operating systems may work, but they are not tested and not officially supported.

This document explains what the panel protects against, what it cannot protect against, and how to publish it safely if you want to reach it from outside your home.

## Threat model

**What we protect.** The panel can start and stop the server, run any console command, change files under `server/`, install mods, restore backups and delete worlds. Anyone who controls the panel controls the Minecraft server, and through it a good part of the PC. The panel password, the 2FA secret, the Playit agent key and Discord webhook URLs are secrets.

**Who we defend against.**

- **Internet visitors.** Someone who finds the panel through a port forward, a Cloudflare tunnel or a reverse proxy, but does not know the password.
- **Malicious websites** opened in the owner's browser while they are logged in. This covers CSRF, DNS rebinding against `127.0.0.1` and cross-site WebSockets.
- **Players.** They can type chat messages, choose names on offline-mode servers, and trigger death messages and log lines. All of that ends up in the panel.
- **Hostile files.** Mod JARs, backups and downloads that may be crafted to escape their folder (zip-slip), fill the disk (zip bombs) or carry links.
- **Compromised or spoofed download sources.** Redirects to local services (SSRF), oversized files, or files that do not match their published checksum.

**Out of scope.** We do not defend against:

- Someone who already has the panel password and 2FA, or who has a Windows account on the same PC.
- Malware on the PC.
- Malicious mods you choose to install. A mod is code that runs with the server's permissions.

The panel has a single administrator. There are no user roles.

## What the panel does for you

**Local by default**

- It listens on `127.0.0.1:8080` only. Nothing is reachable from other devices unless you deliberately publish it.
- **Opening it to a VPN** ("Ajustes" → "Acceso por Internet" → "Por una VPN", off by default) only adds the addresses of the mesh VPNs found when the panel starts (Tailscale, ZeroTier, Radmin VPN, Hamachi, NetBird, WireGuard). It never listens on `0.0.0.0`, so Wi-Fi and the home network still cannot reach it, and every request that is not from this PC must come from one of those VPN networks. Only a browser on this PC can turn it on or off, and the change applies after restarting the panel. It is not offered when the panel is published through a tunnel or proxy. The login, its rate limit and 2FA work the same; the first-run password is still shown only on this PC, and "Abrir" in Notepad stays local. Turn on 2FA before opening it: anyone on your VPN can see the login page.

**Passwords and sessions**

- The first-run password is random: 24 characters, generated with Python's `secrets`. It is shown only to a browser on the same PC, never through a tunnel, proxy or LAN address.
- The password is never stored in plain text. `web_panel/.panel_secrets.json` keeps only a salted scrypt hash (`admin_password_hash`, format `scrypt$<log2 N>$<r>$<p>$<salt>$<key>`, currently N = 2^15, r = 8, p = 1, a 16-byte random salt and a 32-byte key). The final comparison is constant-time.
- The generated first-run password lives only in the panel's memory, so the login page can show it. It is forgotten after the first successful login. If the panel is closed before anyone signs in with it, the next start generates and shows a new one (the file marks it with `admin_password_unclaimed`), so nobody gets locked out.
- Older versions stored the password in plain text (`admin_pin`). On startup the panel hashes it, removes the plain value and keeps the same password and open sessions.
- `MINECRAFT_ADMIN_PIN` still overrides the stored password. It is hashed in memory at startup and never written to disk.
- `restablecer_contrasena_panel.bat` replaces the password. Type one (at least 12 characters) or leave it empty to get a random one, which is printed once in that window. Only the hash is saved, and every open session is signed out.
- After 5 wrong attempts, an IP is locked out for 15 minutes.
- A global limit pauses remote logins if many IPs fail at once. The owner on the PC itself is never locked out.
- Optional TOTP 2FA works with any authenticator app. Turn it on in **"Ajustes" → "Verificación en dos pasos"** (Settings → Two-step verification): scan the QR code (or type the key by hand) and confirm with a 6-digit code. Each code is accepted only once, including the one used to confirm.
- Moving 2FA to another phone or turning it off needs a current code from the app, not just a session, so a stolen cookie cannot remove the second factor. Wrong codes count toward a lockout. If you lose the phone, delete `web_panel/.totp_secret` on the PC to turn 2FA off.
- Sessions are signed `HttpOnly`, `SameSite=Strict` cookies. Each session gets a new id at login and expires after a fixed lifetime (8 hours by default).
- Logging out revokes the session, so a copied cookie stops working.
- Cookies get the `Secure` flag and responses get HSTS automatically whenever the panel is reached over HTTPS (Cloudflare tunnel or a reverse proxy).

**Cross-site attacks**

- Every state-changing request needs a per-session CSRF token and a same-origin `Origin`. The console WebSocket checks both as well.
- The `Host` header must be an IP address, `localhost`, a `*.trycloudflare.com` Quick Tunnel or a domain you list in `MINECRAFT_ALLOWED_HOSTS`. This blocks DNS rebinding.
- A strict Content Security Policy is sent. Scripts only load from the panel's own `/static/js` files (`script-src 'self'`, without `'unsafe-inline'`): pages contain no inline scripts or `on…=` handlers, so injected markup cannot run code. No external scripts are allowed, and the only external images are player heads (`mc-heads.net`) and Modrinth icons. The policy also sets `frame-ancestors 'none'` and `object-src 'none'`.
- Every non-static response is sent with `Cache-Control: no-store`.

**Files and archives**

- Backups, Java runtimes and uploaded mods are checked before anything is written. The checks reject `..`, absolute paths, drive letters, NTFS alternate data streams (`file:stream`), Windows device names (`CON`, `NUL`…), symlinks and special files.
- Extraction counts the real decompressed bytes and the compression ratio as it goes, to stop zip bombs.
- Uploads must really be ZIP/JAR files.
- Request bodies are size-limited while they stream: 1 MB for normal requests, 8 MB for config files, 1 GB for mods.

**Downloads**

- Downloads go only to an HTTPS allow-list, checked on every redirect: Modrinth, Mojang, Fabric, NeoForge, Adoptium, Playit and GitHub releases. The one request that carries the official Playit app's key is limited to `api.playit.gg`.
- Every download has a size cap.
- Where the source publishes a checksum, it is verified: Mojang SHA-1, Modrinth SHA-512, Adoptium SHA-256 and GitHub asset digests.
- Discord alerts are only sent to real `discord.com` webhook URLs.

**Input checks**

- `server.properties` edits cannot inject new lines.
- Player names, selectors and advancement ids are checked before they are put into commands.
- World and config paths must stay inside `server/`.

**Secrets**

- The password hash, session key, 2FA secret, Playit key and Discord config are stored in `web_panel/` and are ignored by Git.
- They are written atomically, with owner-only permissions where the operating system supports it.
- They are never returned by the API, except the Discord webhook, which only the logged-in administrator can see in its own settings page.
- **RCON.** The server runs detached from the panel, so a restarted panel can take it back and still send commands. For that, before a start the panel turns RCON on in `server.properties` when it is off, with a random 32-character password (an RCON setup you already have is kept). The password is never shown: the properties editor hides it and refuses to change it. RCON listens on port `25575` on every network card of this PC, like the game port; Playit never forwards it. Don't forward `25575` on your router.
- API answers shown in the browser never include folders of this PC, the Windows user name or the machine name. Java is described by version, vendor and place ("Java 21 de Adoptium, en tu computadora", meaning "Java 21 from Adoptium, on your computer") and the start script by its file name. The console's **"Descargar registro"** (Download log) hides players' addresses and the Windows user name too.

**The official Playit app for Windows**

When the official Playit installer is used, its `playitd` Windows service holds its own agent key in `C:\ProgramData\playit_gg\playit.toml`. The panel works with it like this:

- **Detection** reads the service status with `psutil` (or `sc.exe` as a fallback) and checks whether `Program Files\playit_gg\bin` exists. It never reads the key for this.
- **Turning it on** runs the app's own `playit.exe start`. The Playit installer lets every signed-in user start and stop that service, so no administrator rights are needed and the panel never changes how the service starts. Making it start with Windows is left to the user, through Windows' *Services* tool.
- **"Usar la dirección de mi Playit"** (Use my Playit address) first asks the service's local status pipe (`\\.\pipe\playitd-system`) with the read-only `get_state` request. That needs no secret, and the panel never sends any other request on that pipe (the pipe also accepts `stop` and `reset_secret` from any local user).
- Only if the pipe does not answer, and only on that click, the panel reads the agent key from `playit.toml` and uses it in memory for **one** HTTPS request to `https://api.playit.gg/v1/agents/rundata` (an allow-listed host, no redirects). The key is never logged, saved, copied to `web_panel/`, returned by the API or shown. Errors are replaced by plain messages that never include it. The automatic lookup after "Encender" (Start) uses the pipe only and never reads the key.
- Only the Minecraft address is saved: in `public_address` of `server/craftpanel.txt` when that file exists, otherwise in the panel's own setting.

**Trade-off.** Reading `playit.toml` means the panel process can see a key that lets anyone run tunnels for that Playit account. The installer does not lock that file down, so it usually keeps the default `C:\ProgramData` permissions, which let every user of the PC read it; the panel gets no access the signed-in user did not already have. If Windows refuses to read it, the panel says so and offers the paste field. The risk is the panel's own: a bug that leaked the key would expose it. That is why the pipe is tried first, the key is only read after a click, and it is never written anywhere. If you prefer the panel never to touch it, paste the address yourself in **"Pegá la dirección que te muestra Playit"** (Paste the address Playit shows you). That field accepts only a host name or IP with an optional port.

## If you expose the panel to the Internet

You usually don't need to: friends join the **Minecraft server** through Playit, not the panel. Publish the panel only if you need to manage the server while away from home.

1. **Use HTTPS, never a plain port forward.** Don't forward port `8080` on your router. Use a tunnel or a reverse proxy that adds HTTPS instead:
   - **Easiest:** create a Cloudflare Quick Tunnel with `iniciar_tunel_panel.bat`, which needs `cloudflared` in `tools\` or installed on the system. You get a temporary `https://…trycloudflare.com` link that changes every time you restart it. Stop it when you are done.
   - **Your own domain:** put a reverse proxy (Caddy, nginx, a Cloudflare named tunnel…) in front of `http://127.0.0.1:8080`. Add your domain to `web_panel/.env`:

     ```
     MINECRAFT_ALLOWED_HOSTS=panel.example.com
     MINECRAFT_COOKIE_SECURE=true
     ```

     The proxy must keep the original `Host` header, or send it in `X-Forwarded-Host`, and it must set `X-Forwarded-Proto: https`.
2. **Turn on 2FA** (**"Ajustes" → "Verificación en dos pasos"**) before publishing the panel, and keep the authenticator on your phone.
3. **Use a strong, unique password.** The generated one is fine. If you change it, use a password manager and at least 16 characters, and don't reuse a password from another site.
4. **Keep the panel and Minecraft separate.** Minecraft uses its own port (25565, or the Playit address). The panel must never be published on the same address or port as the game. Players don't need the panel.
5. **Protect the Minecraft server itself:**
   - Keep `online-mode=true` so players must own a real Minecraft account.
   - Turn on the whitelist (`white-list=true`) and add only your friends.
   - Don't enable `enable-query` unless you know you need it, and never forward the RCON port (`25575`).
   - Remember that anyone you make **op** can run commands in the game.
6. **Close it when you don't need it.** Stop the tunnel, and log out on shared computers.
7. **Keep things updated.** Pull new versions of the panel; the launcher upgrades the Python dependencies. Keep Java and your mods up to date too.

## Public endpoints

Everything under `/api` and `/ws` requires an administrator session, except these. They reveal nothing secret:

| Endpoint | Purpose | What it reveals |
| --- | --- | --- |
| `GET /` | Login page (the dashboard once logged in) | Nothing. The first-run password appears only on the same PC. |
| `GET /health` | Liveness probe used by the launcher | `ok` and the server state (running/stopped) |
| `GET /api/public/status` | Status for a public page | Online/offline, state and the public **game** address |
| `GET /api/server/banner.png` | Status banner image | Online/offline, the server name, its software and version, RAM in use and its limit, and the public game address |
| `POST /api/auth/login` | Sign in | Nothing (rate-limited) |
| `POST /api/auth/logout` | Sign out | Nothing |
| `GET /api/auth/2fa/status` | Login form shows the 2FA field | Whether 2FA is enabled |
| `GET /static/*` | CSS, JS, images | Public front-end files only |

The interactive API docs (`/docs`, `/openapi.json`) are disabled.

## Reporting a vulnerability

Please report security problems **privately**. Use GitHub's **Security → Report a vulnerability** page on this repository. Don't open a public issue.

Include:

- the panel version or commit
- what an attacker can do
- steps to reproduce

Don't include real player data, IP addresses or secrets. We will acknowledge the report, work on a fix and credit you if you want. Please give us reasonable time to release a fix before you disclose it publicly.
