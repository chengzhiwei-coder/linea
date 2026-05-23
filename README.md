# Linea

Linea is Anton's personal realtime voice assistant with a lightweight calling UX.

V1 is server-first:

- `server/`: Python/FastAPI realtime voice relay and auth server.
- `ios/`: future native Swift lightweight client.
- `docs/ios-client-contract.md`: the v1 contract the iOS client should implement.

## Local development

Install `uv`, then run the server from the server package:

```bash
cd server
uv sync --extra dev
uv run linea-server
```

Defaults:

- server URL: `http://localhost:8787` on the development machine;
- health check: `GET /health` without authentication;
- authenticated check: `GET /auth/check` with `Authorization: Bearer <server-token>`;
- WebRTC call setup: `POST /webrtc/offer` with an SDP offer and bearer auth.

On startup, the server creates `server/data/linea.db` if needed and logs the server bearer token. Store that token locally; restarts print the same token again because the local SQLite database persists it with its hash.

## Documentation

- Server runbook and endpoint notes: `server/README.md`.
- iOS placeholder notes: `ios/README.md`.
- Detailed iOS setup, auth, call lifecycle, UI state machine, and ATS caveats: `docs/ios-client-contract.md`.

## Safety

V1 uses plain HTTP for local development only. Do not expose the v1 local HTTP server, its bearer token, or any xAI API key to the public internet.
