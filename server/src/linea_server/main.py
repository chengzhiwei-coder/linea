import uvicorn

from linea_server.app import create_app

HOST = "0.0.0.0"
PORT = 8787


def main() -> None:
    uvicorn.run(create_app(), host=HOST, port=PORT)
