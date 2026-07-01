"""
pages/1_Riesgo_climatico_ENSO.py
==================================
Producto central: cruce fase ENSO × índices de riesgo municipal (SNGRD).
Selector de fase (actual / El Niño / La Niña / Neutral) recolorea el mapa
y actualiza la narrativa por municipio en el momento, reutilizando las
funciones puras ya implementadas en ideam_enso_risk.py (municipal_enso_risk,
public_narrative) — sin tocar IDEAM/NOAA en vivo ni reescribir data_lake.
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import loaders, ui  # noqa: E402
from src.maps import capa_vector_coloreada, mapa_base, mostrar_mapa, agregar_leyenda  # noqa: E402
from src.downloads import boton_csv, boton_geojson  # noqa: E402
from ideam_enso_risk import municipal_enso_risk, public_narrative  # noqa: E402

st.set_page_config(page_title="Riesgo climático ENSO · UNGRD", page_icon="🗺️", layout="wide")

ui.header(
    "Riesgo climático ENSO",
    "Cruce entre la <b>fase ENSO</b> vigente (o una fase hipotética que elijas) y los "
    "<b>índices de riesgo municipal del SNGRD</b> (incendios, desabastecimiento hídrico, "
    "inundaciones, crecientes, avenidas torrenciales, movimientos en masa, vendavales). "
    "La fase <b>amplifica</b> el riesgo asociado; no lo causa por sí sola.",
)

referencia = loaders.cargar_referencia_indices_riesgo()
assessment = loaders.cargar_assessment_enso()

if referencia is None:
    ui.sin_datos("indices_riesgo_municipal", "Falta data/reference/indices_riesgo_municipal.geojson en el repo.")
    st.stop()

fase_vigente = assessment.get("fase", "Neutral") if assessment else "Neutral"
opciones_fase = ["Fase vigente", "El Niño", "La Niña", "Neutral"]

col_sel, col_info = st.columns([1, 3])
with col_sel:
    eleccion = st.selectbox("Selecciona la fase ENSO a evaluar", opciones_fase, index=0)
fase = fase_vigente if eleccion == "Fase vigente" else eleccion
with col_info:
    if eleccion == "Fase vigente":
        st.caption(f"Fase vigente según el último assessment ONI: **{fase_vigente}**"
                    + (f" (ONI {assessment['oni']:+.2f} °C)" if assessment else " — sin snapshot ENSO, se asume Neutral"))
    else:
        st.caption(f"Estás viendo un escenario **hipotético**: fase {fase}. No es la fase vigente.")

registros = municipal_enso_risk(referencia["features"], fase)
tabla = pd.DataFrame(registros)
tabla["narrativa"] = [public_narrative(r) for r in registros]

conteo = tabla["enso_nivel"].value_counts()
ui.kpi_row([
    {"label": "Riesgo ALTO", "value": str(int(conteo.get("alto", 0))), "icon": "🔴"},
    {"label": "Riesgo MEDIO", "value": str(int(conteo.get("medio", 0))), "icon": "🟠"},
    {"label": "Riesgo BAJO", "value": str(int(conteo.get("bajo", 0))), "icon": "🟢"},
    {"label": "Sin dato", "value": str(int(conteo.get("sin dato", 0))), "icon": "⚪"},
])

# geojson enriquecido en memoria (no se escribe a disco: es exploración interactiva)
by_code = {r["cod_dane"]: r for r in registros}
geo_interactivo = {"type": "FeatureCollection", "features": []}
for f in referencia["features"]:
    code = f["properties"].get("MPIO_CCNCT")
    r = by_code.get(code, {})
    props = dict(f["properties"])
    props.update({
        "enso_nivel": r.get("enso_nivel"),
        "enso_amenazas": r.get("amenazas"),
        "amenaza_principal": r.get("amenaza_principal"),
    })
    geo_interactivo["features"].append({"type": "Feature", "properties": props, "geometry": f["geometry"]})

st.divider()
col_map, col_detalle = st.columns([3, 2])

with col_map:
    st.markdown(f"**Mapa nacional — riesgo amplificado en fase {fase}**")
    m = mapa_base()
    capa_vector_coloreada(
        m, geo_interactivo, color_field="enso_nivel", color_map=ui.NIVEL_COLOR,
        tooltip_fields=["MPIO_CNMBR", "DPTO_CNMBR", "enso_nivel", "amenaza_principal"],
        tooltip_aliases=["Municipio", "Departamento", "Nivel", "Amenaza principal"],
        nombre=f"Riesgo ENSO — {fase}",
    )
    agregar_leyenda(m, "Nivel de riesgo", [
        (ui.NIVEL_COLOR["alto"], "Alto"), (ui.NIVEL_COLOR["medio"], "Medio"),
        (ui.NIVEL_COLOR["bajo"], "Bajo"), (ui.NIVEL_COLOR["sin dato"], "Sin dato"),
    ])
    mostrar_mapa(m, key=f"mapa_riesgo_{fase}")

with col_detalle:
    st.markdown("**Consulta ciudadana por municipio**")
    deptos = sorted(tabla["departamento"].dropna().unique())
    depto_sel = st.selectbox("Departamento", ["Todos"] + deptos, key="depto_sel")
    sub = tabla if depto_sel == "Todos" else tabla[tabla["departamento"] == depto_sel]
    munis = sorted(sub["municipio"].dropna().unique())
    muni_sel = st.selectbox("Municipio", munis, key="muni_sel") if munis else None
    if muni_sel:
        rec = sub[sub["municipio"] == muni_sel].iloc[0]
        color = ui.NIVEL_COLOR.get(rec["enso_nivel"], ui.NIVEL_COLOR["sin dato"])
        st.markdown(ui.badge(rec["enso_nivel"].upper(), color), unsafe_allow_html=True)
        st.write(rec["narrativa"])
        if rec["amenazas"]:
            st.caption(f"Amenazas evaluadas: {rec['amenazas']}")

st.divider()
st.markdown("**Tabla técnica** (filtrable por departamento/municipio/amenaza, con descarga)")
amenaza_filtro = st.multiselect(
    "Filtrar por amenaza principal", sorted(tabla["amenaza_principal"].dropna().unique())
)
tabla_filtrada = tabla.copy()
if depto_sel != "Todos":
    tabla_filtrada = tabla_filtrada[tabla_filtrada["departamento"] == depto_sel]
if amenaza_filtro:
    tabla_filtrada = tabla_filtrada[tabla_filtrada["amenaza_principal"].isin(amenaza_filtro)]

st.dataframe(
    tabla_filtrada.rename(columns={
        "cod_dane": "Cód. DANE", "municipio": "Municipio", "departamento": "Departamento",
        "fase_enso": "Fase ENSO", "enso_score": "Índice", "enso_nivel": "Nivel",
        "amenazas": "Amenazas (todas)", "amenaza_principal": "Amenaza principal",
        "narrativa": "Narrativa ciudadana",
    }),
    hide_index=True, use_container_width=True, height=380,
)

c1, c2 = st.columns(2)
with c1:
    boton_csv(tabla_filtrada, f"riesgo_enso_{fase.replace(' ', '_')}.csv", key="csv_detalle")
with c2:
    boton_geojson(geo_interactivo, f"riesgo_enso_{fase.replace(' ', '_')}.geojson", key="geojson_detalle")

ui.footer()
