"""
precompute.py - Preprocesamiento offline de PocketSync (Reloj de Presion y Sincronia).

Se ejecuta a mano, una sola vez, desde la raiz del proyecto con el Python de .venv:

    python backend/precompute.py              (todos los partidos)
    python backend/precompute.py --limite 3   (prueba con 3 partidos)

Lee el dataset (carpeta FUERA del proyecto, solo lectura) y genera backend/data_summary.json.
El servidor (backend/main.py) NUNCA lee el dataset: solo carga ese JSON.
"""
import argparse
import json
import os
import sys
import time
import warnings
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
# Unica definicion de la ruta del dataset (nunca absoluta en el codigo).
DATA_DIR = Path(os.environ.get("NFL_DATA_DIR") or (Path(__file__).resolve().parent.parent.parent / "data"))
SALIDA = Path(__file__).resolve().parent / "data_summary.json"

RADIO_PCT = 2.0          # yardas (validado contra PFF): radio del bolsillo alrededor del QB
FPS = 10                 # cuadros por segundo del tracking
MIN_FRAMES_PCT = 5       # la presion cuenta desde 0.5 s despues del snap
PISO_PCT = 1.0           # segundos: piso del PCT dentro del PSI
MAX_BYTES = 5_000_000    # el JSON debe pesar menos de 5 MB
N_REPRESENTATIVAS = 20
PRE_SNAP_FRAMES = 10     # 1 s antes del snap en las trayectorias

# Evento final -> tipo de final de jugada
EVENTOS_FIN = {
    "pass_forward": "lanzamiento",
    "autoevent_passforward": "lanzamiento",
    "qb_sack": "sack",
    "qb_strip_sack": "sack",
    "run": "scramble",
}

COLS_PLAYS = ["gameId", "playId", "playDescription", "down", "yardsToGo", "possessionTeam", "defensiveTeam",
              "offenseFormation", "playAction", "pff_playAction", "pff_passCoverage",
              "pff_passCoverageType", "passResult", "playResult"]
COLS_PFF = ["gameId", "playId", "nflId", "pff_role", "pff_positionLinedUp", "pff_hit", "pff_hurry",
            "pff_sack", "pff_hitAllowed", "pff_hurryAllowed", "pff_sackAllowed", "pff_blockType"]
COLS_TRACKING = ["gameId", "playId", "nflId", "displayName", "frameId", "club", "team", "playDirection",
                 "x", "y", "o", "dir", "event"]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def error_y_salir(mensaje):
    print("\nERROR: " + mensaje, file=sys.stderr)
    sys.exit(1)


def fmt(v, dec=2):
    """Formatea un numero para los textos; 's/d' si no hay dato."""
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "s/d"
    return f"{v:.{dec}f}"


def pct_txt(v):
    return "s/d" if v is None else f"{v * 100:.1f}%"


def media(serie):
    s = pd.to_numeric(serie, errors="coerce").dropna()
    return float(s.mean()) if len(s) else None


def moda(serie):
    m = serie.dropna().mode()
    return m.iat[0] if len(m) else None


def a_bool(v):
    return str(v).strip().lower() in ("true", "1", "1.0", "t", "yes")


