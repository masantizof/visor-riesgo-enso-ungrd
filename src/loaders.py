"""
src/loaders.py
===============
Único punto donde la app toca los scripts extractores. Son wrappers finos,
cacheados con @st.cache_data, sobre las funciones load_*/latest_meta ya
definidas en ideam_extractor.py, ideam_wrf_cpt.py e ideam_enso_risk.py.

No se reimplementa nada de la lógica de lectura de snapshots: solo se
importa y se envuelve. La app NUNCA llama a IDEAM/NOAA en vivo: todo pasa
por el patrón data_lake/{dataset}/latest.json que producen los scripts
(vía cron de GitHub Actions).

Si un dataset aún no tiene snapshot (FileNotFoundError), las funciones
devuelven None en vez de reventar: la página debe mostrarlo con gracia.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

# Los tres scripts extractores viven en la raíz del repo.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ideam_extractor as _ext  # noqa: E402

TTL = 3600  # 1 hora: coherente con la cadencia del cron de ingesta

REFERENCIA_INDICES_RIESGO = ROOT / "data" / "reference" / "indices_riesgo_municipal.geojson"


@st.cache_data(ttl=TTL, show_spinner=False)
def cargar_referencia_indices_riesgo() -> Optional[dict]:
    """Capa estática de referencia (1.122 municipios, índices SNGRD), ya
    simplificada geométricamente (ver scripts/simplificar_indices_riesgo.py).
    No es un snapshot de data_lake: es insumo fijo para el cruce ENSO×riesgo."""
    import json
    if not REFERENCIA_INDICES_RIESGO.exists():
        return None
    return json.loads(REFERENCIA_INDICES_RIESGO.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Catálogo: dataset_id -> (nombre visible, tipo, descripción corta)
# --------------------------------------------------------------------------- #
CATALOGO = {
    # Vectoriales
    "precipitacion_diaria":   ("Precipitación diaria por estación", "puntos", "IDEAM (ArcGIS OSPA)"),
    "temperatura_max_diaria": ("Temperatura máxima diaria por estación", "puntos", "IDEAM (ArcGIS OSPA)"),
    "alertas_hidrologicas":   ("Alertas hidrológicas vigentes", "poligonos", "IDEAM (ArcGIS OSPA)"),
    "areas_hidrograficas":    ("Áreas hidrográficas (referencia)", "poligonos", "IDEAM (ArcGIS OSPA)"),
    "zonas_hidrograficas":    ("Zonas hidrográficas (referencia)", "poligonos", "IDEAM (ArcGIS OSPA)"),
    "alertas_idd":            ("Alertas por deslizamientos (municipio)", "poligonos", "IDEAM (ArcGIS OSPA)"),
    "alertas_icv":            ("Alertas por incendios de cobertura vegetal", "poligonos", "IDEAM (ArcGIS OSPA)"),
    "amenaza_idd":            ("Amenaza por deslizamientos", "raster", "IDEAM (ArcGIS OSPA)"),
    "amenaza_icv":            ("Amenaza por incendios de cobertura vegetal", "raster", "IDEAM (ArcGIS OSPA)"),
    "municipios":              ("Municipios (referencia)", "poligonos", "IDEAM (ArcGIS OSPA)"),
    "departamentos":           ("Departamentos e islas (referencia)", "poligonos", "IDEAM (ArcGIS OSPA)"),
    # Ráster
    "pronostico_precip_24h":  ("Pronóstico de precipitación 24h", "raster", "IDEAM (ArcGIS OSPA)"),
    "acumulado_24h":          ("Precipitación acumulada 24h", "raster", "IDEAM (ArcGIS OSPA)"),
    "acumulado_72h":          ("Precipitación acumulada 72h", "raster", "IDEAM (ArcGIS OSPA)"),
    "hidroestimador_noaa":    ("Hidroestimador satelital NOAA", "raster", "IDEAM / NOAA"),
    # Tablas BART
    "bart_dia":               ("Reporte diario BART", "tabla", "IDEAM (BART)"),
    "bart_tresdias":          ("Reporte 3 días BART", "tabla", "IDEAM (BART)"),
    "bart_precipitacion":     ("Precipitación diaria (BART)", "tabla", "IDEAM (BART)"),
    "bart_temp_min":          ("Temperatura mínima diaria (BART)", "tabla", "IDEAM (BART)"),
    "bart_temp_med":          ("Temperatura media diaria (BART)", "tabla", "IDEAM (BART)"),
    "bart_temp_max":          ("Temperatura máxima diaria (BART)", "tabla", "IDEAM (BART)"),
    "acumulado_lluvia_mes":   ("Acumulado de lluvia del mes", "tabla", "IDEAM (BART)"),
    "acumulado_tempmax_mes":  ("Acumulado de temperatura máxima del mes", "tabla", "IDEAM (BART)"),
    "reporte_cordoba_mes":    ("Reporte Córdoba del mes", "tabla", "IDEAM (BART)"),
    # Modelos / CPT / ENSO
    "wrf00_netcdf":           ("WRF 00Z Colombia (NetCDF)", "grid", "IDEAM"),
    "wrf00_tif":              ("WRF 00Z Colombia (GeoTIFF)", "grid", "IDEAM"),
    "gfs06_grib2":            ("GFS 06Z Colombia (GRIB2)", "grid", "IDEAM / NOAA"),
    "cpt_prediccion_precipitacion": ("Predicción mensual CPT — Precipitación", "image_set", "IDEAM"),
    "cpt_prediccion_temperatura":   ("Predicción mensual CPT — Temperatura", "image_set", "IDEAM"),
    "cpt_prediccion_viento":        ("Predicción mensual CPT — Viento", "image_set", "IDEAM"),
    "enso_indices":            ("Índices ENSO (ONI) y fase", "enso", "NOAA/CPC"),
    "enso_riesgo":             ("Cruce ENSO × riesgo municipal (SNGRD)", "cruce", "UNGRD (derivado)"),
}


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FileNotFoundError:
        return None


@st.cache_data(ttl=TTL, show_spinner=False)
def dataset_disponible(dataset: str) -> bool:
    return _safe(_ext.latest_meta, dataset) is not None


@st.cache_data(ttl=TTL, show_spinner=False)
def cargar_geojson(dataset: str) -> Optional[dict]:
    return _safe(_ext.load_latest_geojson, dataset)


@st.cache_data(ttl=TTL, show_spinner=False)
def cargar_tabla(dataset: str) -> Optional[pd.DataFrame]:
    return _safe(_ext.load_latest_table, dataset)


@st.cache_data(ttl=TTL, show_spinner=False)
def cargar_tabla_con_respaldo_xlsx(dataset: str) -> tuple[Optional[pd.DataFrame], Optional[str]]:
    """Como cargar_tabla, pero si el parquet no existe (Excel con tipos mixtos que
    el extractor no pudo tabular), intenta una lectura tolerante del .xlsx crudo
    para al menos mostrarlo en pantalla. Devuelve (df_o_None, ruta_xlsx_o_None)."""
    df = cargar_tabla(dataset)
    m = metadatos(dataset)
    ruta_xlsx = m["files"].get("xlsx") if m else None
    if df is not None:
        return df, ruta_xlsx
    if ruta_xlsx:
        try:
            df = pd.read_excel(ruta_xlsx, engine="openpyxl", dtype=str)
        except Exception:  # noqa: BLE001
            df = None
    return df, ruta_xlsx


@st.cache_data(ttl=TTL, show_spinner=False)
def cargar_raster(dataset: str):
    """(ruta_png:str, bounds:list, leyenda:dict) o None si no hay snapshot."""
    r = _safe(_ext.load_latest_raster, dataset)
    if r is None:
        return None
    png, bounds, legend = r
    return str(png), bounds, legend


@st.cache_data(ttl=TTL, show_spinner=False)
def metadatos(dataset: str) -> Optional[dict]:
    return _safe(_ext.latest_meta, dataset)


@st.cache_data(ttl=TTL, show_spinner=False)
def datasets_disponibles() -> list[str]:
    return _ext.list_datasets()


@st.cache_data(ttl=TTL, show_spinner=False)
def cargar_assessment_enso() -> Optional[dict]:
    import ideam_wrf_cpt as _wrf
    return _safe(_wrf.load_enso_assessment)


@st.cache_data(ttl=TTL, show_spinner=False)
def cargar_riesgo_enso_geojson() -> Optional[dict]:
    import ideam_enso_risk as _risk
    return _safe(_risk.load_enso_risk_geojson)


@st.cache_data(ttl=TTL, show_spinner=False)
def cargar_riesgo_enso_tabla() -> Optional[pd.DataFrame]:
    import ideam_enso_risk as _risk
    return _safe(_risk.load_enso_risk_table)


@st.cache_data(ttl=TTL, show_spinner=False)
def cargar_set_imagenes(dataset: str) -> Optional[dict]:
    """Para datasets tipo image_set (CPT): {clave: ruta_png} desde el manifiesto."""
    m = metadatos(dataset)
    if m is None:
        return None
    return {k: v for k, v in m.get("files", {}).items()}
