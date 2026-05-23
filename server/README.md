# Linea Server

Local-dev v1 server for Linea.

Run:

```bash
uv run linea-server
```

Defaults:

- host: `0.0.0.0`
- port: `8787`
- SQLite: `data/linea.db`

Security note: v1 uses plain HTTP for local development. Do not expose port `8787` to the public internet.
