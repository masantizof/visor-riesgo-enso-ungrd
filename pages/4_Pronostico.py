"""
pages/4_Pronostico.py
=======================
Pronóstico de corto plazo (ráster: pronóstico 24h, acumulados 24h/72h,
hidroestimador NOAA) y predicción estacional CPT (galería de imágenes por
producto × horizonte, 6 meses), coherente con la fase ENSO vigente.
Además, enlaces de descarga a las grillas de modelo (WRF/GFS) que se
procesan fuera de la app.
"""
import re
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import loaders, ui  # noqa: E402
from src.maps import capa_raster, mapa_base, mostrar_mapa  # noqa: E402
from src.downloads import boton_png, boton_generico  # noqa: E402

st.set_page_config(page_title="Pronóstico · UNGRD", page_icon="📈", layout="wide")

ui.header(
    "Pronóstico",
    "Pronóstico hidrometeorológico de <b>corto plazo</b> (24–72 h, ráster IDEAM) y "
    "predicción <b>estacional CPT</b> (6 meses), coherente con la fase ENSO vigente. "
    "Las grillas de modelo (WRF/GFS) se ofrecen para descarga y procesamiento externo.",
)

tab_corto, tab_estacional, tab_grillas = st.tabs(
    ["🌧️ Corto plazo (ráster)", "📅 Estacional (CPT)", "🗄️ Grillas de modelo (WRF/GFS)"]
)

RASTER_DS = [
    ("pronostico_precip_24h", "Pronóstico de precipitación 24h"),
    ("acumulado_24h", "Precipitación acumulada 24h"),
    ("acumulado_72h", "Precipitación acumulada 72h"),
    ("hidroestimador_noaa", "Hidroestimador satelital NOAA"),
]

with tab_corto:
    sel = st.selectbox("Producto ráster", [t for _, t in RASTER_DS])
    ds = next(d for d, t in RASTER_DS if t == sel)
    r = loaders.cargar_raster(ds)
    if r is None:
        ui.sin_datos(ds)
    else:
        png, bounds, legend = r
        opacidad = st.slider("Opacidad", 0.0, 1.0, 0.75, key=f"op_{ds}")
        m = mapa_base()
        capa_raster(m, png, bounds, nombre=sel, opacidad=opacidad)
        mostrar_mapa(m, key=f"mapa_{ds}")
        ui.meta_caption(loaders.metadatos(ds))
        boton_png(png, f"{ds}.png", key=f"png_{ds}")
        if legend:
            with st.expander("Leyenda técnica (JSON de simbología IDEAM)"):
                st.json(legend)

with tab_estacional:
    variable = st.radio(
        "Variable", ["Precipitación", "Temperatura", "Viento"], horizontal=True, key="cpt_var"
    )
    ds = f"cpt_prediccion_{variable.lower()}"
    imgs = loaders.cargar_set_imagenes(ds)
    meta = loaders.metadatos(ds)
    if not imgs:
        ui.sin_datos(ds, "Es posible que esta variable no esté publicada por el CPT en este momento.")
    else:
        # claves con forma "{PRODUCTO}_mes{N}" (ver ideam_wrf_cpt.fetch_cpt)
        productos = sorted({re.match(r"(.+)_mes\d+", k).group(1) for k in imgs if re.match(r"(.+)_mes\d+", k)})
        prod_sel = st.selectbox("Producto CPT", productos, key="cpt_prod")
        meses_disponibles = sorted(
            int(re.match(rf"{re.escape(prod_sel)}_mes(\d+)", k).group(1))
            for k in imgs if k.startswith(f"{prod_sel}_mes")
        )
        cols = st.columns(min(len(meses_disponibles), 6) or 1)
        for mes, col in zip(meses_disponibles, cols):
            ruta = imgs.get(f"{prod_sel}_mes{mes}")
            with col:
                st.image(ruta, caption=f"Mes {mes}", use_container_width=True)
                boton_png(ruta, f"{ds}_{prod_sel}_mes{mes}.png", key=f"png_{ds}_{prod_sel}_{mes}")
        ui.meta_caption(meta)

with tab_grillas:
    st.caption(
        "Estas grillas (NetCDF/GeoTIFF/GRIB2) se ofrecen para descarga y procesamiento externo "
        "(xarray/cfgrib/rasterio); la app no las renderiza directamente."
    )
    for ds, titulo in (
        ("wrf00_netcdf", "WRF 00Z Colombia — NetCDF"),
        ("wrf00_tif", "WRF 00Z Colombia — GeoTIFF"),
        ("gfs06_grib2", "GFS 06Z Colombia — GRIB2"),
    ):
        meta = loaders.metadatos(ds)
        st.markdown(f"**{titulo}**")
        if meta is None:
            ui.sin_datos(ds)
            continue
        ui.meta_caption(meta)
        ruta = Path(meta["files"]["data"])
        if ruta.exists():
            boton_generico(
                ruta.read_bytes(), ruta.name, "application/octet-stream",
                f"⬇️ Descargar {ruta.name} ({meta.get('size_bytes', 0) / 1e6:.1f} MB)",
                key=f"grid_{ds}",
            )
        else:
            st.caption("Archivo no disponible localmente en este entorno.")

ui.footer()
