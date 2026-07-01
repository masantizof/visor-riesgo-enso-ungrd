"""
pages/0_Panorama_ENSO.py — Inicio · Panorama ENSO
====================================================
Muestra el semáforo con la fase ENSO vigente (ONI), su intensidad y la
teleconexión esperada para Colombia, junto con el mapa nacional de riesgo
amplificado por esa fase (cruce ENSO × índices SNGRD).

La app NUNCA consulta IDEAM/NOAA en vivo: todo proviene de los snapshots
en data_lake/ (ver src/loaders.py). st.set_page_config vive en app.py
(el router); esta página no la vuelve a llamar.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import loaders, ui  # noqa: E402
from src.maps import capa_vector_coloreada, mapa_base, mostrar_mapa, agregar_leyenda  # noqa: E402
from src.downloads import boton_csv, boton_geojson  # noqa: E402

ui.header(
    "Panorama ENSO",
    "Estado actual del fenómeno <b>El Niño / La Niña - Oscilación del Sur (ENSO)</b> "
    "y su efecto amplificador sobre los riesgos de origen hidrometeorológico en Colombia. "
    "El diagnóstico de fase se calcula a partir del <b>Índice Oceánico El Niño (ONI)</b> "
    "publicado por el NOAA/CPC; el cruce territorial usa los "
    "<b>índices de riesgo municipal del SNGRD</b>.",
)

assessment = loaders.cargar_assessment_enso()
ui.semaforo_enso(assessment)

st.divider()

st.subheader("Riesgo municipal amplificado por la fase ENSO vigente")

tabla = loaders.cargar_riesgo_enso_tabla()
geo = loaders.cargar_riesgo_enso_geojson()
meta = loaders.metadatos("enso_riesgo")

if tabla is None or geo is None:
    ui.sin_datos(
        "enso_riesgo",
        "Corre `python ideam_wrf_cpt.py --enso` y luego "
        "`python ideam_enso_risk.py --indices data/reference/indices_riesgo_municipal.geojson`.",
    )
else:
    conteo = tabla["enso_nivel"].value_counts()
    ui.kpi_row([
        {"label": "Municipios en riesgo ALTO", "value": str(int(conteo.get("alto", 0))), "icon": "🔴",
         "sub": "amplificado por la fase vigente"},
        {"label": "Municipios en riesgo MEDIO", "value": str(int(conteo.get("medio", 0))), "icon": "🟠"},
        {"label": "Municipios en riesgo BAJO", "value": str(int(conteo.get("bajo", 0))), "icon": "🟢"},
        {"label": "Municipios evaluados", "value": str(len(tabla)), "icon": "🗺️",
         "sub": "capa SNGRD, resolución simplificada"},
    ])

    col_map, col_tabla = st.columns([3, 2])
    with col_map:
        m = mapa_base()
        capa_vector_coloreada(
            m, geo, color_field="enso_nivel", color_map=ui.NIVEL_COLOR,
            tooltip_fields=["MPIO_CNMBR", "DPTO_CNMBR", "enso_nivel", "enso_amenazas"],
            tooltip_aliases=["Municipio", "Departamento", "Nivel de riesgo", "Amenazas"],
            nombre="Riesgo ENSO municipal",
        )
        agregar_leyenda(m, "Nivel de riesgo (fase vigente)", [
            (ui.NIVEL_COLOR["alto"], "Alto"),
            (ui.NIVEL_COLOR["medio"], "Medio"),
            (ui.NIVEL_COLOR["bajo"], "Bajo"),
            (ui.NIVEL_COLOR["sin dato"], "Sin dato"),
        ])
        mostrar_mapa(m, key="mapa_panorama_enso")
        ui.meta_caption(meta)

    with col_tabla:
        st.markdown("**Municipios en riesgo ALTO**")
        cols_mostrar = ["municipio", "departamento", "amenaza_principal", "enso_score"]
        alto = tabla[tabla["enso_nivel"] == "alto"][cols_mostrar].rename(columns={
            "municipio": "Municipio", "departamento": "Departamento",
            "amenaza_principal": "Amenaza principal", "enso_score": "Índice",
        }).sort_values("Índice", ascending=False)
        st.dataframe(alto, hide_index=True, height=430, width="stretch")

    c1, c2 = st.columns(2)
    with c1:
        boton_csv(tabla, "riesgo_enso_municipal.csv", key="csv_panorama")
    with c2:
        boton_geojson(geo, "riesgo_enso_municipal.geojson", key="geojson_panorama")

    st.caption(
        "El cruce indica riesgo **amplificado** por la fase ENSO vigente (no una probabilidad "
        "condicional de evento extremo). Ver detalle y selector de fase en **Riesgo climático ENSO**."
    )

ui.footer()
