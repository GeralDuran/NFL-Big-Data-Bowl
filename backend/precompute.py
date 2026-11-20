"""Preprocesamiento de PocketClock AI.

Lee los CSV crudos (fuera del repo), normaliza el tracking, calcula TTT / PCT / TWS / PSI por
jugada y genera backend/data_summary.json. Solo usa pandas, numpy y la librería estándar.

Uso: .venv\\Scripts\\python.exe -m backend.precompute
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

# --- Rutas -----------------------------------------------------------------

DEFAULT_DATA_DIR = Path(r"C:\Users\user\Desktop\data")
REPO_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

FIELD_LENGTH = 120.0
FIELD_WIDTH = 53.3

_TRACKING_RE = re.compile(r"^tracking_(\d+)\.csv$")


def get_data_dir() -> Path:
    """DATA_DIR (variable de entorno) > ruta local del equipo > data/ del repo."""
    env = os.environ.get("DATA_DIR")
    for candidate in (Path(env) if env else None, DEFAULT_DATA_DIR, REPO_DATA_DIR):
        if candidate is not None and (candidate / "plays.csv").exists():
            return candidate
    raise FileNotFoundError(
        "No se encontró plays.csv. Define DATA_DIR o coloca los CSV en "
        f"{DEFAULT_DATA_DIR} o {REPO_DATA_DIR}."
    )


def find_tracking_files(data_dir: Path) -> dict[int, Path]:
    """Detecta tracking_[gameId].csv en data_dir/tracking/ o directo en data_dir/."""
    for folder in (data_dir / "tracking", data_dir):
        files = {
            int(m.group(1)): p
            for p in folder.glob("tracking_*.csv")
            if (m := _TRACKING_RE.match(p.name))
        }
        if files:
            return dict(sorted(files.items()))
    raise FileNotFoundError(f"No hay archivos tracking_*.csv en {data_dir} ni en {data_dir / 'tracking'}.")


# --- Lectura ---------------------------------------------------------------

GAMES_COLS = ["gameId", "week", "homeTeamAbbr", "visitorTeamAbbr"]
PLAYS_COLS = [
    "gameId", "playId", "quarter", "down", "yardsToGo", "possessionTeam", "defensiveTeam",
    "passResult", "dropBackType", "pff_playAction", "pff_passCoverage", "pff_passCoverageType",
    "offenseFormation", "playDescription", "playResult",
]
PLAYERS_COLS = ["nflId", "displayName", "officialPosition"]
PFF_COLS = [
    "gameId", "playId", "nflId", "pff_role", "pff_positionLinedUp",
    "pff_hit", "pff_hurry", "pff_sack", "pff_beatenByDefender",
    "pff_hitAllowed", "pff_hurryAllowed", "pff_sackAllowed",
    "pff_nflIdBlockedPlayer", "pff_blockType",
]
TRACKING_COLS = [
    "gameId", "playId", "nflId", "frameId", "team", "playDirection",
    "x", "y", "s", "a", "o", "dir", "event", "jerseyNumber",
]
TRACKING_DTYPES = {
    "jerseyNumber": "float32",
    "gameId": "int32", "playId": "int32", "frameId": "int16",
    "x": "float32", "y": "float32", "s": "float32", "a": "float32",
    "o": "float32", "dir": "float32",
    "team": "category", "playDirection": "category",
}


def load_tables(data_dir: Path) -> dict[str, pd.DataFrame]:
    """Carga las tablas pequeñas (games, plays, players, PFF)."""
    return {
        "games": pd.read_csv(data_dir / "games.csv", usecols=GAMES_COLS),
        "plays": pd.read_csv(data_dir / "plays.csv", usecols=PLAYS_COLS),
        "players": pd.read_csv(data_dir / "players.csv", usecols=PLAYERS_COLS),
        "pff": pd.read_csv(data_dir / "pffScoutingData.csv", usecols=PFF_COLS),
    }


def read_tracking(path: Path) -> pd.DataFrame:
    """Lee un tracking_[gameId].csv solo con las columnas necesarias.

    nflId queda como NaN en las filas del balón. El texto 'None' de `event` pasa a NaN.
    """
    return pd.read_csv(
        path,
        usecols=TRACKING_COLS,
        dtype=TRACKING_DTYPES,
        na_values={"event": ["None"]},
    )


# --- Normalización espacial ------------------------------------------------

def normalize_direction(df: pd.DataFrame) -> pd.DataFrame:
    """Hace que el ataque avance siempre hacia la derecha (vectorizado).

    Para playDirection == 'left': x = 120 - x, y = 53.3 - y, o y dir = (ángulo + 180) % 360.
    Modifica y devuelve df. Los NaN (p. ej. o/dir del balón) se conservan.
    """
    left = (df["playDirection"] == "left").to_numpy()
    if left.any():
        df.loc[left, "x"] = np.float32(FIELD_LENGTH) - df.loc[left, "x"]
        df.loc[left, "y"] = np.float32(FIELD_WIDTH) - df.loc[left, "y"]
        for col in ("o", "dir"):
            df.loc[left, col] = (df.loc[left, col] + np.float32(180.0)) % np.float32(360.0)
    df["playDirection"] = pd.Categorical(["right"] * len(df), categories=["right", "left"])
    return df


def load_normalized_tracking(path: Path) -> pd.DataFrame:
    return normalize_direction(read_tracking(path))



# --- Métricas por jugada: TTT, PCT, TWS, PSI ---------------------------------

FRAMES_PER_SECOND = 10.0
PRESSURE_RADIUS = 2.5  # yardas entre un Pass rush y el QB
# pff_role se compara en minúsculas: en los CSV reales aparece "Pass Rush", "Pass Route", etc.
KEY_ROLES = ("pass", "pass rush", "pass route", "coverage")

METRIC_COLS = [
    "gameId", "playId", "snap_frame", "pass_frame", "ttt", "pct", "pressure_reached",
    "min_qb_dist", "tws_mean", "tws_max", "n_receivers", "psi",
]


def _first_frame(ev: pd.DataFrame, names: list[str]) -> pd.Series:
    return ev[ev["event"].isin(names)].groupby("playId")["frameId"].min()


def event_frames(trk: pd.DataFrame) -> pd.DataFrame:
    """Frame de ball_snap y pass_forward por jugada.

    Si falta el evento principal se usa su versión autoevent_*. Se descartan las jugadas sin
    ambos eventos (p. ej. sacks sin pase) o con pass_forward antes del snap.
    """
    ev = trk.loc[trk["event"].notna(), ["playId", "frameId", "event"]]
    snap = _first_frame(ev, ["ball_snap"]).combine_first(_first_frame(ev, ["autoevent_ballsnap"]))
    thrw = _first_frame(ev, ["pass_forward"]).combine_first(_first_frame(ev, ["autoevent_passforward"]))
    out = pd.DataFrame({"snap_frame": snap, "pass_frame": thrw}).dropna()
    return out[out["pass_frame"] > out["snap_frame"]].astype("int32")


def compute_game(trk: pd.DataFrame, pff_game: pd.DataFrame):
    """Métricas de un partido (trk ya normalizado).

    Devuelve (jugadas, rushers, receptores):
      - jugadas: una fila por jugada de pase (TTT, PCT, TWS, PSI).
      - rushers: una fila por (jugada, Pass Rush) con PCT individual y velocidad de cierre.
      - receptores: una fila por (jugada, Pass Route) con su separación en pass_forward.
    """
    empty = (pd.DataFrame(columns=METRIC_COLS), pd.DataFrame(), pd.DataFrame())
    frames = event_frames(trk)
    if frames.empty:
        return empty

    roles = (
        pff_game.assign(pff_role=pff_game["pff_role"].str.lower())
        .loc[lambda r: r["pff_role"].isin(KEY_ROLES), ["playId", "nflId", "pff_role"]]
        .drop_duplicates(["playId", "nflId"])
    )
    pts = trk.dropna(subset=["nflId"]).merge(roles, on=["playId", "nflId"], how="inner")
    pts = pts.merge(frames, left_on="playId", right_index=True, how="inner")
    pts = pts[["playId", "nflId", "frameId", "x", "y", "pff_role", "snap_frame", "pass_frame"]]

    out = frames.copy()
    out["ttt"] = (out["pass_frame"] - out["snap_frame"]) / FRAMES_PER_SECOND

    # PCT: primer frame entre snap y pase en que algún Pass rush queda a < 2.5 yd del QB.
    win = pts[(pts["frameId"] >= pts["snap_frame"]) & (pts["frameId"] <= pts["pass_frame"])]
    qb = (
        win.loc[win["pff_role"] == "pass", ["playId", "frameId", "x", "y"]]
        .drop_duplicates(["playId", "frameId"])
        .rename(columns={"x": "qx", "y": "qy"})
    )
    rush = win.loc[win["pff_role"] == "pass rush", ["playId", "nflId", "frameId", "x", "y", "snap_frame"]]
    d = rush.merge(qb, on=["playId", "frameId"], how="inner")
    d["dist"] = np.hypot(d["x"] - d["qx"], d["y"] - d["qy"])
    out["min_qb_dist"] = d.groupby("playId")["dist"].min()
    cross = d.loc[d["dist"] < PRESSURE_RADIUS].groupby("playId")["frameId"].min()
    out["pressure_reached"] = out.index.isin(cross.index)
    pct = (cross - out["snap_frame"].reindex(cross.index)) / FRAMES_PER_SECOND
    out["pct"] = pct.reindex(out.index).fillna(out["ttt"])

    # Por rusher: PCT individual y velocidad de cierre = (dist en snap - dist mínima) / tiempo al mínimo.
    key = ["playId", "nflId"]
    at_min = d.loc[d.groupby(key)["dist"].idxmin()].set_index(key)
    rt = pd.DataFrame({"min_dist": at_min["dist"], "f_min": at_min["frameId"], "snap_frame": at_min["snap_frame"]})
    rt["d_snap"] = d[d["frameId"] == d["snap_frame"]].set_index(key)["dist"]
    rt["f_cross"] = d[d["dist"] < PRESSURE_RADIUS].groupby(key)["frameId"].min()
    rt = rt.reset_index().merge(out[["ttt"]], left_on="playId", right_index=True)
    rt["reached"] = rt["f_cross"].notna()
    rt["pct_ind"] = ((rt["f_cross"] - rt["snap_frame"]) / FRAMES_PER_SECOND).fillna(rt["ttt"])
    t_min = (rt["f_min"] - rt["snap_frame"]) / FRAMES_PER_SECOND
    rt["closing_speed"] = (rt["d_snap"] - rt["min_dist"]) / t_min.where(t_min > 0)
    rt = rt[["playId", "nflId", "min_dist", "pct_ind", "reached", "closing_speed"]]

    # TWS: separación de cada receptor con su Coverage más cercano en el frame pass_forward.
    at_pass = pts[pts["frameId"] == pts["pass_frame"]]
    route = at_pass.loc[at_pass["pff_role"] == "pass route", ["playId", "nflId", "x", "y"]]
    cov = at_pass.loc[at_pass["pff_role"] == "coverage", ["playId", "x", "y"]]
    pair = route.merge(cov, on="playId", suffixes=("", "_d"))
    pair["dist"] = np.hypot(pair["x"] - pair["x_d"], pair["y"] - pair["y_d"])
    sep = pair.groupby(key)["dist"].min()
    by_play = sep.groupby("playId")
    out["tws_mean"] = by_play.mean()
    out["tws_max"] = by_play.max()
    out["n_receivers"] = by_play.size().reindex(out.index).fillna(0).astype("int16")

    # PSI = TWS_max / PCT (NaN si PCT <= 0 o no hay separación calculable).
    out["psi"] = (out["tws_max"] / out["pct"].where(out["pct"] > 0)).astype("float64")

    rc = sep.rename("sep").reset_index().merge(out[["pct"]], left_on="playId", right_index=True)
    rc["psi"] = rc["sep"] / rc["pct"].where(rc["pct"] > 0)
    rc = rc[["playId", "nflId", "sep", "psi"]]

    out = out.reset_index(names="playId")
    gid = int(trk["gameId"].iloc[0])
    out.insert(0, "gameId", gid)
    rt.insert(0, "gameId", gid)
    rc.insert(0, "gameId", gid)
    return out[METRIC_COLS], rt, rc


def compute_all(data_dir: Path, pff: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Calcula las métricas de las jugadas de pase de los 122 partidos."""
    pff_by_game = {g: df[["playId", "nflId", "pff_role"]] for g, df in pff.groupby("gameId")}
    parts = ([], [], [])
    for game_id, path in find_tracking_files(data_dir).items():
        if game_id not in pff_by_game:
            continue
        for bucket, part in zip(parts, compute_game(load_normalized_tracking(path), pff_by_game[game_id])):
            bucket.append(part)
    metrics, rushers, receivers = (pd.concat(p, ignore_index=True) for p in parts)
    for t in (rushers, receivers):
        t["nflId"] = t["nflId"].astype("int64")
    return {"metrics": metrics, "rushers": rushers, "receivers": receivers}


