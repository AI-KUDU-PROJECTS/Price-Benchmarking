"""Marketing BFF. The React app may call only this HTTP surface."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from bff.routes import router
from competitors.hungerstation import config as hungerstation_config

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIST = ROOT / "frontend" / "dist"

app = FastAPI(
    title="Kudu Price Intelligence BFF",
    version="v1",
    description="Composition API for KUDU's menu baseline and competitor price monitoring.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    ],
    allow_origin_regex=r"http://(192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+):(5173|4173)",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.mount(
    "/hungerstation-images",
    StaticFiles(directory=hungerstation_config.IMAGE_DIR, check_dir=False),
    name="hungerstation-images",
)
app.mount(
    "/assets",
    StaticFiles(directory=FRONTEND_DIST / "assets", check_dir=False),
    name="frontend-assets",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str) -> FileResponse:
    """Serve Vite files and fall back to index.html for React routes."""
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")

    dist = FRONTEND_DIST.resolve()
    candidate = (dist / path).resolve()
    if candidate.is_file() and dist in candidate.parents:
        return FileResponse(candidate)

    index = dist / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=503, detail="Frontend build is unavailable")
    return FileResponse(index)
