"""

Desarrollado por: Moisés Santizo Fuentes, Juni 2026 - UNGRD / Subdirección de Conocimiento del Riesgo.
ideam_enso_risk.py
==================
Cruce ENSO × índices de riesgo municipal (SNGRD) para Colombia.

Producto para la Subdirección de Conocimiento del Riesgo (UNGRD). Adapta el
enfoque de NOAA "ENSO Climate Risks" al territorio nacional: dada la fase ENSO
vigente (ONI), resalta los municipios cuyo riesgo asociado a precipitación y
temperatura se ve AMPLIFICADO por esa fase, cruzando la señal climática con la
capa de índices de riesgo del SNGRD.

Lógica:
  El Niño  (seco/cálido)  -> amplifica: incendios, desabastecimiento, déficit hídrico
  La Niña  (húmedo)       -> amplifica: inundaciones, crecientes, avenidas, mov. en masa
  Neutral                 -> sin señal ENSO dominante (panel informativo)

Encaja con el flujo: usa la fase del módulo ENSO (ideam_wrf_cpt) y deja salidas
con el mismo patrón (GeoJSON + parquet + manifiesto) para que la app las lea.

Salidas (por corrida):
  - <root>/enso_riesgo/dt=YYYY-MM-DD/enso_riesgo_municipal.geojson  (mapa)
  - <root>/enso_riesgo/dt=YYYY-MM-DD/enso_riesgo_municipal.parquet  (tabla/descarga)
  - <root>/enso_riesgo/dt=YYYY-MM-DD/rollup_departamental.json      (vista pública)
  - latest.json

Uso:
    python ideam_enso_risk.py --indices data/reference/indices_riesgo_municipal.geojson
    # toma la fase del último assessment ENSO; o se fuerza con --fase "El Niño"
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

from ideam_extractor import (
    DATA_ROOT, log, _partition_dir, _write_manifest, _maybe_upload_oss,
    _resolve_manifest_path,
)

# --------------------------------------------------------------------------- #
# Metadatos de los índices: campo -> (nombre legible, fase que amplifica, condición)
# --------------------------------------------------------------------------- #
INDEX_META = {
    "I_IF":       ("Incendios de cobertura vegetal", "El Niño", "seco/cálido"),
    "I_Desabast": ("Desabastecimiento hídrico",       "El Niño", "seco"),
    "I_DHTLL_In": ("Déficit hídrico (lluvia)",        "El Niño", "seco"),
    "I_DHTS_I_D": ("Déficit hídrico (sequía)",        "El Niño", "seco"),
    "I_Inundaci": ("Inundaciones",                    "La Niña", "húmedo"),
    "I_Crecient": ("Crecientes súbitas",              "La Niña", "húmedo"),
    "I_AVT":      ("Avenidas torrenciales",           "La Niña", "húmedo"),
    "I_MovMasa":  ("Movimientos en masa",             "La Niña", "húmedo"),
    "I_Vendaval": ("Vendavales",                      "Ambas",   "transición/convección"),
}

CODE_FIELD = "MPIO_CCNCT"
MPIO_FIELD = "MPIO_CNMBR"
DPTO_FIELD = "DPTO_CNMBR"


def relevant_indices(phase: str) -> list[str]:
    """Campos de índice que la fase dada amplifica (incluye 'Ambas' como secundario)."""
    return [f for f, (_, ph, _) in INDEX_META.items() if ph in (phase, "Ambas")]


def classify(score: Optional[float]) -> str:
    if score is None:
        return "sin dato"
    if score >= 0.66:
        return "alto"
    if score >= 0.33:
        return "medio"
    return "bajo"


# --------------------------------------------------------------------------- #
# Núcleo: cruce fase × índices por municipio
# --------------------------------------------------------------------------- #
def municipal_enso_risk(features: list[dict], phase: str) -> list[dict]:
    """Calcula el riesgo amplificado por ENSO por municipio.

    Score = máximo de los índices relevantes para la fase (peor amenaza),
    y se listan las amenazas que contribuyen, ordenadas por valor.
    """
    fields = relevant_indices(phase)
    out = []
    for f in features:
        p = f.get("properties", {})
        contribs = []
        for fld in fields:
            v = p.get(fld)
            if isinstance(v, (int, float)):
                contribs.append((INDEX_META[fld][0], round(float(v), 3)))
        contribs.sort(key=lambda x: x[1], reverse=True)
        score = contribs[0][1] if contribs else None
        out.append({
            "cod_dane": p.get(CODE_FIELD),
            "municipio": p.get(MPIO_FIELD),
            "departamento": p.get(DPTO_FIELD),
            "fase_enso": phase,
            "enso_score": score,
            "enso_nivel": classify(score),
            "amenazas": "; ".join(f"{n} ({v})" for n, v in contribs) or None,
            "amenaza_principal": contribs[0][0] if contribs else None,
        })
    return out


def public_narrative(rec: dict) -> str:
    """Frase apta para consulta ciudadana."""
    if rec["enso_nivel"] in ("sin dato",):
        return (f"En fase {rec['fase_enso']}, {rec['municipio']} ({rec['departamento']}) "
                f"no registra índices de riesgo asociados a esta fase.")
    cond = "más seco y cálido" if rec["fase_enso"] == "El Niño" else (
        "más húmedo" if rec["fase_enso"] == "La Niña" else "cercano a lo normal")
    return (f"En fase {rec['fase_enso']} (condiciones {cond}), {rec['municipio']} "
            f"({rec['departamento']}) presenta riesgo {rec['enso_nivel'].upper()} "
            f"asociado principalmente a {rec['amenaza_principal']}.")


# --------------------------------------------------------------------------- #
# Construcción de salidas
# --------------------------------------------------------------------------- #
def build(indices_path: Path, phase: str) -> dict:
    geo = json.loads(Path(indices_path).read_text(encoding="utf-8"))
    feats = geo["features"]
    records = municipal_enso_risk(feats, phase)
    by_code = {r["cod_dane"]: r for r in records}

    # GeoJSON enriquecido (para el mapa): agrega props enso_* a cada municipio.
    for f in feats:
        code = f["properties"].get(CODE_FIELD)
        r = by_code.get(code, {})
        f["properties"].update({
            "enso_fase": r.get("fase_enso"),
            "enso_score": r.get("enso_score"),
            "enso_nivel": r.get("enso_nivel"),
            "enso_amenazas": r.get("amenazas"),
            "enso_narrativa": public_narrative(r) if r else None,
        })

    pdir = _partition_dir("enso_riesgo")
    geojson_path = pdir / "enso_riesgo_municipal.geojson"
    parquet_path = pdir / "enso_riesgo_municipal.parquet"
    rollup_path = pdir / "rollup_departamental.json"

    geojson_path.write_text(json.dumps(geo, ensure_ascii=False), encoding="utf-8")

    df = pd.DataFrame(records)
    df["_ingested_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    df.to_parquet(parquet_path, index=False)

    # Rollup departamental (vista pública simple): nº municipios por nivel.
    rollup = (
        df.groupby(["departamento", "enso_nivel"]).size()
        .unstack(fill_value=0).to_dict(orient="index")
    )
    rollup_path.write_text(json.dumps(rollup, ensure_ascii=False, indent=2), encoding="utf-8")

    n_alto = int((df["enso_nivel"] == "alto").sum())
    n_medio = int((df["enso_nivel"] == "medio").sum())
    _write_manifest(
        "enso_riesgo", "enso_risk_cross",
        files={"geojson": geojson_path, "parquet": parquet_path, "rollup": rollup_path},
        fase_enso=phase, n_municipios=len(records),
        n_alto=n_alto, n_medio=n_medio,
        indices_evaluados=relevant_indices(phase),
        nota=("Cruce fase ENSO × índices de riesgo SNGRD. La fase amplifica el "
              "riesgo; no lo causa. Producto de apoyo a SAT (Conocimiento del Riesgo)."),
    )
    for pth in (geojson_path, parquet_path, rollup_path):
        _maybe_upload_oss(pth)

    log.info("✓ enso_riesgo  fase=%s  alto=%d  medio=%d  (de %d munis)",
             phase, n_alto, n_medio, len(records))
    return {"fase": phase, "n_alto": n_alto, "n_medio": n_medio,
            "df": df, "geojson_path": geojson_path}


# --------------------------------------------------------------------------- #
# API para la app
# --------------------------------------------------------------------------- #
def load_enso_risk_geojson() -> dict:
    p = DATA_ROOT / "enso_riesgo" / "latest.json"
    meta = json.loads(p.read_text(encoding="utf-8"))
    ruta = _resolve_manifest_path(meta["files"]["geojson"])
    return json.loads(ruta.read_text(encoding="utf-8"))


def load_enso_risk_table() -> pd.DataFrame:
    p = DATA_ROOT / "enso_riesgo" / "latest.json"
    meta = json.loads(p.read_text(encoding="utf-8"))
    ruta = _resolve_manifest_path(meta["files"]["parquet"])
    return pd.read_parquet(ruta)


def _phase_from_assessment() -> str:
    """Toma la fase del último assessment ENSO; si no hay, asume Neutral."""
    try:
        from ideam_wrf_cpt import load_enso_assessment
        return load_enso_assessment().get("fase", "Neutral")
    except Exception:  # noqa: BLE001
        return "Neutral"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Cruce ENSO × índices de riesgo municipal")
    ap.add_argument("--indices", required=True, help="GeoJSON de índices de riesgo municipal")
    ap.add_argument("--fase", choices=["El Niño", "La Niña", "Neutral"],
                    help="forzar fase; por defecto la del assessment ENSO")
    args = ap.parse_args(argv)

    phase = args.fase or _phase_from_assessment()
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    build(Path(args.indices), phase)
    return 0


if __name__ == "__main__":
    sys.exit(main())
