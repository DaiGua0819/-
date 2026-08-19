from fastapi import FastAPI

from xvi import __version__
from xvi.config import settings

app = FastAPI(title="XVI API", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/ready")
def ready() -> dict[str, str]:
    return {
        "status": "ready",
        "source_access_mode": settings.source_access_mode.value,
    }
