# Linea Server

Local-dev v1 server for Linea.

## Run

```bash
uv sync --extra dev
uv run linea-server
```

Defaults:

- host: `0.0.0.0`
- port: `8787`
- local URL: `http://localhost:8787` from the same machine
- SQLite: `data/linea.db`

On startup the server initializes SQLite if needed and logs the server bearer token. Keep that plaintext token in your local password manager or development notes. The token and its hash are stored in SQLite so restarts can print the same token again.

If you want to rotate the local development token, stop the server, delete `data/linea.db`, and restart to generate a new database and token. Older hash-only development databases are migrated by generating and printing a replacement token.

## Authentication

Authenticated endpoints require:

```http
Authorization: Bearer <server-token>
```

Use `GET /auth/check` to validate a saved token. Missing, malformed, or invalid authorization returns `401 Unauthorized`.

## Endpoints

- `GET /health`: unauthenticated liveness check; returns `{"ok": true}`.
- `GET /internal/conversation-test`: unauthenticated internal HTML page for manual browser verification of the WebRTC conversation path. Open it from the same local server, paste the server bearer token into the page, and click **Start conversation**.
- `GET /auth/check`: bearer-auth validation; returns `{"ok": true}` when authorized.
- `POST /webrtc/offer`: bearer-auth WebRTC offer endpoint. The request body is an SDP offer, and the response includes an SDP answer and `call_id`. V1 allows one active call at a time; a second call attempt returns `409 Conflict`.

Example offer request shape:

```json
{
  "type": "offer",
  "sdp": "v=0..."
}
```

Example answer response shape:

```json
{
  "type": "answer",
  "sdp": "v=0...",
  "call_id": "..."
}
```

## xAI configuration

Set these in your local environment before starting real xAI calls:

- `XAI_API_KEY`: required server-side xAI API key. Never expose this to the iOS client.
- `XAI_REALTIME_URL`: optional, defaults to `wss://api.x.ai/v1/realtime`.
- `XAI_REALTIME_MODEL`: optional, defaults to `grok-voice-think-fast-1.0`.
- `XAI_REALTIME_VOICE`: optional, defaults to `eve`.

## Verification

Run from this directory:

```bash
uv run pytest -q
uv run ruff check .
```

## Safety

Security note: v1 uses plain HTTP for local development. Do not expose port `8787`, the server bearer token, or `XAI_API_KEY` to the public internet.
