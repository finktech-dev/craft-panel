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
