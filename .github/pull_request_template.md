## What this changes

<!-- One or two sentences: what a player or server owner notices. -->

## How it was checked

- [ ] `python -m pytest web_panel/tests`
- [ ] `node web_panel/tests/test_admin_js_regression.js` and `node web_panel/tests/test_console.js`
- [ ] `npm run build:css` in `web_panel/frontend` (only when templates or classes changed)
- [ ] Tried in the panel on Windows

## Before opening

- [ ] No secrets, worlds, backups, logs, player data or downloaded JARs.
- [ ] On-screen text is in plain Spanish; code comments and docs are in English.
