from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Linea Server", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    return app
