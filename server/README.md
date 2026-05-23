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

## xAI configuration

Set these in your local environment before starting real xAI calls:

- `XAI_API_KEY`: required server-side xAI API key. Never expose this to the iOS client.
- `XAI_REALTIME_URL`: optional, defaults to `wss://api.x.ai/v1/realtime`.
- `XAI_REALTIME_MODEL`: optional, defaults to `grok-voice-think-fast-1.0`.
- `XAI_REALTIME_VOICE`: optional, defaults to `eve`.
