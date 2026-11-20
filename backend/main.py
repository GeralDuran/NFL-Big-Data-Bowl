"""API de PocketClock AI. Ejecuta: .venv\\Scripts\\uvicorn backend.main:app --reload

Sirve backend/data_summary.json (generado con `python -m backend.precompute`).
"""
import json
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

SUMMARY_PATH = Path(__file__).resolve().parent / "data_summary.json"
DIST_DIR = Path(__file__).resolve().parent.parent / "dashboard" / "dist"

app = FastAPI(title="Hackathon NFL UNAM - PocketClock AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def _load() -> dict:
    if not SUMMARY_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="Falta backend/data_summary.json. Genera con: python -m backend.precompute",
        )
    return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/summary")
def summary() -> dict:
    """KPIs, rankings, matriz situacional y lista del Film Room (sin las trayectorias)."""
    return {k: v for k, v in _load().items() if k != "plays"}


@app.get("/api/play/{game_id}/{play_id}")
def play(game_id: int, play_id: int) -> dict:
    """Trayectorias cuadro por cuadro de una jugada del Film Room."""
    found = _load()["plays"].get(f"{game_id}_{play_id}")
    if found is None:
        raise HTTPException(status_code=404, detail="Jugada no incluida en el Film Room")
    return found


# --- Frontend compilado (dashboard/dist), servido en la misma URL y puerto que la API ---

if (DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str) -> FileResponse:
    """Archivos de dist/ si existen; si no, index.html (fallback de la SPA). /api/* desconocido es 404."""
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Ruta de API no encontrada")
    root = DIST_DIR.resolve()
    candidate = (root / full_path).resolve()
    if full_path and candidate.is_file() and root in candidate.parents:
        return FileResponse(candidate)
    index = root / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="Falta dashboard/dist. Genera con: npm run build (en dashboard/)")
    return FileResponse(index)
