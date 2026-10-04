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
5. Explain in the pull request what the code validates and what still needs manual verification.

This repository is released under the MIT License. Do not copy code from other panels without verifying license compatibility.
