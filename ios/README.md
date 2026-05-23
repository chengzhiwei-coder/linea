# Linea iOS

Future native Swift client.

V1 client contract:

- setup screen accepts server URL and server bearer token;
- Save validates with `GET /auth/check`;
- main screen has one Start/Stop button;
- Start creates WebRTC offer and sends it to `POST /webrtc/offer`;
- Stop closes the WebRTC peer connection.
