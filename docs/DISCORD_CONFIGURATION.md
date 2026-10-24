# Configurable Discord alerts

The panel does not include a specific server's world names, player names, or webhooks. **"Ajustes" › "Avisos en Discord"** (Settings › Discord alerts) stores local preferences in `web_panel/.discord_config.json`, which is ignored by Git. You can also use the `MINECRAFT_DISCORD_*` variables in [`web_panel/.env.example`](../web_panel/.env.example) as initial values for an installation.

Screen preferences take precedence over environment variables. If a presentation field is empty, the panel uses its matching variable. This lets you publish the code without copying host data or secrets.

| Preference | Variable | Use |
| --- | --- | --- |
| Server name | `MINECRAFT_DISCORD_SERVER_NAME` | Alert footer. |
| Software/version | `MINECRAFT_DISCORD_SERVER_SOFTWARE_LABEL` | Status and startup alerts. |
| World | `MINECRAFT_DISCORD_WORLD_NAME` | Startup and ready alerts. |
| Test player | `MINECRAFT_DISCORD_TEST_PLAYER_NAME` | Feed test only. |
| Avatar template | `MINECRAFT_DISCORD_PLAYER_AVATAR_URL_TEMPLATE` | Must contain `{player_name}`; empty disables avatars. |

Never paste a webhook into documentation, issues, or commits. Testing a webhook from the UI sends a message; automated tests do not make network calls.

## Panel alerts vs. a chat bridge

The alerts above need no mod: the panel reads the server console and posts to the webhook.
Linking the game chat with Discord (messages both ways, a bot with commands) needs a server mod.
At the top of "Avisos en Discord" (Discord alerts) the panel checks for Simple Discord Link,
Mc2Discord or Discord Integration:

- None installed: it offers "Instalar desde el panel" (Install from the panel, which also installs
  required libraries) or a Modrinth link, plus the manual steps.
- Installed: it links to the mod's settings file, where the bot token goes. The panel never reads,
  stores or sends that token.

If both the panel and the mod announce server start, turn one of them off to avoid duplicates.

## Status banner

"Cartel del servidor" (Server banner) is a PNG served at `/api/server/banner.png`. Discord downloads
images itself, so a link only works when the panel is reachable from the internet. On a local panel
the UI offers "Descargar la imagen" (Download the image) instead.
