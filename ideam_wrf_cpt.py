"""
ideam_wrf_cpt.py
================
Extensión del flujo de ideam_extractor.py. Agrega tres familias nuevas:

  A) Modelo grillado descargable:
       - WRF 00Z Colombia  -> NetCDF y GeoTIFF
       - GFS 06Z Colombia  -> GRIB2
     (datos reales, se procesan sin ArcGIS con xarray/cfgrib/rasterio)

  B) CPT — Predicción mensual (estacional) de IDEAM:
       imágenes PNG por variable (precip/temp/viento), 6 meses, 6 productos.

  C) Índices ENSO (NOAA/CPC) + clasificador de fase (Niño/Niña/Neutral) y
     teleconexión esperada para Colombia. Esto es lo que alimenta el análisis
     de "condiciones El Niño" — NO el WRF, que es de corto plazo.

Reutiliza toda la infraestructura del extractor base (sesión con reintentos,
dedup por hash, manifiesto latest.json, subida opcional a OSS).

Uso:
    python ideam_wrf_cpt.py --wrf --cpt --enso
    # o desde el orquestador: importar run_all() y añadirlo a main()
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import re
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# Reutilizamos los internos del extractor base (mismo directorio).
from ideam_extractor import (  # noqa: F401
    SESSION, DATA_ROOT, TIMEOUT, log,
    _sha256, _partition_dir, _changed, _commit_hash,
    _write_manifest, _maybe_upload_oss, _resolve_manifest_path,
)

import requests

# Sesión sin reintentos para los HEAD de "¿existe esta URL?": si el CPT
# tiene decenas de combinaciones producto×mes a verificar, reintentar 3
# veces con backoff exponencial en cada URL que falla multiplica un timeout
# corto en una espera larga (fue la causa real del colgado original).
_HEAD_SESSION = requests.Session()
_HEAD_SESSION.headers.update(SESSION.headers)


# --------------------------------------------------------------------------- #
# A) Modelo grillado: WRF / GFS
# --------------------------------------------------------------------------- #
WRF_BASE = "https://bart.ideam.gov.co/wrfideam/new_modelo"

MODEL_DIRS = {
    "wrf00_netcdf": (f"{WRF_BASE}/WRF00COLOMBIA/netcdf", (".nc", ".nc4", ".netcdf")),
    "wrf00_tif":    (f"{WRF_BASE}/WRF00COLOMBIA/tif",    (".tif", ".tiff")),
    "gfs06_grib2":  (f"{WRF_BASE}/GFS06COLOMBIA/grib2",  (".grb2", ".grib2", ".grb")),
}

# Regex para parsear el autoindex de Apache (nombre + fecha de modificación).
_AUTOINDEX_RX = re.compile(
    r'href="(?P<name>[^"?][^"]*)".*?'
    r'(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2})',
    re.S,
)


def _list_autoindex(url: str, exts: tuple[str, ...]) -> list[tuple[str, dt.datetime]]:
    """Lista (nombre, fecha) de un índice de directorio, filtrando por extensión.

    Nota: si el servidor bloquea el listado para clientes 'robot', conviene
    correr esto desde el entorno donde sí responde (Actions/servidor propio)
    con el User-Agent que ya trae SESSION.
    """
    r = SESSION.get(url if url.endswith("/") else url + "/", timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for m in _AUTOINDEX_RX.finditer(r.text):
        name = m.group("name")
        if name.endswith("/") or name.startswith(("?", "/")):
            continue
        if not name.lower().endswith(exts):
            continue
        when = dt.datetime.strptime(f'{m.group("date")} {m.group("time")}', "%Y-%m-%d %H:%M")
        out.append((name, when))
    return out


def fetch_model_latest(dataset: str, url: str, exts: tuple[str, ...]) -> bool:
    """Descarga el archivo más reciente de un directorio de modelo (WRF/GFS).

    Por el peso de estos archivos, descargamos solo el último por corrida.
    """
    base = url if url.endswith("/") else url + "/"
    files = _list_autoindex(base, exts)
    if not files:
        log.warning("· %-18s sin archivos en %s", dataset, url)
        return False
    name, when = max(files, key=lambda x: x[1])
    file_url = base + name

    # Dedup barato por (nombre + fecha) antes de descargar el binario pesado.
    sig = f"{name}|{when.isoformat()}"
    if not _changed(dataset, sig):
        log.info("· %-18s sin corrida nueva (%s)", dataset, name)
        return False

    r = SESSION.get(file_url, timeout=TIMEOUT * 3)  # binarios grandes
    r.raise_for_status()
    blob = r.content

    pdir = _partition_dir(dataset)
    out_path = pdir / name
    out_path.write_bytes(blob)

    _commit_hash(dataset, sig)
    _write_manifest(
        dataset, "grid",
        files={"data": out_path},
        source_url=file_url, filename=name,
        model_run=when.isoformat(), size_bytes=len(blob),
        note="Grilla de modelo: procesar con xarray/cfgrib/rasterio (sin ArcGIS).",
    )
    _maybe_upload_oss(out_path)
    log.info("✓ %-18s %s (%.1f MB)", dataset, name, len(blob) / 1e6)
    return True


def run_models() -> tuple[int, int]:
    ok = fail = 0
    for ds, (url, exts) in MODEL_DIRS.items():
        try:
            fetch_model_latest(ds, url, exts); ok += 1
        except Exception as e:  # noqa: BLE001
            log.error("✗ %s: %s", ds, e); fail += 1
    return ok, fail


# --------------------------------------------------------------------------- #
# B) CPT — Predicción mensual (imágenes PNG, patrón de URL conocido)
# --------------------------------------------------------------------------- #
CPT_BASE = f"{WRF_BASE}/CPT/gif/PREDICCION_MENSUAL"

# Sufijo de variable en el nombre de archivo. 'PREC' está confirmado en la web;
# 'TEMP'/'VIEN' son candidatos: si dan 404 se omiten (HEAD previo).
CPT_VARS = {"PREC": "precipitacion", "TEMP": "temperatura", "VIEN": "viento"}
CPT_PRODUCTS = ["CLIMA", "DETER", "INDICE", "PROBVALORDET", "PROB", "PROB1090"]
CPT_MESES = range(1, 7)

# Timeout corto para el HEAD de verificación: si el servidor CPT no responde
# rápido a un HEAD, no vale la pena esperar TIMEOUT completo (60s) por cada
# una de las hasta 36 combinaciones producto×mes — eso fue lo que colgó el
# extractor la primera vez (~100 min para 108 combinaciones).
CPT_HEAD_TIMEOUT = 12


def _exists(url: str) -> bool:
    try:
        return _HEAD_SESSION.head(url, timeout=CPT_HEAD_TIMEOUT, allow_redirects=True).status_code == 200
    except requests.RequestException:
        return False


def fetch_cpt(var_suffix: str = "PREC") -> bool:
    """Descarga el set de imágenes CPT de una variable (hasta 6 productos × 6 meses).

    Primero verifica con HEAD cuáles URLs existen (rápido, sin bajar el
    binario); si ninguna existe, escribe un manifiesto "unavailable" en vez
    de dejar el dataset sin snapshot alguno, para que la app distinga
    "no publicado por CPT" de "nunca se corrió el extractor"."""
    if var_suffix not in CPT_VARS:
        raise ValueError(f"variable CPT desconocida: {var_suffix}")
    dataset = f"cpt_prediccion_{CPT_VARS[var_suffix]}"

    candidatos = [
        (prod, mes, f"{prod}MES{mes}{var_suffix}.png")
        for prod in CPT_PRODUCTS for mes in CPT_MESES
    ]
    existentes = [
        (prod, mes, fname) for prod, mes, fname in candidatos
        if _exists(f"{CPT_BASE}/{fname}")
    ]

    if not existentes:
        log.warning("· %-18s ninguna imagen publicada (var %s, %d URLs verificadas)",
                     dataset, var_suffix, len(candidatos))
        _write_manifest(
            dataset, "unavailable",
            files={},
            source_url=CPT_BASE, variable=CPT_VARS[var_suffix],
            n_images=0,
            note=f"El CPT de IDEAM no tiene publicada la variable '{CPT_VARS[var_suffix]}' "
                 "en la corrida más reciente (verificado con HEAD, no es un error de la app).",
        )
        return False

    pdir = _partition_dir(dataset)
    saved, hashes = {}, []
    for prod, mes, fname in existentes:
        url = f"{CPT_BASE}/{fname}"
        try:
            r = SESSION.get(url, timeout=TIMEOUT)
            if not r.ok:
                continue
            (pdir / fname).write_bytes(r.content)
            saved[f"{prod}_mes{mes}"] = pdir / fname
            hashes.append(_sha256(r.content))
        except requests.RequestException:
            continue

    if not saved:
        log.warning("· %-18s HEAD confirmó %d URLs pero GET falló en todas", dataset, len(existentes))
        return False

    combined = _sha256("".join(sorted(hashes)).encode())
    if not _changed(dataset, combined):
        log.info("· %-18s sin cambios (%d imgs)", dataset, len(saved))
        return False

    _commit_hash(dataset, combined)
    _write_manifest(
        dataset, "image_set",
        files={k: str(v) for k, v in saved.items()},
        source_url=CPT_BASE, variable=CPT_VARS[var_suffix],
        n_images=len(saved), content_hash=combined,
        note="Predicción estacional CPT, 6 meses. Coherente con el estado ENSO.",
    )
    for p in saved.values():
        _maybe_upload_oss(p)
    log.info("✓ %-18s %d imágenes (de %d verificadas)", dataset, len(saved), len(existentes))
    return True


def run_cpt() -> tuple[int, int]:
    ok = fail = 0
    for suffix in CPT_VARS:
        try:
            fetch_cpt(suffix); ok += 1
        except Exception as e:  # noqa: BLE001
            log.error("✗ cpt_%s: %s", suffix, e); fail += 1
    return ok, fail


# --------------------------------------------------------------------------- #
# C) Índices ENSO + clasificación de fase + teleconexión Colombia
# --------------------------------------------------------------------------- #
# Fuentes públicas NOAA/CPC (texto plano). Son la base correcta para la fase ENSO.
ENSO_SOURCES = {
    "oni": "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
    "nino34": "https://www.cpc.ncep.noaa.gov/data/indices/ersst5.nino.mth.91-20.ascii",
}


def enso_phase(oni: float) -> str:
    """Fase ENSO por umbral ONI (estándar NOAA: ±0.5 °C)."""
    if oni >= 0.5:
        return "El Niño"
    if oni <= -0.5:
        return "La Niña"
    return "Neutral"


def enso_intensity(oni: float) -> str:
    a = abs(oni)
    if a < 0.5:
        return "—"
    if a < 1.0:
        return "débil"
    if a < 1.5:
        return "moderado"
    if a < 2.0:
        return "fuerte"
    return "muy fuerte"


def colombia_teleconnection(phase: str) -> dict:
    """Implicación climática típica de la fase ENSO para Colombia (probabilística)."""
    if phase == "El Niño":
        return {
            "precipitacion": "déficit (más seco que lo normal)",
            "temperatura": "por encima de lo normal",
            "riesgos": ["sequía", "incendios de cobertura vegetal", "desabastecimiento hídrico"],
            "regiones_sensibles": ["Andina", "Caribe", "Pacífico"],
        }
    if phase == "La Niña":
        return {
            "precipitacion": "excedentes (más lluvioso que lo normal)",
            "temperatura": "por debajo de lo normal",
            "riesgos": ["inundaciones", "deslizamientos", "crecientes súbitas"],
            "regiones_sensibles": ["Andina", "Caribe", "Pacífico"],
        }
    return {
        "precipitacion": "cercana a la climatología",
        "temperatura": "cercana a la climatología",
        "riesgos": ["sin señal ENSO dominante; pesan otros moduladores (ITCZ, MJO, ondas)"],
        "regiones_sensibles": [],
    }


def _parse_oni_ascii(text: str) -> pd.DataFrame:
    """Parsea oni.ascii.txt -> columnas SEAS, YR, TOTAL, ANOM."""
    df = pd.read_csv(io.StringIO(text), sep=r"\s+")
    df.columns = [c.strip().upper() for c in df.columns]
    return df


def fetch_enso_indices() -> Optional[dict]:
    """Descarga ONI, clasifica la fase más reciente y guarda el assessment."""
    dataset = "enso_indices"
    pdir = _partition_dir(dataset)

    r = SESSION.get(ENSO_SOURCES["oni"], timeout=TIMEOUT)
    r.raise_for_status()
    raw = r.text
    df = _parse_oni_ascii(raw)
    (pdir / "oni.ascii.txt").write_text(raw, encoding="utf-8")
    df.to_parquet(pdir / "oni.parquet", index=False)

    last = df.iloc[-1]
    oni_val = float(last["ANOM"])
    phase = enso_phase(oni_val)
    assessment = {
        "trimestre": str(last["SEAS"]),
        "anio": int(last["YR"]),
        "oni": oni_val,
        "fase": phase,
        "intensidad": enso_intensity(oni_val),
        "teleconexion_colombia": colombia_teleconnection(phase),
        "fuente": ENSO_SOURCES["oni"],
        "actualizado": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "nota": ("La fase ENSO se diagnostica del Pacífico ecuatorial (ONI), "
                 "no del WRF/GFS. La teleconexión es probabilística, no determinista."),
    }
    (pdir / "assessment.json").write_text(
        json.dumps(assessment, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _write_manifest(
        dataset, "enso",
        files={"oni_raw": pdir / "oni.ascii.txt",
               "oni_table": pdir / "oni.parquet",
               "assessment": pdir / "assessment.json"},
        **{k: assessment[k] for k in ("fase", "intensidad", "oni", "trimestre")},
    )
    for p in pdir.glob("*"):
        _maybe_upload_oss(p)
    log.info("✓ %-18s ONI=%.2f -> %s (%s)", dataset, oni_val, phase, assessment["intensidad"])
    return assessment


def load_enso_assessment() -> dict:
    """Para la app: devuelve el último assessment ENSO (fase + teleconexión)."""
    p = DATA_ROOT / "enso_indices" / "latest.json"
    if not p.exists():
        raise FileNotFoundError("No hay assessment ENSO. Corre fetch_enso_indices().")
    meta = json.loads(p.read_text(encoding="utf-8"))
    ruta = _resolve_manifest_path(meta["files"]["assessment"])
    return json.loads(ruta.read_text(encoding="utf-8"))


def run_enso() -> tuple[int, int]:
    try:
        fetch_enso_indices()
        return 1, 0
    except Exception as e:  # noqa: BLE001
        log.error("✗ enso_indices: %s", e)
        return 0, 1


# --------------------------------------------------------------------------- #
# Orquestación
# --------------------------------------------------------------------------- #
def run_all() -> tuple[int, int]:
    ok = fail = 0
    for runner in (run_models, run_cpt, run_enso):
        o, f = runner(); ok += o; fail += f
    return ok, fail


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="WRF/GFS + CPT + ENSO (extensión del extractor)")
    ap.add_argument("--wrf", action="store_true", help="grillas WRF/GFS")
    ap.add_argument("--cpt", action="store_true", help="predicción mensual CPT")
    ap.add_argument("--enso", action="store_true", help="índices ENSO + fase")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args(argv)
    if not any([args.wrf, args.cpt, args.enso, args.all]):
        args.all = True

    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    ok = fail = 0
    if args.all or args.wrf:
        o, f = run_models(); ok += o; fail += f
    if args.all or args.cpt:
        o, f = run_cpt(); ok += o; fail += f
    if args.all or args.enso:
        o, f = run_enso(); ok += o; fail += f
    log.info("WRF/CPT/ENSO: %d ok, %d con error", ok, fail)
    return 1 if ok == 0 and fail > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