# --- Agregados para data_summary.json ---------------------------------------

SUMMARY_PATH = Path(__file__).resolve().parent / "data_summary.json"
MAX_SUMMARY_BYTES = 5 * 1024 * 1024

TOP_N = 15
MIN_OL_SNAPS = 150
MIN_RUSHES = 60
MIN_ROUTES = 60
OL_POSITIONS = {"LT", "LG", "C", "RG", "RT"}
DIST_ORDER = ["Corto: 1-3", "Medio: 4-7", "Largo: 8+"]
PLAY_KEY = ["gameId", "playId"]


def distance_bucket(yards_to_go: pd.Series) -> pd.Series:
    labels = np.select([yards_to_go <= 3, yards_to_go <= 7], DIST_ORDER[:2], DIST_ORDER[2])
    return pd.Series(pd.Categorical(labels, categories=DIST_ORDER, ordered=True), index=yards_to_go.index)


def prepare_blockers(pff: pd.DataFrame) -> pd.DataFrame:
    blk = pff[pff["pff_role"].str.lower() == "pass block"].copy()
    allowed = blk[["pff_hitAllowed", "pff_hurryAllowed", "pff_sackAllowed"]].fillna(0).sum(axis=1)
    blk["blocker_pressure"] = (allowed > 0).astype("float64")
    blk["beaten"] = (blk["pff_beatenByDefender"].fillna(0) > 0).astype("float64")
    return blk


