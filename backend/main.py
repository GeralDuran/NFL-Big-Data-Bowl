"""API de PocketClock AI. Ejecuta: .venv\\Scripts\\uvicorn backend.main:app --reload

Sirve backend/data_summary.json (generado con `python -m backend.precompute`).
"""
import json
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

SUMMARY_PATH = Path(__file__).resolve().parent / "data_summary.json"

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
