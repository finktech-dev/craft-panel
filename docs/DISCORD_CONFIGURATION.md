# Configurable Discord alerts

The panel does not include a specific server's world names, player names, or webhooks. **Administration > Discord** stores local preferences in `web_panel/.discord_config.json`, which is ignored by Git. You can also use the `MINECRAFT_DISCORD_*` variables in [`web_panel/.env.example`](../web_panel/.env.example) as initial values for an installation.

Screen preferences take precedence over environment variables. If a presentation field is empty, the panel uses its matching variable. This lets you publish the code without copying host data or secrets.

| Preference | Variable | Use |
| --- | --- | --- |
| Server name | `MINECRAFT_DISCORD_SERVER_NAME` | Alert footer. |
| Software/version | `MINECRAFT_DISCORD_SERVER_SOFTWARE_LABEL` | Status and startup alerts. |
| World | `MINECRAFT_DISCORD_WORLD_NAME` | Startup and ready alerts. |
| Test player | `MINECRAFT_DISCORD_TEST_PLAYER_NAME` | Feed test only. |
| Avatar template | `MINECRAFT_DISCORD_PLAYER_AVATAR_URL_TEMPLATE` | Must contain `{player_name}`; empty disables avatars. |

Never paste a webhook into documentation, issues, or commits. Testing a webhook from the UI sends a message; automated tests do not make network calls.
