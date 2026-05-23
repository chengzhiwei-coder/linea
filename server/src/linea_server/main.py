import logging

import uvicorn

from linea_server.app import create_app

HOST = "0.0.0.0"
PORT = 8787

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("Linea server startup host=%s port=%s", HOST, PORT)
    app = create_app()
    if app.state.initial_server_token is not None:
        logger.info("New Linea server token: %s", app.state.initial_server_token)
    try:
        uvicorn.run(app, host=HOST, port=PORT)
    finally:
        logger.info("Linea server shutdown")