def build_full(plays: pd.DataFrame, metrics: pd.DataFrame, blk: pd.DataFrame, psi_cap: float) -> pd.DataFrame:
    """Una fila por dropback (plays.csv) con las métricas de tracking cuando existen."""
    play_pressure = blk.groupby(PLAY_KEY)["blocker_pressure"].max().rename("pressure_allowed")
    full = (
        plays.merge(metrics, on=PLAY_KEY, how="left")
        .merge(play_pressure, on=PLAY_KEY, how="left")
    )
    full["pressure_reached"] = full["pressure_reached"].astype("float64")
    full["psi_w"] = full["psi"].clip(upper=psi_cap)
    full["dist_bucket"] = distance_bucket(full["yardsToGo"])
    full["is_c"] = (full["passResult"] == "C").astype("float64")
    full["is_s"] = (full["passResult"] == "S").astype("float64")
    return full


def agg_table(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Métricas agregadas por grupo. Las % están en escala 0-100."""
    work = df.assign(_all=1) if not keys else df
    t = (
        work.groupby(keys or ["_all"], observed=True)
        .agg(
            n=("playId", "size"),
            n_tracked=("ttt", "count"),
            play_result=("playResult", "mean"),
            complete_pct=("is_c", "mean"),
            sack_pct=("is_s", "mean"),
            pressure_allowed_pct=("pressure_allowed", "mean"),
            pressure_reached_pct=("pressure_reached", "mean"),
            ttt=("ttt", "mean"),
            pct=("pct", "mean"),
            tws_mean=("tws_mean", "mean"),
            tws_max=("tws_max", "mean"),
            psi=("psi_w", "mean"),
        )
        .reset_index()
    )
    for c in ("complete_pct", "sack_pct", "pressure_allowed_pct", "pressure_reached_pct"):
        t[c] *= 100
    return t.drop(columns="_all", errors="ignore")


def records(t: pd.DataFrame) -> list[dict]:
    return clean(t.to_dict("records"))


def clean(obj):
    """Convierte a tipos JSON: NaN/inf -> None, numpy -> Python, floats a 3 decimales."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return clean(obj.tolist())
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return None if not np.isfinite(obj) else round(float(obj), 3)
    if obj is None or obj is pd.NaT or (not isinstance(obj, str) and pd.isna(obj)):
        return None
    return obj if isinstance(obj, str) else str(obj)


def mode_by(df: pd.DataFrame, col: str) -> pd.Series:
    """Valor más frecuente de `col` por nflId."""
    return df.groupby("nflId")[col].agg(lambda s: s.mode().iat[0] if s.notna().any() else None)


def with_names(t: pd.DataFrame, players: pd.DataFrame) -> pd.DataFrame:
    p = players.set_index("nflId")
    t = t.copy()
    t.insert(1, "name", t["nflId"].map(p["displayName"]))
    if "position" not in t.columns:  # los linieros ya traen la posición alineada según PFF
        t.insert(2, "position", t["nflId"].map(p["officialPosition"]))
    return t


def build_matrix(full: pd.DataFrame, blk: pd.DataFrame) -> dict:
    base = full[full["down"].between(1, 4)]

    def one(df: pd.DataFrame, col: str, sort_n: bool = True) -> list[dict]:
        t = agg_table(df, [col]).rename(columns={col: "value"})
        if sort_n:
            t = t.sort_values("n", ascending=False)
        return records(t)

    bt = blk[blk["pff_blockType"].notna()].merge(
        full[PLAY_KEY + ["playResult", "is_c", "is_s", "ttt", "pct", "tws_mean", "tws_max", "psi_w", "pressure_reached"]],
        on=PLAY_KEY,
    )
    bt["pressure_allowed"] = bt["blocker_pressure"]  # a nivel bloqueador
    bt_t = agg_table(bt, ["pff_blockType"]).rename(columns={"pff_blockType": "value"})
    bt_t["beaten_pct"] = bt.groupby("pff_blockType")["beaten"].mean().reindex(bt_t["value"]).to_numpy() * 100
    bt_t = bt_t.sort_values("n", ascending=False)

    return {
        "down": one(base, "down", sort_n=False),
        "distance": one(base, "dist_bucket", sort_n=False),
        "coverage_type": one(full, "pff_passCoverageType"),
        "coverage": one(full, "pff_passCoverage"),
        "formation": one(full, "offenseFormation"),
        "play_action": one(full, "pff_playAction", sort_n=False),
        "block_type": records(bt_t),
        "down_distance": records(
            agg_table(base, ["down", "dist_bucket"]).rename(columns={"dist_bucket": "distance"})
        ),
        "down_distance_coverage": records(
            agg_table(base, ["down", "dist_bucket", "pff_passCoverageType"]).rename(
                columns={"dist_bucket": "distance", "pff_passCoverageType": "coverage_type"}
            )
        ),
    }


def build_rankings(full: pd.DataFrame, blk: pd.DataFrame, pff: pd.DataFrame, tables: dict, players: pd.DataFrame,
                   psi_cap: float) -> dict:
    team_cols = ["possessionTeam", "n", "n_tracked", "sack_pct", "pressure_allowed_pct", "pct", "tws_max", "psi"]
    teams = (
        agg_table(full, ["possessionTeam"]).sort_values("psi", ascending=False).head(TOP_N)[team_cols]
        .rename(columns={"possessionTeam": "team"})
    )

    ol = blk[blk["pff_positionLinedUp"].isin(OL_POSITIONS)].merge(
        full[PLAY_KEY + ["pct", "possessionTeam"]], on=PLAY_KEY
    )
    g = ol.groupby("nflId")
    ol_t = pd.DataFrame({
        "snaps": g.size(),
        "pressure_allowed_pct": g["blocker_pressure"].mean() * 100,
        "beaten_pct": g["beaten"].mean() * 100,
        "pct": g["pct"].mean(),
    })
    ol_t["position"] = mode_by(ol, "pff_positionLinedUp")
    ol_t["team"] = mode_by(ol, "possessionTeam")
    ol_t = ol_t[ol_t["snaps"] >= MIN_OL_SNAPS]
    ol_t["score"] = ol_t["pressure_allowed_pct"].rank() + ol_t["pct"].rank(ascending=False)
    ol_t = ol_t.sort_values(["score", "pressure_allowed_pct"]).head(TOP_N).reset_index()

    rp = pff[pff["pff_role"].str.lower() == "pass rush"].merge(full[PLAY_KEY + ["defensiveTeam"]], on=PLAY_KEY)
    rt = tables["rushers"]
    g = rt.groupby("nflId")
    rush_t = pd.DataFrame({
        "rushes": g.size(),
        "pct": g["pct_ind"].mean(),
        "reach_pct": g["reached"].mean() * 100,
        "closing_speed": g["closing_speed"].mean(),
        "min_dist": g["min_dist"].mean(),
    })
    pff_sums = rp.groupby("nflId")[["pff_hit", "pff_hurry", "pff_sack"]].sum()
    rush_t = rush_t.join(pff_sums.rename(columns={"pff_hit": "hits", "pff_hurry": "hurries", "pff_sack": "sacks"}))
    rush_t["team"] = mode_by(rp, "defensiveTeam")
    rush_t = rush_t[rush_t["rushes"] >= MIN_RUSHES]
    rush_by_pct = rush_t.sort_values("pct").head(TOP_N).reset_index()
    rush_by_speed = rush_t.sort_values("closing_speed", ascending=False).head(TOP_N).reset_index()

    rc = tables["receivers"].merge(full[PLAY_KEY + ["possessionTeam"]], on=PLAY_KEY)
    g = rc.groupby("nflId")
    rec_t = pd.DataFrame({
        "routes": g.size(),
        "tws": g["sep"].mean(),
        "psi": g["psi"].apply(lambda s: s.clip(upper=psi_cap).mean()),
    })
    rec_t["team"] = mode_by(rc, "possessionTeam")
    rec_t = rec_t[rec_t["routes"] >= MIN_ROUTES]
    rec_t["position"] = players.set_index("nflId")["officialPosition"].reindex(rec_t.index).to_numpy()

    def top_receivers(t: pd.DataFrame) -> pd.DataFrame:
        t = t.assign(score=t["tws"].rank(ascending=False) + t["psi"].rank(ascending=False))
        return t.sort_values(["score", "tws"], ascending=[True, False]).head(TOP_N).reset_index()

    rec_all = top_receivers(rec_t)
    rec_wr_te = top_receivers(rec_t[rec_t["position"].isin(["WR", "TE"])])

    return {
        "min_samples": {"ol_snaps": MIN_OL_SNAPS, "rushes": MIN_RUSHES, "routes": MIN_ROUTES},
        "teams_offense": records(teams),
        "blockers": records(with_names(ol_t, players)),
        "rushers_by_pct": records(with_names(rush_by_pct, players)),
        "rushers_by_closing_speed": records(with_names(rush_by_speed, players)),
        "receivers": records(with_names(rec_all, players)),
        "receivers_wr_te": records(with_names(rec_wr_te, players)),
    }


def build_kpis(full: pd.DataFrame, metrics: pd.DataFrame, n_games: int, psi_cap: float) -> dict:
    tr = full[full["ttt"].notna()]
    return clean({
        "n_games": n_games,
        "n_dropbacks": len(full),
        "n_tracked_plays": len(tr),
        "ttt_mean": tr["ttt"].mean(), "ttt_median": tr["ttt"].median(),
        "pct_mean": tr["pct"].mean(), "pct_median": tr["pct"].median(),
        "min_qb_dist_mean": tr["min_qb_dist"].mean(),
        "pressure_reached_pct": tr["pressure_reached"].mean() * 100,
        "tws_mean_avg": tr["tws_mean"].mean(), "tws_max_avg": tr["tws_max"].mean(),
        "psi_mean": tr["psi_w"].mean(), "psi_median": tr["psi"].median(), "psi_cap_p99": psi_cap,
        "pressure_allowed_pct": full["pressure_allowed"].mean() * 100,
        "sack_pct": full["is_s"].mean() * 100,
        "complete_pct": full["is_c"].mean() * 100,
        "play_result_mean": full["playResult"].mean(),
    })


# --- Film Room ---------------------------------------------------------------

FILM_CATEGORIES = [
    ("clean_window", "Ventana abierta con bolsillo limpio"),
    ("broken_pocket_complete", "Bolsillo roto, pase completo"),
    ("protected_no_window", "Protección larga, sin ventana"),
    ("early_pressure_incomplete", "Presión temprana, pase fallido"),
    ("play_action_window", "Play action con ventana"),
]
FILM_PER_CATEGORY = 4
FILM_FRAMES_AFTER_PASS = 10  # 1 s después del pase


def select_film_plays(full: pd.DataFrame) -> pd.DataFrame:
    """20 jugadas destacadas: 4 por categoría, sin repetir jugada."""
    f = full[full["psi"].notna() & (full["n_receivers"] >= 2)]
    complete = f["passResult"] == "C"
    picks = {
        "clean_window": f[complete & (f["pct"] >= 2.0)].sort_values("psi", ascending=False),
        "broken_pocket_complete": f[complete & f["pressure_reached"].eq(1.0) & (f["pct"] <= 1.5)]
        .sort_values("tws_max", ascending=False),
        "protected_no_window": f[f["pressure_reached"].eq(0.0) & (f["ttt"] >= 2.5)].sort_values("tws_max"),
        "early_pressure_incomplete": f[f["passResult"].isin(["I", "IN"]) & (f["pct"] <= 1.5)]
        .sort_values("min_qb_dist"),
        "play_action_window": f[complete & (f["pff_playAction"] == 1) & (f["pct"] >= 1.5)]
        .sort_values("psi", ascending=False),
    }
    labels = dict(FILM_CATEGORIES)
    chosen, taken = [], set()
    for cat, cand in picks.items():
        n = 0
        for _, row in cand.iterrows():
            k = (row["gameId"], row["playId"])
            if k in taken:
                continue
            taken.add(k)
            chosen.append(row.to_frame().T.assign(category=cat, category_label=labels[cat]))
            n += 1
            if n == FILM_PER_CATEGORY:
                break
    return pd.concat(chosen, ignore_index=True)


def build_film_play(trk: pd.DataFrame, pff_game: pd.DataFrame, players: pd.DataFrame, row: pd.Series) -> dict:
    """Trayectorias cuadro por cuadro de los 22 jugadores y el balón, del snap a 1 s después del pase."""
    pid, snap, pas = int(row["playId"]), int(row["snap_frame"]), int(row["pass_frame"])
    t = trk[trk["playId"] == pid]
    last = min(pas + FILM_FRAMES_AFTER_PASS, int(t["frameId"].max()))
    t = t[(t["frameId"] >= snap) & (t["frameId"] <= last)]
    frames = np.arange(snap, last + 1)

    meta = pff_game[pff_game["playId"] == pid].drop_duplicates("nflId").set_index("nflId")
    names = players.set_index("nflId")["displayName"]
    role_of = meta["pff_role"].str.lower()

    ents, ball = [], None
    for nfl_id, g in t.groupby(t["nflId"].fillna(-1), observed=True):
        g = g.drop_duplicates("frameId").set_index("frameId").reindex(frames)
        xs, ys = np.round(g["x"].to_numpy(dtype=float), 2), np.round(g["y"].to_numpy(dtype=float), 2)
        if nfl_id == -1:
            ball = {"x": xs, "y": ys}
            continue
        jersey = g["jerseyNumber"].dropna()
        ents.append({
            "nfl_id": int(nfl_id),
            "name": names.get(int(nfl_id)),
            "jersey": int(jersey.iat[0]) if len(jersey) else None,
            "position": meta["pff_positionLinedUp"].get(int(nfl_id)),
            "role": meta["pff_role"].get(int(nfl_id)),
            "team": str(g["team"].dropna().iat[0]) if g["team"].notna().any() else None,
            "x": xs, "y": ys,
        })

    # Distancias por frame: Pass rush más cercano al QB y mayor separación de un receptor.
    xy = {e["nfl_id"]: (e["x"], e["y"]) for e in ents}
    ids = {r: [e["nfl_id"] for e in ents if role_of.get(e["nfl_id"]) == r]
           for r in ("pass", "pass rush", "pass route", "coverage")}
    min_rush, max_sep = np.full(len(frames), np.nan), np.full(len(frames), np.nan)
    if ids["pass"] and ids["pass rush"]:
        qx, qy = xy[ids["pass"][0]]
        dists = np.stack([np.hypot(xy[i][0] - qx, xy[i][1] - qy) for i in ids["pass rush"]])
        min_rush = np.nanmin(np.where(np.isnan(dists), np.inf, dists), axis=0)
        min_rush[np.isinf(min_rush)] = np.nan
    if ids["pass route"] and ids["coverage"]:
        seps = []
        for r in ids["pass route"]:
            dd = np.stack([np.hypot(xy[c][0] - xy[r][0], xy[c][1] - xy[r][1]) for c in ids["coverage"]])
            seps.append(np.min(np.where(np.isnan(dd), np.inf, dd), axis=0))
        max_sep = np.max(np.stack(seps), axis=0)
        max_sep[np.isinf(max_sep)] = np.nan

    cols = ["category", "category_label", "possessionTeam", "defensiveTeam", "down", "yardsToGo", "quarter",
            "offenseFormation", "pff_passCoverage", "pff_passCoverageType", "pff_playAction", "passResult",
            "playResult", "playDescription"]
    return clean({
        "game_id": int(row["gameId"]), "play_id": pid,
        **{c: row[c] for c in cols},
        "metrics": {c: row[c] for c in ("ttt", "pct", "pressure_reached", "min_qb_dist", "tws_mean", "tws_max", "psi")},
        "snap_frame": snap, "pass_frame": pas, "pass_index": pas - snap,
        "los_x": ball["x"][0] if ball is not None else None,
        "clock": (frames - snap) / FRAMES_PER_SECOND,
        "min_rush_qb_dist": min_rush,
        "max_receiver_separation": max_sep,
        "players": ents,
        "ball": ball,
    })


FILM_META_KEYS = ("game_id", "play_id", "category", "category_label", "possessionTeam", "defensiveTeam", "down",
                  "yardsToGo", "passResult", "metrics", "playDescription")


# --- Ejecución ----------------------------------------------------------------

def build_summary(data_dir: Path) -> dict:
    tables = load_tables(data_dir)
    games, plays, players, pff = tables["games"], tables["plays"], tables["players"], tables["pff"]
    files = find_tracking_files(data_dir)

    res = compute_all(data_dir, pff[["gameId", "playId", "nflId", "pff_role"]])
    metrics = res["metrics"]
    psi_cap = float(metrics["psi"].quantile(0.99))

    blk = prepare_blockers(pff)
    full = build_full(plays, metrics, blk, psi_cap)

    summary = {
        "meta": {
            "project": "PocketClock AI",
            "pressure_radius_yd": PRESSURE_RADIUS,
            "frames_per_second": FRAMES_PER_SECOND,
            "psi_cap_p99": round(psi_cap, 3),
            "notes": {
                "tracked_plays": "TTT/PCT/TWS/PSI solo existen en jugadas con pass_forward; playResult, "
                                 "complete_pct y sack_pct usan todos los dropbacks de plays.csv.",
                "psi": "PSI = TWS_max / PCT; los promedios de PSI se limitan al percentil 99 global.",
                "pct": "PCT = segundos desde ball_snap hasta que un Pass Rush queda a < 2.5 yd del QB; "
                       "si no ocurre antes del pase, PCT = TTT.",
            },
        },
        "kpis": build_kpis(full, metrics, games["gameId"].nunique(), psi_cap),
        "rankings": build_rankings(full, blk, pff, res, players, psi_cap),
        "matrix": build_matrix(full, blk),
    }

    film = select_film_plays(full)
    film_plays: dict[str, dict] = {}
    for game_id, rows in film.groupby("gameId"):
        trk = load_normalized_tracking(files[int(game_id)])
        pff_game = pff[pff["gameId"] == game_id]
        for _, row in rows.iterrows():
            film_plays[f"{int(game_id)}_{int(row['playId'])}"] = build_film_play(trk, pff_game, players, row)
    summary["film_room"] = [
        {k: film_plays[f"{int(r.gameId)}_{int(r.playId)}"][k] for k in FILM_META_KEYS}
        for r in film.itertuples()
    ]
    summary["plays"] = film_plays
    return summary


def write_summary(summary: dict, path: Path = SUMMARY_PATH) -> int:
    text = json.dumps(summary, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    size = len(text.encode("utf-8"))
    if size >= MAX_SUMMARY_BYTES:
        raise RuntimeError(f"data_summary.json pesa {size:,} bytes (límite {MAX_SUMMARY_BYTES:,}).")
    path.write_text(text, encoding="utf-8")
    return size


def print_findings(s: dict) -> None:
    k = s["kpis"]
    print("\n=== KPIs globales ===")
    print(f"Partidos: {k['n_games']} | dropbacks: {k['n_dropbacks']:,} | con tracking (pass_forward): {k['n_tracked_plays']:,}")
    print(f"TTT medio {k['ttt_mean']:.2f}s (mediana {k['ttt_median']:.2f}) | PCT medio {k['pct_mean']:.2f}s (mediana {k['pct_median']:.2f})")
    print(f"Presión (rusher < 2.5 yd antes del pase): {k['pressure_reached_pct']:.1f}% | distancia mínima media al QB: {k['min_qb_dist_mean']:.2f} yd")
    print(f"TWS medio {k['tws_mean_avg']:.2f} yd | TWS máx medio {k['tws_max_avg']:.2f} yd | PSI medio {k['psi_mean']:.2f} (mediana {k['psi_median']:.2f}; tope p99 {k['psi_cap_p99']:.1f})")
    print(f"Presión permitida (PFF): {k['pressure_allowed_pct']:.1f}% | sacks {k['sack_pct']:.1f}% | completos {k['complete_pct']:.1f}% | playResult medio {k['play_result_mean']:.2f}")

    def line(r, label):
        return (f"  {label:<14} n={r['n']:>5} yds={r['play_result']:.2f} C%={r['complete_pct']:.1f} S%={r['sack_pct']:.1f} "
                f"TTT={r['ttt']:.2f} PCT={r['pct']:.2f} TWSmax={r['tws_max']:.2f} PSI={r['psi']:.2f}")

    m = s["matrix"]
    print("\n=== Play Action (0 vs 1) ===")
    for r in m["play_action"]:
        print(line(r, "PA=" + str(r["value"])))
    print("\n=== Man vs Zone vs Other ===")
    for r in m["coverage_type"]:
        print(line(r, str(r["value"])))
    print("\n=== Por down ===")
    for r in m["down"]:
        print(line(r, f"{r['value']}er/do"))
    print("\n=== Por distancia ===")
    for r in m["distance"]:
        print(line(r, str(r["value"])))
    print("\n=== Tipos de bloqueo (menor presión permitida primero) ===")
    for r in sorted((r for r in m["block_type"] if r["n"] >= 500), key=lambda r: r["pressure_allowed_pct"]):
        print(f"  {r['value']:<3} bloqueos={r['n']:>6} presión permitida={r['pressure_allowed_pct']:.1f}% "
              f"vencido={r['beaten_pct']:.1f}% PCT={r['pct']:.2f} PSI={r['psi']:.2f}")

    rk = s["rankings"]
    print("\n=== Top equipos ofensivos (PSI) ===")
    for i, r in enumerate(rk["teams_offense"], 1):
        print(f"  {i:>2}. {r['team']:<4} PSI={r['psi']:.2f} PCT={r['pct']:.2f} TWSmax={r['tws_max']:.2f} "
              f"presión permitida={r['pressure_allowed_pct']:.1f}% sacks={r['sack_pct']:.1f}%")
    print("\n=== Top linieros (menos presión permitida + mayor PCT) ===")
    for i, r in enumerate(rk["blockers"], 1):
        print(f"  {i:>2}. {r['name']:<22} {r['position']:<3} {r['team']:<4} snaps={r['snaps']} "
              f"presión={r['pressure_allowed_pct']:.1f}% PCT={r['pct']:.2f}")
    print("\n=== Top cazamariscales (menor PCT) ===")
    for i, r in enumerate(rk["rushers_by_pct"], 1):
        print(f"  {i:>2}. {r['name']:<22} {r['position']:<4} {r['team']:<4} rushes={r['rushes']} PCT={r['pct']:.2f} "
              f"cierre={r['closing_speed']:.2f} yd/s")
    print("\n=== Top cazamariscales (velocidad de cierre) ===")
    for i, r in enumerate(rk["rushers_by_closing_speed"][:5], 1):
        print(f"  {i:>2}. {r['name']:<22} cierre={r['closing_speed']:.2f} yd/s PCT={r['pct']:.2f}")
    print("\n=== Top receptores WR/TE (TWS + PSI) ===")
    for i, r in enumerate(rk["receivers_wr_te"], 1):
        print(f"  {i:>2}. {r['name']:<22} {r['position']:<3} {r['team']:<4} rutas={r['routes']} TWS={r['tws']:.2f} yd PSI={r['psi']:.2f}")
    print("\n=== Film Room ===")
    for r in s["film_room"]:
        m_ = r["metrics"]
        print(f"  {r['game_id']}/{r['play_id']} [{r['category_label']}] {r['possessionTeam']} PCT={m_['pct']:.1f} "
              f"TWSmax={m_['tws_max']:.1f} PSI={m_['psi']:.2f} {r['passResult']}")


def main() -> None:
    t0 = time.perf_counter()
    data_dir = get_data_dir()
    print(f"DATA_DIR: {data_dir}")
    summary = build_summary(data_dir)
    size = write_summary(summary)
    print(f"{SUMMARY_PATH} escrito: {size / 1024:.0f} KB en {time.perf_counter() - t0:.1f} s "
          f"({len(summary['film_room'])} jugadas de Film Room)")
    print_findings(summary)


if __name__ == "__main__":
    main()
