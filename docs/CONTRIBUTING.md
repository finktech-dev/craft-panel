# Contributing

Thanks for helping make the panel easier for non-technical Minecraft hosts.

## Safety rules

- Do not add worlds, backups, player logs, UUIDs, IP addresses, tokens, PINs, or `.env` files to the repository.
- Do not change restore, deletion, or server-process behavior as part of a visual or provider-contract change.
- Every new provider must declare its capabilities and work without operating-system-specific paths or commands.
- Risky actions need a focused test and an explicit UX confirmation.

## Workflow

1. Start from a clean checkout and keep commits small.
2. Create or refresh the local environment: `python -m venv .venv`, then install dependencies with `python -m pip install -r requirements-dev.txt`.
3. Add or update tests for the affected contract.
4. Run focused tests without starting a real Minecraft server: `python -m pytest web_panel/tests`.
   - If you changed JavaScript, also run `node web_panel/tests/test_admin_js_regression.js` and `node web_panel/tests/test_console.js`.
   - If you changed templates or JavaScript classes, rebuild the stylesheet with `npm --prefix web_panel/frontend ci` (once) and `npm --prefix web_panel/frontend run build:css`, and commit `web_panel/static/css/tailwind.css`. CI fails when it is out of date.
5. Explain in the pull request what the code validates and what still needs manual verification.

## Releases

1. Set the new number in `VERSION` (for example `1.1.0`) in a pull request and merge it.
2. Tag that commit with the same number and push the tag: `git tag v1.1.0` and `git push origin v1.1.0`.
3. The **Release** workflow checks that the tag matches `VERSION`, builds `CraftPanel.zip` (the panel without tests, CI files or stylesheet sources) and publishes the release with notes on how to update. Panels that have `check_updates` on show the new version on their home screen within a day.

Use `MAJOR.MINOR.PATCH`: a patch for fixes, a minor version for new features, a major one only when updating needs extra steps.

## Language and translations

The panel interface is in Spanish (Rioplatense, "vos" form); documentation, code comments and config keys are in English. Help translating the interface into other languages (i18n) is very welcome.

## License

This repository is released under the MIT License. Do not copy code from other panels without verifying license compatibility.
