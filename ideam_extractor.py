"""
ideam_extractor.py
==================
Extractor diario de datos IDEAM (OSPA) y PUENTE hacia la app Streamlit.

Doble propósito:
  1) Como SCRIPT (lo corre el cron / GitHub Actions): toma un snapshot de cada
     fuente, lo deja particionado por fecha en un almacén local (y opcionalmente
     lo sube a OSS de Alibaba), construyendo el histórico que IDEAM no conserva.
  2) Como MÓDULO (lo importa la app): expone load_latest_* para leer el último
     snapshot disponible sin tocar a IDEAM en vivo.

Diseño clave:
  - El visor NUNCA consulta a IDEAM directamente -> resiliencia + histórico.
  - Vectorial ArcGIS  -> GeoJSON vía /query (paginado, outSR=4326) -> .geojson + .parquet
  - Ráster ArcGIS     -> imagen vía /export + /legend                -> .png + _legend.json
  - BART Excel        -> HEAD (Last-Modified) -> GET con User-Agent   -> .xlsx + .parquet
  - Deduplicado por hash de contenido: si no cambió, no se reescribe.
  - Cada dataset deja un latest.json (manifiesto) para lectura O(1) desde la app.

Uso CLI:
    python ideam_extractor.py --all
    python ideam_extractor.py --vector --raster
    python ideam_extractor.py --bart
    python ideam_extractor.py --verify        # resuelve AMENAZA_IDD / AMENAZA_ICV

Uso desde la app:
    from ideam_extractor import load_latest_geojson, load_latest_table, load_latest_raster
    fc   = load_latest_geojson("alertas_idd")          # dict FeatureCollection -> folium
    df   = load_latest_table("acumulado_lluvia_mes")    # DataFrame -> st.dataframe
    png, bounds, legend = load_latest_raster("acumulado_24h")
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter

try:  # urllib3 viene con requests; el import explícito permite configurar Retry
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover
    Retry = None


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #
# Ancla al directorio de este archivo (no al cwd del proceso): en Streamlit
# Community Cloud el directorio de trabajo al arrancar no es de fiar, y una
# ruta relativa tipo Path("data_lake") puede no apuntar al repo.
_DEFAULT_DATA_ROOT = Path(__file__).resolve().parent / "data_lake"
DATA_ROOT = Path(os.getenv("IDEAM_DATA_ROOT", str(_DEFAULT_DATA_ROOT)))

ARCGIS_BASE = (
    "https://visualizador.ideam.gov.co/gisserver/rest/services/StoryMaps_IDA"
)
BART_BASE = "https://bart.ideam.gov.co/ospa/Alertas/datos_diarios_preliminares"

# UA de navegador: BART bloquea clientes "robot"; identifícate de forma honesta.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; UNGRD-VisorAlertas/1.0; "
        "consumo de datos públicos OSPA-IDEAM)"
    )
}

# bbox nacional (lon_min, lat_min, lon_max, lat_max) incluyendo San Andrés.
COLOMBIA_BBOX = (-82.0, -4.5, -66.0, 13.5)
RASTER_SIZE = (1200, 1400)          # px del PNG exportado
TIMEOUT = 60
PAGE_SIZE = 1000                     # se ajusta al maxRecordCount real del servicio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ideam")


# --------------------------------------------------------------------------- #
# Catálogo de fuentes
# --------------------------------------------------------------------------- #
# Vectoriales -> GeoJSON. (dataset_id: (servicio, layer_id, descripción))
VECTOR_LAYERS = {
    "precipitacion_diaria":  ("Datos_Precipitacion", 0,  "Precipitación diaria por estación"),
    "temperatura_max_diaria":("Datos_TMaxima",       0,  "Temperatura máxima diaria por estación"),
    "alertas_hidrologicas":  ("Alertas_Hidrologicas",2,  "Alertas hidrológicas vigentes"),
    "areas_hidrograficas":   ("Alertas_Hidrologicas",0,  "Áreas hidrográficas (referencia)"),
    "zonas_hidrograficas":   ("Alertas_Hidrologicas",1,  "Zonas hidrográficas (referencia)"),
    "alertas_idd":           ("Alertas__IDD",        1,  "Alertas por deslizamientos (municipio)"),
    "alertas_icv":           ("Alertas_ICV",         2,  "Alertas por incendios cobertura vegetal"),
    "municipios":            ("Datos_Precipitacion", 22, "Municipios (referencia/regionalización)"),
    "departamentos":         ("Datos_Precipitacion", 3,  "Departamentos e islas (referencia)"),
}

# Ráster -> imagen. (dataset_id: (servicio, layer_id, descripción))
RASTER_LAYERS = {
    "pronostico_precip_24h": ("Pronostico_24_horas",      6, "Pronóstico precipitación 24h"),
    "acumulado_24h":         ("Precipitacion__Acumulada", 2, "Precipitación acumulada 24h"),
    "acumulado_72h":         ("Precipitacion__Acumulada", 3, "Precipitación acumulada 72h"),
    "hidroestimador_noaa":   ("Precipitacion__Acumulada", 4, "Hidroestimador satelital NOAA"),
}

# Tipo no confirmado: el extractor lee ?f=json y enruta según 'type'.
VERIFY_LAYERS = {
    "amenaza_idd": ("Alertas__IDD", 2, "Amenaza por deslizamientos (tipo por verificar)"),
    "amenaza_icv": ("Alertas_ICV",  3, "Amenaza por incendios (tipo por verificar)"),
}

# BART diarios (se sobrescriben). (dataset_id: nombre de archivo)
BART_DAILY = {
    "bart_dia":            "dia.xlsx",
    "bart_tresdias":       "tresdias.xlsx",
    "bart_precipitacion":  "precipitacion.xlsx",
    "bart_temp_min":       "temperaturamin.xlsx",
    "bart_temp_med":       "temperaturamed.xlsx",
    "bart_temp_max":       "temperaturamax.xlsx",
}

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def bart_monthly_candidates(today: Optional[dt.date] = None) -> dict[str, list[str]]:
    """Genera nombres candidatos de los acumulados del mes en curso.

    El servidor usa sufijo de año de 2 dígitos (p. ej. '-26') y el mes con
    distintas convenciones; probamos varias y el extractor se queda con la
    primera que exista (HEAD 200).
    """
    today = today or dt.date.today()
    mes_full = MESES[today.month - 1]
    mes_abbr3 = mes_full[:3]                  # 'jun', 'may'...
    yy = today.strftime("%y")                 # '26'
    return {
        "acumulado_lluvia_mes": [
            f"lluvia-{mes_full}-{yy}.xlsx",
        ],
        "acumulado_tempmax_mes": [
            f"Temp-max-{mes_full}-{yy}.xlsx",
        ],
        "reporte_cordoba_mes": [
            f"CORDOBA_{mes_abbr3.upper()}{yy}.xlsx",   # CORDOBA_JUN26.xlsx
            f"CORDOBA_{mes_full.upper()}{yy}.xlsx",     # CORDOBA_MAYO26.xlsx
        ],
    }


# --------------------------------------------------------------------------- #
# HTTP con reintentos
# --------------------------------------------------------------------------- #
def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    if Retry is not None:
        retry = Retry(
            total=3, backoff_factor=2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "HEAD"]),
        )
        adapter = HTTPAdapter(max_retries=retry)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
    return s


SESSION = _session()


# --------------------------------------------------------------------------- #
# Utilidades de almacén
# --------------------------------------------------------------------------- #
def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _partition_dir(dataset: str, today: Optional[dt.date] = None) -> Path:
    today = today or dt.date.today()
    d = DATA_ROOT / dataset / f"dt={today.isoformat()}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _last_hash_path(dataset: str) -> Path:
    return DATA_ROOT / dataset / "_last_hash.txt"


def _changed(dataset: str, content_hash: str) -> bool:
    """True si el contenido difiere del último snapshot (o si no hay previo)."""
    p = _last_hash_path(dataset)
    if p.exists() and p.read_text(encoding="utf-8").strip() == content_hash:
        return False
    return True


def _commit_hash(dataset: str, content_hash: str) -> None:
    p = _last_hash_path(dataset)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content_hash, encoding="utf-8")


def _write_manifest(dataset: str, kind: str, files: dict, **extra) -> None:
    """latest.json: puntero que la app lee para hallar el último snapshot."""
    manifest = {
        "dataset": dataset,
        "kind": kind,
        "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "files": {k: Path(v).as_posix() for k, v in files.items()},
        **extra,
    }
    (DATA_ROOT / dataset).mkdir(parents=True, exist_ok=True)
    (DATA_ROOT / dataset / "latest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _maybe_upload_oss(local_path: Path) -> None:
    """Sube a OSS de Alibaba si están las credenciales en el entorno.

    Variables: OSS_ENDPOINT, OSS_BUCKET, OSS_ACCESS_KEY_ID, OSS_ACCESS_KEY_SECRET
    Si falta oss2 o las variables, no hace nada (no-op).
    """
    endpoint = os.getenv("OSS_ENDPOINT")
    bucket_name = os.getenv("OSS_BUCKET")
    key_id = os.getenv("OSS_ACCESS_KEY_ID")
    key_secret = os.getenv("OSS_ACCESS_KEY_SECRET")
    if not all([endpoint, bucket_name, key_id, key_secret]):
        return
    try:
        import oss2  # import perezoso: solo si se va a usar
    except ImportError:
        log.warning("oss2 no instalado; se omite subida a OSS de %s", local_path.name)
        return
    auth = oss2.Auth(key_id, key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)
    key = str(local_path.relative_to(DATA_ROOT)).replace(os.sep, "/")
    bucket.put_object_from_file(f"bronze/{key}", str(local_path))
    log.info("OSS <- %s", key)


# --------------------------------------------------------------------------- #
# ArcGIS: introspección y vectorial
# --------------------------------------------------------------------------- #
def arcgis_layer_info(service: str, layer_id: int) -> dict:
    url = f"{ARCGIS_BASE}/{service}/MapServer/{layer_id}"
    r = SESSION.get(url, params={"f": "json"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_vector(dataset: str, service: str, layer_id: int, descripcion: str = "") -> bool:
    """Descarga una capa vectorial completa como GeoJSON (paginado, WGS84).

    Devuelve True si escribió un snapshot nuevo, False si no hubo cambios.
    """
    base = f"{ARCGIS_BASE}/{service}/MapServer/{layer_id}"
    info = arcgis_layer_info(service, layer_id)
    max_rc = int(info.get("maxRecordCount", PAGE_SIZE)) or PAGE_SIZE
    page = min(max_rc, PAGE_SIZE)

    features: list[dict] = []
    offset = 0
    while True:
        params = {
            "where": "1=1",
            "outFields": "*",
            "outSR": 4326,
            "returnGeometry": "true",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": page,
        }
        r = SESSION.get(f"{base}/query", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        chunk = r.json()
        batch = chunk.get("features", [])
        features.extend(batch)
        if len(batch) < page:
            break
        offset += page
        if offset > 500_000:  # cinturón de seguridad
            log.warning("%s: corte de paginación por exceso de registros", dataset)
            break

    fc = {"type": "FeatureCollection", "features": features}
    raw = json.dumps(fc, ensure_ascii=False).encode("utf-8")
    content_hash = _sha256(raw)

    if not _changed(dataset, content_hash):
        log.info("· %-24s sin cambios (%d feats)", dataset, len(features))
        return False

    pdir = _partition_dir(dataset)
    geojson_path = pdir / f"{dataset}.geojson"
    parquet_path = pdir / f"{dataset}.parquet"
    geojson_path.write_bytes(raw)

    # Atributos -> Parquet (para tablas/descarga); con linaje.
    props = [f.get("properties", {}) for f in features]
    df = pd.json_normalize(props) if props else pd.DataFrame()
    df["_ingested_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    df["_source_url"] = base
    df.to_parquet(parquet_path, index=False)

    _commit_hash(dataset, content_hash)
    _write_manifest(
        dataset, "vector",
        files={"geojson": geojson_path, "parquet": parquet_path},
        source_url=base, descripcion=descripcion,
        n_features=len(features), content_hash=content_hash,
        geometry_type=info.get("geometryType"),
    )
    for p in (geojson_path, parquet_path):
        _maybe_upload_oss(p)
    log.info("✓ %-24s %d feats -> snapshot nuevo", dataset, len(features))
    return True


# --------------------------------------------------------------------------- #
# ArcGIS: ráster -> imagen + leyenda
# --------------------------------------------------------------------------- #
def fetch_raster(dataset: str, service: str, layer_id: int, descripcion: str = "") -> bool:
    base = f"{ARCGIS_BASE}/{service}/MapServer"
    lon_min, lat_min, lon_max, lat_max = COLOMBIA_BBOX
    params = {
        "bbox": f"{lon_min},{lat_min},{lon_max},{lat_max}",
        "bboxSR": 4326, "imageSR": 4326,
        "size": f"{RASTER_SIZE[0]},{RASTER_SIZE[1]}",
        "format": "png32", "transparent": "true", "dpi": 96,
        "layers": f"show:{layer_id}", "f": "image",
    }
    r = SESSION.get(f"{base}/export", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    img = r.content
    content_hash = _sha256(img)

    if not _changed(dataset, content_hash):
        log.info("· %-24s sin cambios (ráster)", dataset)
        return False

    # Leyenda (para reproducir la simbología en la UI).
    legend = {}
    try:
        lr = SESSION.get(f"{base}/legend", params={"f": "json"}, timeout=TIMEOUT)
        if lr.ok:
            legend = lr.json()
    except requests.RequestException:
        pass

    pdir = _partition_dir(dataset)
    png_path = pdir / f"{dataset}.png"
    legend_path = pdir / f"{dataset}_legend.json"
    png_path.write_bytes(img)
    legend_path.write_text(json.dumps(legend, ensure_ascii=False, indent=2), encoding="utf-8")

    _commit_hash(dataset, content_hash)
    # bounds en formato folium [[lat_min,lon_min],[lat_max,lon_max]]
    bounds = [[lat_min, lon_min], [lat_max, lon_max]]
    _write_manifest(
        dataset, "raster",
        files={"png": png_path, "legend": legend_path},
        source_url=f"{base}/export", descripcion=descripcion,
        bounds=bounds, content_hash=content_hash,
    )
    for p in (png_path, legend_path):
        _maybe_upload_oss(p)
    log.info("✓ %-24s ráster -> snapshot nuevo", dataset)
    return True


# --------------------------------------------------------------------------- #
# Capas por verificar -> enruta según tipo real
# --------------------------------------------------------------------------- #
def fetch_verify(dataset: str, service: str, layer_id: int, descripcion: str = "") -> bool:
    info = arcgis_layer_info(service, layer_id)
    tipo = (info.get("type") or "").lower()
    if "raster" in tipo:
        log.info("· %s es Raster Layer -> export", dataset)
        return fetch_raster(dataset, service, layer_id, descripcion)
    log.info("· %s es Feature Layer (%s) -> GeoJSON", dataset, info.get("geometryType"))
    return fetch_vector(dataset, service, layer_id, descripcion)


# --------------------------------------------------------------------------- #
# BART: Excel con verificación de cambio por Last-Modified
# --------------------------------------------------------------------------- #
def _bart_signature(filename: str) -> Optional[str]:
    """HEAD -> firma (Last-Modified + tamaño). None si no existe (404)."""
    url = f"{BART_BASE}/{filename}"
    try:
        r = SESSION.head(url, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    return f"{r.headers.get('Last-Modified','')}|{r.headers.get('Content-Length','')}"


def fetch_bart(dataset: str, filename: str, descripcion: str = "") -> bool:
    sig = _bart_signature(filename)
    if sig is None:
        log.warning("· %-24s no disponible (%s)", dataset, filename)
        return False
    if not _changed(dataset, sig):     # firma como hash de cambio (barato, sin GET)
        log.info("· %-24s sin cambios (Last-Modified)", dataset)
        return False

    url = f"{BART_BASE}/{filename}"
    r = SESSION.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    blob = r.content

    pdir = _partition_dir(dataset)
    xlsx_path = pdir / filename
    parquet_path = pdir / f"{dataset}.parquet"
    xlsx_path.write_bytes(blob)

    # Parseo tolerante: si falla, igual conservamos el crudo (bronze real).
    wrote_parquet = False
    try:
        df = pd.read_excel(io.BytesIO(blob), engine="openpyxl")
        df.columns = [str(c).strip() for c in df.columns]   # normaliza encabezados
        df["_ingested_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        df["_source_url"] = url
        df.to_parquet(parquet_path, index=False)
        wrote_parquet = True
    except Exception as e:  # noqa: BLE001
        log.warning("· %s: Excel no parseado (%s); se guarda solo crudo", dataset, e)

    _commit_hash(dataset, sig)
    files = {"xlsx": xlsx_path}
    if wrote_parquet:
        files["parquet"] = parquet_path
    _write_manifest(
        dataset, "table", files=files,
        source_url=url, descripcion=descripcion, signature=sig,
    )
    for p in files.values():
        _maybe_upload_oss(p)
    log.info("✓ %-24s -> snapshot nuevo", dataset)
    return True


def fetch_bart_monthly() -> int:
    """Recorre los acumulados del mes en curso, probando nombres candidatos."""
    n = 0
    for dataset, candidates in bart_monthly_candidates().items():
        for fname in candidates:
            if _bart_signature(fname) is not None:
                if fetch_bart(dataset, fname, f"Acumulado mensual ({fname})"):
                    n += 1
                break
        else:
            log.warning("· %-24s sin candidato disponible este mes", dataset)
    return n


# --------------------------------------------------------------------------- #
# API de lectura para la app Streamlit (el "puente")
# --------------------------------------------------------------------------- #
def _resolve_manifest_path(path_str: str) -> Path:
    """Convierte una ruta guardada en un manifiesto en una ruta válida en ESTE
    entorno. Manifiestos viejos (generados en Windows, o antes de anclar
    DATA_ROOT) pueden traer backslash y/o ser relativas al cwd de aquel
    momento: normalizamos separador y anclamos al DATA_ROOT actual en vez de
    confiar en el cwd del proceso que lee."""
    p = Path(path_str.replace("\\", "/"))
    if p.is_absolute():
        return p
    return DATA_ROOT.parent / p


def _manifest(dataset: str) -> dict:
    p = DATA_ROOT / dataset / "latest.json"
    if not p.exists():
        raise FileNotFoundError(
            f"No hay snapshot de '{dataset}'. Corre el extractor primero."
        )
    manifest = json.loads(p.read_text(encoding="utf-8"))
    if "files" in manifest:
        manifest["files"] = {k: str(_resolve_manifest_path(v)) for k, v in manifest["files"].items()}
    return manifest


def load_latest_geojson(dataset: str) -> dict:
    """FeatureCollection (dict) lista para folium.GeoJson."""
    m = _manifest(dataset)
    return json.loads(Path(m["files"]["geojson"]).read_text(encoding="utf-8"))


def load_latest_table(dataset: str) -> pd.DataFrame:
    """DataFrame de atributos (para st.dataframe / descarga)."""
    m = _manifest(dataset)
    key = "parquet" if "parquet" in m["files"] else None
    if key is None:
        raise FileNotFoundError(f"'{dataset}' no tiene tabla parquet disponible.")
    return pd.read_parquet(m["files"][key])


def load_latest_raster(dataset: str) -> tuple[Path, list, dict]:
    """(ruta_png, bounds_folium, leyenda_dict) para ImageOverlay."""
    m = _manifest(dataset)
    png = Path(m["files"]["png"])
    legend = json.loads(Path(m["files"]["legend"]).read_text(encoding="utf-8")) if "legend" in m["files"] else {}
    return png, m.get("bounds", []), legend


def latest_meta(dataset: str) -> dict:
    """Manifiesto (fecha de actualización, fuente, nº features, etc.)."""
    return _manifest(dataset)


def list_datasets() -> list[str]:
    if not DATA_ROOT.exists():
        return []
    return sorted(p.name for p in DATA_ROOT.iterdir()
                  if (p / "latest.json").exists())


# --------------------------------------------------------------------------- #
# Orquestación
# --------------------------------------------------------------------------- #
def run_vector() -> tuple[int, int]:
    ok = fail = 0
    for ds, (svc, lid, desc) in VECTOR_LAYERS.items():
        try:
            fetch_vector(ds, svc, lid, desc); ok += 1
        except Exception as e:  # noqa: BLE001
            log.error("✗ %s: %s", ds, e); fail += 1
    return ok, fail


def run_raster() -> tuple[int, int]:
    ok = fail = 0
    for ds, (svc, lid, desc) in RASTER_LAYERS.items():
        try:
            fetch_raster(ds, svc, lid, desc); ok += 1
        except Exception as e:  # noqa: BLE001
            log.error("✗ %s: %s", ds, e); fail += 1
    return ok, fail


def run_verify() -> tuple[int, int]:
    ok = fail = 0
    for ds, (svc, lid, desc) in VERIFY_LAYERS.items():
        try:
            fetch_verify(ds, svc, lid, desc); ok += 1
        except Exception as e:  # noqa: BLE001
            log.error("✗ %s: %s", ds, e); fail += 1
    return ok, fail


def run_bart() -> tuple[int, int]:
    ok = fail = 0
    for ds, fname in BART_DAILY.items():
        try:
            fetch_bart(ds, fname, "BART diario"); ok += 1
        except Exception as e:  # noqa: BLE001
            log.error("✗ %s: %s", ds, e); fail += 1
    try:
        fetch_bart_monthly(); ok += 1
    except Exception as e:  # noqa: BLE001
        log.error("✗ bart_monthly: %s", e); fail += 1
    return ok, fail


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Extractor diario IDEAM (ArcGIS + BART)")
    ap.add_argument("--all", action="store_true", help="todas las fuentes")
    ap.add_argument("--vector", action="store_true")
    ap.add_argument("--raster", action="store_true")
    ap.add_argument("--verify", action="store_true", help="AMENAZA_IDD / AMENAZA_ICV")
    ap.add_argument("--bart", action="store_true")
    args = ap.parse_args(argv)

    if not any([args.all, args.vector, args.raster, args.verify, args.bart]):
        args.all = True

    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    log.info("Almacén: %s", DATA_ROOT.resolve())

    total_ok = total_fail = 0
    if args.all or args.vector:
        o, f = run_vector(); total_ok += o; total_fail += f
    if args.all or args.verify:
        o, f = run_verify(); total_ok += o; total_fail += f
    if args.all or args.raster:
        o, f = run_raster(); total_ok += o; total_fail += f
    if args.all or args.bart:
        o, f = run_bart(); total_ok += o; total_fail += f

    log.info("Resumen: %d datasets procesados, %d con error", total_ok, total_fail)
    # Exit != 0 si TODO falló (útil para que la Action marque fallo real),
    # pero no si solo cayó una fuente (resiliencia).
    return 1 if total_ok == 0 and total_fail > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
