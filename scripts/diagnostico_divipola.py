"""
scripts/diagnostico_divipola.py
==================================
Compara los códigos DIVIPOLA entre las tres fuentes municipales que la app
cruza (capa de riesgo SNGRD, DIVIPOLA-DANE, Sala de Crisis) y escribe
data_lake/_diagnostico/divipola_no_cruza.csv con los códigos que NO
aparecen en las tres a la vez — típicamente municipios nuevos (p.ej.
Nuevo Belén de Bajirá) o cambios de código entre fuentes. No se corrige
nada automáticamente: es un reporte para revisión humana.

Uso:
    python scripts/diagnostico_divipola.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dane_terridata as dane  # noqa: E402
import sala_crisis as sc  # noqa: E402

REFERENCIA_RIESGO = ROOT / "data" / "reference" / "indices_riesgo_municipal.geojson"
OUT_PATH = ROOT / "data_lake" / "_diagnostico" / "divipola_no_cruza.csv"


def main() -> int:
    geo = json.loads(REFERENCIA_RIESGO.read_text(encoding="utf-8"))
    cod_riesgo = {
        f["properties"].get("MPIO_CCNCT"): f["properties"].get("MPIO_CNMBR")
        for f in geo["features"]
    }

    car = dane.load_caracterizacion()
    cod_dane = dict(zip(car["mpio_codigo"], car["mpio_nombre"])) if car is not None else {}

    emerg = sc.load_emergencias()
    cod_sala = dict(zip(emerg["Codigo Municipio"], emerg["Nombre Municipio"]))

    # 1) Las dos listas "maestras" (indices SNGRD y DIVIPOLA-DANE) DEBERIAN
    #    cubrir los mismos 1.122 municipios. Una diferencia aqui SI es una
    #    discrepancia real de codigo (renombramiento, municipio nuevo, etc.).
    filas = []
    for cod in sorted(set(cod_riesgo) | set(cod_dane)):
        en_riesgo, en_dane = cod in cod_riesgo, cod in cod_dane
        if en_riesgo and en_dane:
            continue
        filas.append({
            "codigo_divipola": cod,
            "nombre": cod_riesgo.get(cod) or cod_dane.get(cod),
            "tipo_discrepancia": "solo en indices_riesgo_sngrd" if en_riesgo else "solo en divipola_dane",
        })

    # 2) Sala de Crisis es un LOG de eventos (cobertura parcial por diseno:
    #    un municipio sin emergencias registradas NO es un error). Solo
    #    reportamos codigos de Sala de Crisis que no existen en NINGUNA
    #    lista maestra -- eso si es un codigo invalido/desactualizado.
    maestro = set(cod_riesgo) | set(cod_dane)
    for cod in sorted(set(cod_sala) - maestro):
        filas.append({
            "codigo_divipola": cod,
            "nombre": cod_sala.get(cod),
            "tipo_discrepancia": "en sala_crisis pero no existe en ninguna lista maestra de municipios",
        })

    df = pd.DataFrame(filas)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"{len(df)} discrepancias de codigo DIVIPOLA -> {OUT_PATH}")
    print(f"(indices_riesgo_sngrd: {len(cod_riesgo)} municipios, divipola_dane: {len(cod_dane)}, "
          f"sala_crisis: {len(cod_sala)} municipios distintos con emergencias)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
