"""Pruebas rápidas de la API. Ejecuta desde la raíz: .venv\\Scripts\\python.exe -m pytest backend"""
import pytest
from fastapi.testclient import TestClient

from backend.main import DIST_DIR, app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_summary_estructura():
    r = client.get("/api/summary")
    assert r.status_code == 200
    data = r.json()
    assert {"meta", "kpis", "rankings", "matrix", "film_room"} <= data.keys()
    assert "plays" not in data  # las trayectorias van por /api/play
    assert data["kpis"]["n_games"] == 122
    assert len(data["film_room"]) == 20
    assert len(data["rankings"]["teams_offense"]) == 15


def test_play_film_room():
    item = client.get("/api/summary").json()["film_room"][0]
    r = client.get(f"/api/play/{item['game_id']}/{item['play_id']}")
    assert r.status_code == 200
    play = r.json()
    assert len(play["players"]) == 22
    assert play["ball"] is not None
    n = len(play["clock"])
    assert n > 0 and play["clock"][0] == 0
    assert all(len(p["x"]) == n and len(p["y"]) == n and len(p["o"]) == n for p in play["players"])
    assert {"name", "jersey", "position", "role", "team"} <= play["players"][0].keys()


def test_play_inexistente():
    assert client.get("/api/play/1/2").status_code == 404


def test_api_desconocida_no_cae_en_la_spa():
    assert client.get("/api/no-existe").status_code == 404


def test_cors():
    r = client.get("/api/summary", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "*"


@pytest.mark.skipif(not (DIST_DIR / "index.html").exists(), reason="dashboard/dist no está compilado")
def test_sirve_frontend_compilado():
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert client.get("/ruta/cualquiera").status_code == 200  # fallback de la SPA
    asset = next((DIST_DIR / "assets").glob("*.js"))
    assert client.get(f"/assets/{asset.name}").status_code == 200
