# Demo without real data

`DemoProvider` exists to demonstrate the future UX without connecting to a server. It is static: it does not enumerate files, detect Java, start processes, or save credentials.

To use it from a development console:

```powershell
$env:PYTHONPATH = 'web_panel'
python -c "from app.providers.demo import DemoProvider; print(DemoProvider().descriptor.model_dump_json(indent=2))"
```

The output declares read-only capabilities only: runtime discovery, server observation, and backup observation. For a public demo, use this provider or synthetic fixtures; never use a copy of a real world or configuration.
