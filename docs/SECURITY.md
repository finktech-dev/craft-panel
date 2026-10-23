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

**Passwords and sessions**

- The first-run password is random: 24 characters, generated with Python's `secrets`. It is shown only to a browser on the same PC, never through a tunnel, proxy or LAN address. You can replace it with `restablecer_contrasena_panel.bat` (at least 12 characters). Resetting it also signs out every open session.
- Passwords are compared in constant time.
- After 5 wrong attempts, an IP is locked out for 15 minutes.
- A global limit pauses remote logins if many IPs fail at once. The owner on the PC itself is never locked out.
- Optional TOTP 2FA works with any authenticator app. Each code is accepted only once.
- Sessions are signed `HttpOnly`, `SameSite=Strict` cookies. Each session gets a new id at login and expires after a fixed lifetime (8 hours by default).
- Logging out revokes the session, so a copied cookie stops working.
- Cookies get the `Secure` flag and responses get HSTS automatically whenever the panel is reached over HTTPS (Cloudflare tunnel or a reverse proxy).

**Cross-site attacks**

- Every state-changing request needs a per-session CSRF token and a same-origin `Origin`. The console WebSocket checks both as well.
- The `Host` header must be an IP address, `localhost`, a `*.trycloudflare.com` Quick Tunnel or a domain you list in `MINECRAFT_ALLOWED_HOSTS`. This blocks DNS rebinding.
- A strict Content Security Policy is sent. No external scripts are allowed, and the only external images are player heads (`mc-heads.net`) and Modrinth icons. The policy also sets `frame-ancestors 'none'` and `object-src 'none'`.
- Every non-static response is sent with `Cache-Control: no-store`.

**Files and archives**

- Backups, Java runtimes and uploaded mods are checked before anything is written. The checks reject `..`, absolute paths, drive letters, NTFS alternate data streams (`file:stream`), Windows device names (`CON`, `NUL`…), symlinks and special files.
- Extraction counts the real decompressed bytes and the compression ratio as it goes, to stop zip bombs.
- Uploads must really be ZIP/JAR files.
- Request bodies are size-limited while they stream: 1 MB for normal requests, 8 MB for config files, 1 GB for mods.

**Downloads**

- Downloads go only to an HTTPS allow-list, checked on every redirect: Modrinth, Mojang, Fabric, NeoForge, Adoptium, Playit and GitHub releases.
- Every download has a size cap.
- Where the source publishes a checksum, it is verified: Mojang SHA-1, Modrinth SHA-512, Adoptium SHA-256 and GitHub asset digests.
- Discord alerts are only sent to real `discord.com` webhook URLs.

**Input checks**

- `server.properties` edits cannot inject new lines.
- Player names, selectors and advancement ids are checked before they are put into commands.
- World and config paths must stay inside `server/`.

**Secrets**

- The password, session key, 2FA secret, Playit key and Discord config are stored in `web_panel/` and are ignored by Git.
- They are written atomically, with owner-only permissions where the operating system supports it.
- They are never returned by the API, except the Discord webhook, which only the logged-in administrator can see in its own settings page.

## If you expose the panel to the Internet

You usually don't need to: friends join the **Minecraft server** through Playit, not the panel. Publish the panel only if you need to manage the server while away from home.

1. **Use HTTPS, never a plain port forward.** Don't forward port `8080` on your router. Use a tunnel or a reverse proxy that adds HTTPS instead:
   - **Easiest:** create a Cloudflare Quick Tunnel. Use the panel's HTTPS link option if your version shows it; otherwise run `iniciar_tunel_panel.bat`, which needs `cloudflared` in `tools\` or installed on the system. You get a temporary `https://…trycloudflare.com` link that changes every time you restart it. Stop it when you are done.
   - **Your own domain:** put a reverse proxy (Caddy, nginx, a Cloudflare named tunnel…) in front of `http://127.0.0.1:8080`. Add your domain to `web_panel/.env`:

     ```
     MINECRAFT_ALLOWED_HOSTS=panel.example.com
     MINECRAFT_COOKIE_SECURE=true
     ```

     The proxy must keep the original `Host` header, or send it in `X-Forwarded-Host`, and it must set `X-Forwarded-Proto: https`.
2. **Turn on 2FA** before publishing the panel, and keep the authenticator on your phone. If your version of the panel does not show a 2FA option yet, keep the panel local.
3. **Use a strong, unique password.** The generated one is fine. If you change it, use a password manager and at least 16 characters, and don't reuse a password from another site.
4. **Keep the panel and Minecraft separate.** Minecraft uses its own port (25565, or the Playit address). The panel must never be published on the same address or port as the game. Players don't need the panel.
5. **Protect the Minecraft server itself:**
   - Keep `online-mode=true` so players must own a real Minecraft account.
   - Turn on the whitelist (`white-list=true`) and add only your friends.
   - Don't enable RCON or `enable-query` unless you know you need them.
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
| `GET /api/server/banner.png` | Status banner image | Online/offline, RAM in use and the public game address |
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