def limpio(o):
    """Convierte tipos numpy/pandas a tipos JSON (NaN -> null, redondeo a 3 decimales)."""
    if isinstance(o, dict):
        return {str(k): limpio(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [limpio(v) for v in o]
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return round(float(o), 3) if np.isfinite(o) else None
    if o is pd.NA or o is pd.NaT:
        return None
    return o


def bin_distancia(y):
    if pd.isna(y):
        return None
    if y <= 3:
        return "corta"
    if y <= 7:
        return "media"
    return "larga"


# ---------------------------------------------------------------------------
# Lectura de tablas
# ---------------------------------------------------------------------------
def verificar_carpeta():
    if not DATA_DIR.is_dir():
        error_y_salir(
            f"No encontre la carpeta del dataset en: {DATA_DIR}\n"
            "Definela con la variable de entorno NFL_DATA_DIR. En PowerShell:\n"
            '    $env:NFL_DATA_DIR = "C:\\ruta\\a\\data"\n'
            "    .venv\\Scripts\\python backend\\precompute.py\n"
            "Por omision se busca en la carpeta 'data' hermana de la raiz del proyecto."
        )
    for nombre in ("plays.csv", "pffScoutingData.csv", "players.csv", "games.csv"):
        if not (DATA_DIR / nombre).is_file():
            error_y_salir(f"Falta el archivo {nombre} en {DATA_DIR}")
    if not (DATA_DIR / "tracking").is_dir():
        error_y_salir(f"Falta la carpeta tracking/ en {DATA_DIR}")


def cargar_tablas():
    plays = pd.read_csv(DATA_DIR / "plays.csv", usecols=lambda c: c in COLS_PLAYS)
    for c in COLS_PLAYS:
        if c not in plays.columns:
            plays[c] = np.nan
    pff = pd.read_csv(DATA_DIR / "pffScoutingData.csv", usecols=lambda c: c in COLS_PFF)
    for c in COLS_PFF:
        if c not in pff.columns:
            pff[c] = np.nan
    pff["rol"] = pff["pff_role"].astype(str).str.strip().str.lower()
    pff["bt"] = pff["pff_blockType"].astype(str).str.strip().str.upper()
    for c in ("pff_hit", "pff_hurry", "pff_sack", "pff_hitAllowed", "pff_hurryAllowed", "pff_sackAllowed"):
        pff[c] = pd.to_numeric(pff[c], errors="coerce").fillna(0)
    jug = pd.read_csv(DATA_DIR / "players.csv", usecols=lambda c: c in ("nflId", "displayName", "officialPosition"))
    for c in ("displayName", "officialPosition"):
        if c not in jug.columns:
            jug[c] = np.nan
    nombres = jug.set_index("nflId")["displayName"].to_dict()
    posiciones = jug.set_index("nflId")["officialPosition"].to_dict()
    juegos = pd.read_csv(DATA_DIR / "games.csv", usecols=lambda c: c in ("gameId", "week", "homeTeamAbbr", "visitorTeamAbbr"))
    return plays, pff, nombres, posiciones, juegos


def leer_tracking(ruta):
    """Lee un archivo de tracking con usecols y normaliza la direccion del juego."""
    cols = pd.read_csv(ruta, nrows=0).columns
    df = pd.read_csv(ruta, usecols=[c for c in COLS_TRACKING if c in cols])
    if "club" not in df.columns:
        df["club"] = df["team"] if "team" in df.columns else None
    izq = df["playDirection"].astype(str).str.lower().eq("left")
    df.loc[izq, "x"] = 120 - df.loc[izq, "x"]
    df.loc[izq, "y"] = 53.3 - df.loc[izq, "y"]
    for c in ("o", "dir"):
        if c in df.columns:
            df.loc[izq, c] = (df.loc[izq, c] + 180) % 360
    return df


def listar_tracking():
    archivos = {}
    for f in sorted((DATA_DIR / "tracking").glob("tracking_*.csv")):
        try:
            archivos[int(f.stem.split("_")[1])] = f
        except ValueError:
            pass
    return archivos


# ---------------------------------------------------------------------------
# Metricas de UNA jugada
# ---------------------------------------------------------------------------
def analizar_jugada(jdf, roles):
    """
    jdf: tracking de una jugada (ya normalizado). roles: {nflId: pff_role en minusculas}.
    Devuelve (resultado, None) o (None, motivo_de_exclusion).
    """
    snap = jdf.loc[jdf["event"] == "ball_snap", "frameId"]
    if snap.empty:  # respaldo: snap automatico
        snap = jdf.loc[jdf["event"] == "autoevent_ballsnap", "frameId"]
    if snap.empty:
        return None, "sin ball_snap"
    f_snap = int(snap.min())
    fin = jdf.loc[jdf["event"].isin(EVENTOS_FIN) & (jdf["frameId"] >= f_snap), ["frameId", "event"]]
    if fin.empty:
        return None, "sin evento final"
    fin = fin.sort_values("frameId")
    f_fin = int(fin["frameId"].iloc[0])
    tipo = EVENTOS_FIN[fin["event"].iloc[0]]

    qbs = [i for i, r in roles.items() if r == "pass"]
    if not qbs:
        return None, "sin QB identificado"

    jug = jdf[jdf["nflId"].notna() & jdf["frameId"].between(f_snap, f_fin)].drop_duplicates(["frameId", "nflId"])
    jug = jug.assign(nflId=jug["nflId"].astype(int))
    frames = range(f_snap, f_fin + 1)
    X = jug.pivot(index="frameId", columns="nflId", values="x").reindex(frames)
    Y = jug.pivot(index="frameId", columns="nflId", values="y").reindex(frames)

    qb = next((q for q in qbs if q in X.columns), None)
    if qb is None:
        return None, "QB sin tracking"
    xq, yq = X[qb].values, Y[qb].values

    # --- PCT: primer frame con un pass rusher dentro del radio (RADIO_PCT) del QB ---
    rushers = [i for i in X.columns if roles.get(i) == "pass rush"]
    presion, f_pct, pct = False, None, (f_fin - f_snap) / FPS
    if rushers:
        d = np.hypot(X[rushers].values - xq[:, None], Y[rushers].values - yq[:, None])
        d = np.nan_to_num(d, nan=np.inf)
        # Presion real: dentro del radio, a partir de 0.5 s del snap y mas cerca que en el snap
        dentro = (d <= RADIO_PCT) & (d < d[0][None, :])
        dentro[:MIN_FRAMES_PCT] = False
        hay = dentro.any(axis=1)
        if hay.any():
            i = int(hay.argmax())
            presion, f_pct, pct = True, f_snap + i, i / FPS

    # --- TTT y TWS solo en lanzamientos ---
    ttt = tws = psi = None
    separaciones = []
    if tipo == "lanzamiento":
        ttt = (f_fin - f_snap) / FPS
        rec = [i for i in X.columns if roles.get(i) == "pass route"]
        cov = [i for i in X.columns if roles.get(i) == "coverage"]
        if rec and cov:
            xr, yr = X[rec].values[-1], Y[rec].values[-1]
            xc, yc = X[cov].values[-1], Y[cov].values[-1]
            d = np.nan_to_num(np.hypot(xr[:, None] - xc[None, :], yr[:, None] - yc[None, :]), nan=np.inf)
            minimos, cercano = d.min(axis=1), d.argmin(axis=1)
            for k, r in enumerate(rec):
                if np.isfinite(minimos[k]):
                    separaciones.append({"nflId": int(r), "separacion": float(minimos[k]), "defensorId": int(cov[cercano[k]])})
            if separaciones:
                tws = max(s["separacion"] for s in separaciones)
                psi = tws / max(pct, PISO_PCT)

    return {"qb": int(qb), "tipoFinal": tipo, "PCT": pct, "TTT": ttt, "TWS": tws, "PSI": psi,
            "presion": presion, "f_snap": f_snap, "f_fin": f_fin, "f_pct": f_pct,
            "separaciones": separaciones}, None


# ---------------------------------------------------------------------------
# Procesamiento de todos los partidos (un archivo de tracking a la vez)
# ---------------------------------------------------------------------------
def procesar_partidos(archivos, plays, pff):
    filas, receptores, excluidas = [], [], Counter()
    pff_por_juego = {g: d for g, d in pff.groupby("gameId")}
    t0 = time.time()
    for n, (gid, ruta) in enumerate(archivos.items(), 1):
        plays_g = plays[plays["gameId"] == gid]
        meta = plays_g.set_index("playId").to_dict("index")
        roles_g = {}
        if gid in pff_por_juego:
            pg = pff_por_juego[gid].dropna(subset=["nflId"])
            for pid, d in pg.groupby("playId"):
                roles_g[pid] = dict(zip(d["nflId"].astype(int), d["rol"]))
        try:
            df = leer_tracking(ruta)
        except Exception as e:  # archivo ilegible
            excluidas["archivo de tracking ilegible"] += len(meta)
            print(f"  [!] {ruta.name}: {e}")
            continue
        vistos = set()
        for pid, jdf in df.groupby("playId", sort=False):
            vistos.add(pid)
            if pid not in meta:
                excluidas["jugada de tracking sin registro en plays.csv"] += 1
                continue
            try:
                res, motivo = analizar_jugada(jdf, roles_g.get(pid, {}))
            except Exception:
                res, motivo = None, "error al procesar la jugada"
            if res is None:
                excluidas[motivo] += 1
                continue
            m = meta[pid]
            pa = a_bool(m["pff_playAction"] if pd.notna(m["pff_playAction"]) else m["playAction"])
            ydl, resultado = m["yardsToGo"], m["playResult"]
            filas.append({
                "gameId": int(gid), "playId": int(pid),
                "ofensivo": m["possessionTeam"], "defensivo": m["defensiveTeam"], "qb": res["qb"],
                "down": m["down"], "yardsToGo": ydl,
                "formacion": m["offenseFormation"] if pd.notna(m["offenseFormation"]) else "DESCONOCIDA",
                "playAction": pa,
                "cobertura": m["pff_passCoverage"] if pd.notna(m["pff_passCoverage"]) else "Desconocida",
                "tipoCobertura": m["pff_passCoverageType"] if pd.notna(m["pff_passCoverageType"]) else "Desconocida",
                "PCT": res["PCT"], "TTT": res["TTT"], "TWS": res["TWS"], "PSI": res["PSI"],
                "presion": res["presion"], "passResult": m["passResult"], "playResult": resultado,
                "tipoFinal": res["tipoFinal"],
                "sack": (m["passResult"] == "S") or res["tipoFinal"] == "sack",
                "exito": bool(pd.notna(resultado) and pd.notna(ydl) and resultado >= ydl),
            })
            if res["tipoFinal"] == "lanzamiento" and res["separaciones"]:
                mejor = max(res["separaciones"], key=lambda s: s["separacion"])["nflId"]
                for s in res["separaciones"]:
                    receptores.append({"gameId": int(gid), "playId": int(pid), "nflId": s["nflId"],
                                       "sep": s["separacion"], "mas_abierto": s["nflId"] == mejor,
                                       "equipo": m["possessionTeam"]})
        faltan = len(set(meta) - vistos)
        if faltan:
            excluidas["sin tracking en el partido"] += faltan
        if n % 10 == 0 or n == len(archivos):
            print(f"  partidos: {n}/{len(archivos)}  jugadas analizadas: {len(filas)}  ({time.time() - t0:.0f} s)")
    return pd.DataFrame(filas), pd.DataFrame(receptores), excluidas


# ---------------------------------------------------------------------------
# Agregados
# ---------------------------------------------------------------------------
def resumen(g):
    return {"n": int(len(g)), "n_lanzamientos": int(g["PSI"].notna().sum()),
            "PCT": media(g["PCT"]), "TTT": media(g["TTT"]), "TWS": media(g["TWS"]), "PSI": media(g["PSI"]),
            "tasa_presion": media(g["presion"].astype(float)), "tasa_sack": media(g["sack"].astype(float)),
            "tasa_exito": media(g["exito"].astype(float))}


def ranking_jugadas(j, clave, min_n, top, orden="PSI"):
    """Ranking por una columna (equipo, QB...) a partir de las metricas por jugada."""
    out = []
    for k, g in j.groupby(clave):
        r = resumen(g)
        if r["n"] < min_n:
            continue
        r[clave] = k
        out.append(r)
    out = [r for r in out if r.get(orden) is not None]
    out.sort(key=lambda r: r[orden], reverse=True)
    return out[:top]


def ranking_receptores(rec, j, nombres, min_n, top, posiciones=None, permitidas=("WR", "TE")):
    if rec.empty:
        return []
    if posiciones is not None:  # solo las posiciones pedidas (WR/TE o RB)
        rec = rec[rec["nflId"].map(posiciones).isin(permitidas)]
    out = []
    for nfl, g in rec.groupby("nflId"):
        if len(g) < min_n:
            continue
        out.append({"nflId": int(nfl), "nombre": nombres.get(nfl, str(nfl)), "equipo": moda(g["equipo"]),
                    "n": int(len(g)), "separacion_media": float(g["sep"].mean()),
                    "pct_mas_abierto": float(g["mas_abierto"].mean())})
    out.sort(key=lambda r: r["separacion_media"], reverse=True)
    return out[:top]


def ranking_linieros(pff_inc, nombres, posiciones, min_snaps, top):
    ol = pff_inc[pff_inc["rol"] == "pass block"].copy()
    es_ol = ol["nflId"].map(posiciones).isin(["T", "G", "C"]) | ol["pff_positionLinedUp"].isin(["LT", "LG", "C", "RG", "RT"])
    ol = ol[es_ol]
    ol["perm"] = ol["pff_hitAllowed"] + ol["pff_hurryAllowed"] + ol["pff_sackAllowed"]
    out = []
    for nfl, g in ol.groupby("nflId"):
        if len(g) < min_snaps:
            continue
        out.append({"nflId": int(nfl), "nombre": nombres.get(nfl, str(nfl)), "equipo": moda(g["ofensivo"]),
                    "snaps": int(len(g)), "presiones_permitidas": int(g["perm"].sum()),
                    "sacks_permitidos": int(g["pff_sackAllowed"].sum()),
                    "presiones_por_100": float(g["perm"].sum() / len(g) * 100), "PCT_medio": media(g["PCT"])})
    out.sort(key=lambda r: (r["presiones_por_100"], -r["snaps"]))  # menos presiones = mejor; empate: mas snaps primero
    return out[:top]


def ranking_defensivos(pff_inc, nombres, min_snaps, top):
    pr = pff_inc[pff_inc["rol"] == "pass rush"].copy()
    pr["pres"] = pr["pff_hit"] + pr["pff_hurry"] + pr["pff_sack"]
    out = []
    for nfl, g in pr.groupby("nflId"):
        if len(g) < min_snaps:
            continue
        out.append({"nflId": int(nfl), "nombre": nombres.get(nfl, str(nfl)), "equipo": moda(g["defensivo"]),
                    "snaps": int(len(g)), "presiones": int(g["pres"].sum()), "sacks": int(g["pff_sack"].sum()),
                    "presiones_por_100": float(g["pres"].sum() / len(g) * 100), "PCT_medio": media(g["PCT"])})
    out.sort(key=lambda r: r["presiones_por_100"], reverse=True)
    return out[:top]


def matriz_situacional(j):
    d = j.dropna(subset=["down"]).copy()
    d["distancia"] = d["yardsToGo"].map(bin_distancia)
    d = d.dropna(subset=["distancia"])
    out = []
    for (dw, dist, form, pa, cob), g in d.groupby(["down", "distancia", "formacion", "playAction", "tipoCobertura"]):
        r = resumen(g)
        r.update({"down": int(dw), "distancia": dist, "formacion": form, "playAction": bool(pa), "tipoCobertura": cob})
        out.append(r)
    return out


def efecto_bloqueos(j, pff_inc):
    """En 3rd down: jugadas con bloqueo de ayuda (CH chip, SW switch) frente a solo PP."""
    t3 = j[j["down"] == 3]
    flags = (pff_inc.assign(ch=pff_inc["bt"] == "CH", sw=pff_inc["bt"] == "SW")
             .groupby(["gameId", "playId"])[["ch", "sw"]].max().reset_index())
    t3 = t3.merge(flags, on=["gameId", "playId"], how="left").fillna({"ch": False, "sw": False})
    grupos = {"solo_PP": t3[~t3["ch"] & ~t3["sw"]], "CH": t3[t3["ch"]], "SW": t3[t3["sw"]],
              "CH_o_SW": t3[t3["ch"] | t3["sw"]]}
    out = {k: resumen(g) for k, g in grupos.items()}
    base = out["solo_PP"]
    for k in ("CH", "SW", "CH_o_SW"):
        out[k]["delta_PCT_vs_PP"] = None if out[k]["PCT"] is None or base["PCT"] is None else out[k]["PCT"] - base["PCT"]
        out[k]["delta_presion_vs_PP"] = (None if out[k]["tasa_presion"] is None or base["tasa_presion"] is None
                                         else out[k]["tasa_presion"] - base["tasa_presion"])
    return out


def construir_hipotesis(j, bloqueos, rank_ol, rank_rec, min_form):
    h = {}
    # 1) Play Action
    pa, sin = resumen(j[j["playAction"]]), resumen(j[~j["playAction"]])
    h["play_action"] = {
        "titulo": "Efecto del Play Action", "con_play_action": pa, "sin_play_action": sin,
        "texto": (f"Con Play Action el PCT medio es {fmt(pa['PCT'])} s y sin PA {fmt(sin['PCT'])} s; "
                  f"el TWS es {fmt(pa['TWS'])} yd contra {fmt(sin['TWS'])} yd; el PSI es {fmt(pa['PSI'])} contra "
                  f"{fmt(sin['PSI'])}; la tasa de sack es {pct_txt(pa['tasa_sack'])} contra {pct_txt(sin['tasa_sack'])} "
                  f"({pa['n']} y {sin['n']} jugadas)."),
    }
    # 2) Bloqueos de ayuda
    b, ch, sw = bloqueos["solo_PP"], bloqueos["CH"], bloqueos["SW"]
    h["bloqueos_ayuda"] = {
        "titulo": "Bloqueos de ayuda en 3rd down (CH y SW contra PP)", "datos": bloqueos,
        "texto": (f"En 3rd down, solo PP: PCT {fmt(b['PCT'])} s, presion {pct_txt(b['tasa_presion'])} ({b['n']} jugadas). "
                  f"Con CH: PCT {fmt(ch['PCT'])} s, presion {pct_txt(ch['tasa_presion'])} ({ch['n']}). "
                  f"Con SW: PCT {fmt(sw['PCT'])} s, presion {pct_txt(sw['tasa_presion'])} ({sw['n']})."),
    }
    # 3) Formaciones bajo presion
    forms = []
    for f, g in j.groupby("formacion"):
        if len(g) >= min_form:
            r = resumen(g)
            r["formacion"] = f
            forms.append(r)
    forms.sort(key=lambda r: (r["tasa_presion"] or 0), reverse=True)
    if forms:
        a, z = forms[0], forms[-1]
        txt = (f"La formacion con mas presion es {a['formacion']} ({pct_txt(a['tasa_presion'])}, PCT {fmt(a['PCT'])} s, "
               f"{a['n']} jugadas); la que menos, {z['formacion']} ({pct_txt(z['tasa_presion'])}, PCT {fmt(z['PCT'])} s, "
               f"{z['n']} jugadas).")
    else:
        txt = "No hay formaciones con jugadas suficientes."
    h["formaciones_presion"] = {"titulo": "Formaciones bajo presion", "formaciones": forms, "texto": txt}
    # 4) Talento de linieros y receptores
    ol = rank_ol[0] if rank_ol else None
    rc = rank_rec[0] if rank_rec else None
    partes = []
    if ol:
        partes.append(f"Mejor liniero: {ol['nombre']} ({ol['equipo']}) con {fmt(ol['presiones_por_100'])} presiones permitidas por 100 snaps ({ol['snaps']} snaps).")
    if rc:
        partes.append(f"Receptor con mas separacion: {rc['nombre']} ({rc['equipo']}) con {fmt(rc['separacion_media'])} yd en promedio ({rc['n']} jugadas).")
    h["talento"] = {"titulo": "Talento de linieros y receptores", "texto": " ".join(partes) or "Sin datos suficientes."}
    return h


# ---------------------------------------------------------------------------
# Trayectorias de 20 jugadas representativas
# ---------------------------------------------------------------------------
def elegir_representativas(j):
    elegidas, usadas = [], set()

    def tomar(etiqueta, d, col, asc, k):
        n = 0
        for r in d.dropna(subset=[col]).sort_values(col, ascending=asc).itertuples():
            clave = (int(r.gameId), int(r.playId))
            if clave in usadas:
                continue
            usadas.add(clave)
            elegidas.append((clave, etiqueta))
            n += 1
            if n >= k:
                break

    lanz = j[j["PSI"].notna()]
    tomar("sack_rapido", j[j["sack"]], "PCT", True, 4)
    tomar("psi_alto", lanz, "PSI", False, 4)
    tomar("psi_bajo", lanz, "PSI", True, 4)
    tomar("play_action", lanz[lanz["playAction"]], "PSI", False, 4)
    tomar("tercera_larga", lanz[(lanz["down"] == 3) & (lanz["yardsToGo"] >= 8)], "PSI", False, 4)
    if len(elegidas) < N_REPRESENTATIVAS:
        tomar("otra", lanz, "PSI", False, N_REPRESENTATIVAS - len(elegidas))
    return elegidas[:N_REPRESENTATIVAS]


def redondear_lista(arr):
    return [None if not np.isfinite(v) else round(float(v), 1) for v in arr]


def construir_trayectoria(jdf, roles, fila, res, etiqueta, nombres):
    f0 = max(int(jdf["frameId"].min()), res["f_snap"] - PRE_SNAP_FRAMES)
    frames = range(f0, res["f_fin"] + 1)
    d = jdf[jdf["frameId"].between(f0, res["f_fin"])].drop_duplicates(["frameId", "nflId"])
    jug = d[d["nflId"].notna()].copy()
    jug["nflId"] = jug["nflId"].astype(int)
    X = jug.pivot(index="frameId", columns="nflId", values="x").reindex(frames)
    Y = jug.pivot(index="frameId", columns="nflId", values="y").reindex(frames)
    club = jug.groupby("nflId")["club"].first().to_dict()
    jugadores = []
    for i in X.columns:
        xy = [[a, b] if a is not None and b is not None else None
              for a, b in zip(redondear_lista(X[i].values), redondear_lista(Y[i].values))]
        jugadores.append({"nflId": int(i), "nombre": nombres.get(i, str(i)), "club": club.get(i),
                          "rol": roles.get(i, ""), "xy": xy})
    pelota = d[d["nflId"].isna()].drop_duplicates("frameId").set_index("frameId").reindex(frames)
    balon = [[a, b] if a is not None and b is not None else None
             for a, b in zip(redondear_lista(pelota["x"].values), redondear_lista(pelota["y"].values))]
    eventos = [{"frame": int(r.frameId - f0), "evento": r.event}
               for r in d.dropna(subset=["event"]).drop_duplicates(["frameId", "event"]).itertuples()]
    return {
        "gameId": fila["gameId"], "playId": fila["playId"], "etiqueta": etiqueta,
        "descripcion": fila["descripcion"], "ofensivo": fila["ofensivo"], "defensivo": fila["defensivo"],
        "qb": res["qb"], "down": fila["down"], "yardsToGo": fila["yardsToGo"], "formacion": fila["formacion"],
        "playAction": fila["playAction"], "cobertura": fila["cobertura"], "tipoCobertura": fila["tipoCobertura"],
        "passResult": fila["passResult"], "playResult": fila["playResult"], "tipoFinal": res["tipoFinal"],
        "PCT": res["PCT"], "TTT": res["TTT"], "TWS": res["TWS"], "PSI": res["PSI"], "presion": res["presion"],
        "fps": FPS, "frame_snap": res["f_snap"] - f0, "frame_fin": res["f_fin"] - f0,
        "frame_pct": None if res["f_pct"] is None else res["f_pct"] - f0,
        "jugadores": jugadores, "balon": balon, "separacion_receptores": res["separaciones"], "eventos": eventos,
    }


def extraer_trayectorias(elegidas, archivos, j, pff, plays, nombres):
    desc = plays.set_index(["gameId", "playId"])["playDescription"].to_dict()
    filas = j.set_index(["gameId", "playId"]).to_dict("index")
    por_juego = {}
    for (gid, pid), etq in elegidas:
        por_juego.setdefault(gid, []).append((pid, etq))
    salida = []
    for gid, lista in por_juego.items():
        df = leer_tracking(archivos[gid])
        pg = pff[pff["gameId"] == gid].dropna(subset=["nflId"])
        for pid, etq in lista:
            jdf = df[df["playId"] == pid]
            d = pg[pg["playId"] == pid]
            roles = dict(zip(d["nflId"].astype(int), d["rol"]))
            res, _ = analizar_jugada(jdf, roles)
            if res is None:
                continue
            fila = dict(filas[(gid, pid)])
            fila.update({"gameId": gid, "playId": pid, "descripcion": desc.get((gid, pid))})
            salida.append(construir_trayectoria(jdf, roles, fila, res, etq, nombres))
    return salida


# ---------------------------------------------------------------------------
# Escritura del JSON y resumen en consola
# ---------------------------------------------------------------------------
COLUMNAS_JUGADAS = ["gameId", "playId", "ofensivo", "defensivo", "qb", "down", "yardsToGo", "formacion",
                    "playAction", "cobertura", "tipoCobertura", "PCT", "TTT", "TWS", "PSI", "presion",
                    "passResult", "playResult", "tipoFinal"]


def escribir_json(datos):
    def serializar():
        return json.dumps(limpio(datos), ensure_ascii=False, separators=(",", ":"))

    texto = serializar()
    filas = datos["jugadas"]["filas"]
    original = len(filas)
    # Si pesa demasiado, se aligera la tabla de jugadas tomando una de cada k.
    while len(texto.encode("utf-8")) >= MAX_BYTES and len(filas) > 100:
        k = 2
        filas = filas[::k]
        datos["jugadas"]["filas"] = filas
        texto = serializar()
    if len(filas) < original:
        datos["meta"]["jugadas_en_tabla"] = len(filas)
        texto = serializar()
        print(f"  [!] El JSON superaba 5 MB: la tabla de jugadas se aligero a {len(filas)} de {original}.")
    SALIDA.write_text(texto, encoding="utf-8")
    return len(texto.encode("utf-8"))


def validar_contra_pff(j, pff_inc):
    """Compara nuestra presion con la de PFF (alguna fila de la jugada con hit, hurry o sack = 1)."""
    pff_pres = (pff_inc.assign(p=(pff_inc["pff_hit"] > 0) | (pff_inc["pff_hurry"] > 0) | (pff_inc["pff_sack"] > 0))
                .groupby(["gameId", "playId"])["p"].max().rename("pff_presion").reset_index())
    v = j[["gameId", "playId", "presion"]].merge(pff_pres, on=["gameId", "playId"], how="inner")
    v["pff_presion"] = v["pff_presion"].astype(bool)
    if v.empty:
        return {"jugadas_comparadas": 0, "coincidencia": None, "tasa_presion_nuestra": None, "tasa_presion_pff": None}
    return {"jugadas_comparadas": int(len(v)),
            "coincidencia": float((v["presion"] == v["pff_presion"]).mean()),
            "tasa_presion_nuestra": float(v["presion"].mean()),
            "tasa_presion_pff": float(v["pff_presion"].mean())}


def imprimir_resumen(j, h, rank, excluidas, total_plays, tam, val):
    print("\n" + "=" * 60)
    print("RESUMEN DE HALLAZGOS")
    print("=" * 60)
    lanz = j[j["PSI"].notna()]
    print(f"Jugadas analizadas: {len(j)} | con lanzamiento y TWS: {len(lanz)} | sacks: {int(j['sack'].sum())}")
    print(f"PCT medio: {fmt(media(j['PCT']))} s | TTT medio: {fmt(media(j['TTT']))} s | "
          f"TWS medio: {fmt(media(j['TWS']))} yd | PSI medio: {fmt(media(j['PSI']))}")
    print(f"Jugadas con presion (pass rusher a <= {RADIO_PCT} yd del QB): {pct_txt(media(j['presion'].astype(float)))}")
    for k in ("play_action", "bloqueos_ayuda", "formaciones_presion", "talento"):
        print(f"- {h[k]['titulo']}: {h[k]['texto']}")
    if rank["qb"]:
        q = rank["qb"][0]
        print(f"- QB con mejor PSI medio: {q['nombre']} ({q['equipo']}) PSI {fmt(q['PSI'])} en {q['n']} jugadas")
    print(f"- Validacion contra PFF ({val['jugadas_comparadas']} jugadas): coincidencia {pct_txt(val['coincidencia'])}, "
          f"presion nuestra {pct_txt(val['tasa_presion_nuestra'])} vs PFF {pct_txt(val['tasa_presion_pff'])}")
    print("\nJUGADAS EXCLUIDAS")
    total_exc = sum(excluidas.values())
    print(f"Total excluidas: {total_exc} (de {len(j) + total_exc} jugadas revisadas en los partidos procesados)")
    for motivo, n in excluidas.most_common():
        print(f"  {n:>6}  {motivo}")
    print(f"\nArchivo generado: {SALIDA.name} ({tam / 1e6:.2f} MB)")


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Genera backend/data_summary.json a partir del dataset NFL.")
    ap.add_argument("--limite", type=int, default=None, help="procesar solo N partidos (para pruebas)")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    verificar_carpeta()
    print(f"Dataset: {DATA_DIR}")
    archivos = listar_tracking()
    if not archivos:
        error_y_salir(f"No hay archivos tracking_<gameId>.csv en {DATA_DIR / 'tracking'}")
    if args.limite:
        archivos = dict(list(archivos.items())[:args.limite])
    print(f"Partidos a procesar: {len(archivos)}")

    plays, pff, nombres, posiciones, juegos = cargar_tablas()
    plays = plays[plays["gameId"].isin(archivos)]
    j, rec, excluidas = procesar_partidos(archivos, plays, pff)
    if j.empty:
        error_y_salir("No se pudo analizar ninguna jugada. Revisa el log de exclusiones: " + str(dict(excluidas)))

    # Minimos para rankings (se relajan al probar con --limite)
    prueba = bool(args.limite)
    min_eq, min_qb, min_snaps, min_rec, min_form = (1, 1, 1, 1, 1) if prueba else (30, 100, 100, 30, 100)

    # pff solo de las jugadas analizadas, con datos de la jugada
    pff_inc = pff.merge(j[["gameId", "playId", "ofensivo", "defensivo", "PCT"]], on=["gameId", "playId"], how="inner")

    validacion = validar_contra_pff(j, pff_inc)
    rank_ol = ranking_linieros(pff_inc, nombres, posiciones, min_snaps, 30)
    rank_rec = ranking_receptores(rec, j, nombres, min_rec, 30, posiciones, ("WR", "TE"))
    rank_rb = ranking_receptores(rec, j, nombres, min_rec, 30, posiciones, ("RB",))
    rankings = {
        "equipo_ofensivo": ranking_jugadas(j, "ofensivo", min_eq, 32),
        "equipo_defensivo": ranking_jugadas(j, "defensivo", min_eq, 32),
        "qb": ranking_jugadas(j, "qb", min_qb, 30),
        "liniero": rank_ol,
        "defensivo": ranking_defensivos(pff_inc, nombres, min_snaps, 30),
        "receptor": rank_rec,
        "ranking_rb": rank_rb,
    }
    equipo_qb = j.groupby("qb")["ofensivo"].agg(moda).to_dict()
    for r in rankings["qb"]:
        r["nombre"] = nombres.get(r["qb"], str(r["qb"]))
        r["equipo"] = equipo_qb.get(r["qb"])

    bloqueos = efecto_bloqueos(j, pff_inc)
    hipotesis = construir_hipotesis(j, bloqueos, rank_ol, rank_rec, min_form)
    matriz = matriz_situacional(j)

    print("Extrayendo trayectorias de jugadas representativas...")
    elegidas = elegir_representativas(j)
    trayectorias = extraer_trayectorias(elegidas, archivos, j, pff, plays, nombres)

    ids = set(j["gameId"])
    partidos = {int(r.gameId): [r.week, r.homeTeamAbbr, r.visitorTeamAbbr]
                for r in juegos.itertuples() if r.gameId in ids} if {"week", "homeTeamAbbr"} <= set(juegos.columns) else {}
    tabla = j[COLUMNAS_JUGADAS].copy()
    tabla["playAction"] = tabla["playAction"].astype(int)
    tabla["presion"] = tabla["presion"].astype(int)
    nombres_qb = {int(q): nombres.get(q, str(q)) for q in j["qb"].unique()}

    datos = {
        "meta": {"generado": datetime.now().isoformat(timespec="seconds"), "partidos": len(archivos),
                 "jugadas_analizadas": int(len(j)), "jugadas_excluidas": int(sum(excluidas.values())),
                 "parcial": prueba, "radio_pct_yd": RADIO_PCT, "piso_pct_s": PISO_PCT,
                 "validacion_pff": validacion},
        "excluidas": dict(excluidas),
        "partidos": partidos,
        "nombres_qb": nombres_qb,
        "jugadas": {"columnas": COLUMNAS_JUGADAS, "filas": tabla.astype(object).where(tabla.notna(), None).values.tolist()},
        "rankings": rankings,
        "matriz": matriz,
        "bloqueos_ayuda_3er_down": bloqueos,
        "hipotesis": hipotesis,
        "trayectorias": trayectorias,
    }
    tam = escribir_json(datos)
    imprimir_resumen(j, hipotesis, rankings, excluidas, len(plays), tam, validacion)


if __name__ == "__main__":
    main()