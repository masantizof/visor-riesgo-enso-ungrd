"""
pages/1_Riesgo_climatico_ENSO.py
==================================
Producto central: cruce fase ENSO × índices de riesgo municipal (SNGRD),
enriquecido con recurrencia histórica de emergencias (Sala de Crisis).
Selector de fase (actual / El Niño / La Niña / Neutral) recolorea el mapa
y actualiza la narrativa por municipio en el momento, reutilizando las
funciones puras ya implementadas en ideam_enso_risk.py (municipal_enso_risk,
public_narrative) — sin tocar IDEAM/NOAA en vivo ni reescribir data_lake.

Filtros cruzados: todos los widgets de esta página (fase, departamento,
nivel, amenaza, "solo con historial") se aplican ANTES de calcular KPIs,
mapa y tabla — cambiar cualquiera actualiza los tres a la vez.
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

ui.header(
    "Riesgo climático ENSO",
    "Cruce entre la <b>fase ENSO</b> vigente (o una fase hipotética que elijas) y los "
    "<b>índices de riesgo municipal del SNGRD</b> (incendios, desabastecimiento hídrico, "
    "inundaciones, crecientes, avenidas torrenciales, movimientos en masa, vendavales), "
    "enriquecido con la <b>recurrencia histórica de emergencias</b> (Sala de Crisis). "
    "La fase <b>amplifica</b> el riesgo asociado; no lo causa por sí sola. "
    "<a href='/Metodologia_y_fuentes' target='_self'>¿Cómo se calcula esto?</a>",
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

# --- Enriquecer con Sala de Crisis: recurrencia y familias históricas ---
recurrencia = loaders.cargar_recurrencia_municipio_evento()
if recurrencia is not None:
    # nº de emergencias del MISMO tipo que la amenaza principal SNGRD de cada municipio
    mapa_evento = {
        "I_IF": "Incendio forestal", "I_Inundaci": "Inundacion", "I_MovMasa": "Movimiento en masa",
        "I_Vendaval": "Vendaval", "I_Crecient": "Creciente subita", "I_AVT": "Avenida torrencial",
        "I_Desabast": "Desabastecimiento de agua", "I_DHTLL_In": "Inundacion", "I_DHTS_I_D": "Inundacion",
    }
    tabla["evento_sala_crisis"] = tabla["amenaza_principal"].map(
        lambda a: next((v for k, v in mapa_evento.items() if k in str(a)), None)
    ) if "amenaza_principal" in tabla.columns else None
    rec_idx = recurrencia.set_index(["Codigo Municipio", "EVENTO"])
    def _lookup(row):
        clave = (row["cod_dane"], row.get("evento_sala_crisis"))
        if clave in rec_idx.index:
            r = rec_idx.loc[clave]
            return pd.Series({"n_emergencias_historicas": r["n_emergencias"], "familias_historicas": r["familias"]})
        return pd.Series({"n_emergencias_historicas": 0, "familias_historicas": 0.0})
    tabla = pd.concat([tabla, tabla.apply(_lookup, axis=1)], axis=1)
else:
    tabla["n_emergencias_historicas"] = None
    tabla["familias_historicas"] = None

# índice de exposición: amplifica el índice SNGRD con la afectación histórica
# (no es un dato DANE de población real — ver nota de metodología)
tabla["indice_exposicion"] = tabla["enso_score"].fillna(0) * (1 + tabla["familias_historicas"].fillna(0))

# --- Filtros (todo lo de aquí abajo se recalcula con cada cambio) ---
st.markdown("**Filtros** (se cruzan entre sí y con el mapa/tabla)")
f1, f2, f3, f4 = st.columns(4)
with f1:
    deptos = sorted(tabla["departamento"].dropna().unique())
    depto_filtro = st.multiselect("Departamento", deptos, key="depto_filtro")
with f2:
    niveles = ["alto", "medio", "bajo", "sin dato"]
    nivel_filtro = st.multiselect("Nivel de riesgo", niveles, key="nivel_filtro")
with f3:
    amenazas = sorted(tabla["amenaza_principal"].dropna().unique())
    amenaza_filtro = st.multiselect("Amenaza principal", amenazas, key="amenaza_filtro")
with f4:
    solo_historial = st.checkbox("Solo con historial de emergencias", key="solo_historial")

st.caption(
    "Filtros por tipo de población (familias reales, % rural, estrato, grupo étnico) están "
    "**pendientes**: requieren una fuente nacional verificada de caracterización DANE que aún no "
    "está disponible (ver Metodología y fuentes)."
)

tabla_f = tabla.copy()
if depto_filtro:
    tabla_f = tabla_f[tabla_f["departamento"].isin(depto_filtro)]
if nivel_filtro:
    tabla_f = tabla_f[tabla_f["enso_nivel"].isin(nivel_filtro)]
if amenaza_filtro:
    tabla_f = tabla_f[tabla_f["amenaza_principal"].isin(amenaza_filtro)]
if solo_historial:
    tabla_f = tabla_f[tabla_f["n_emergencias_historicas"] > 0]

conteo = tabla_f["enso_nivel"].value_counts()
ui.kpi_row([
    {"label": "Riesgo ALTO", "value": str(int(conteo.get("alto", 0))), "icon": "🔴"},
    {"label": "Riesgo MEDIO", "value": str(int(conteo.get("medio", 0))), "icon": "🟠"},
    {"label": "Riesgo BAJO", "value": str(int(conteo.get("bajo", 0))), "icon": "🟢"},
    {"label": "Municipios en la vista", "value": str(len(tabla_f)), "icon": "🗺️",
     "sub": f"de {len(tabla)} evaluados" if len(tabla_f) != len(tabla) else "sin filtros activos"},
])

# geojson enriquecido en memoria (no se escribe a disco: es exploración interactiva)
codigos_f = set(tabla_f["cod_dane"])
by_code = {r["cod_dane"]: r for r in tabla_f.to_dict("records")}
geo_interactivo = {"type": "FeatureCollection", "features": []}
for f in referencia["features"]:
    code = f["properties"].get("MPIO_CCNCT")
    if code not in codigos_f:
        continue
    r = by_code.get(code, {})
    props = dict(f["properties"])
    props.update({
        "enso_nivel": r.get("enso_nivel"),
        "enso_amenazas": r.get("amenazas"),
        "amenaza_principal": r.get("amenaza_principal"),
        "n_emergencias_historicas": r.get("n_emergencias_historicas"),
    })
    geo_interactivo["features"].append({"type": "Feature", "properties": props, "geometry": f["geometry"]})

st.divider()
col_map, col_detalle = st.columns([3, 2])

with col_map:
    st.markdown(f"**Mapa nacional — riesgo amplificado en fase {fase}**")
    if not geo_interactivo["features"]:
        st.warning("Ningún municipio cumple los filtros seleccionados.")
    else:
        m = mapa_base()
        capa_vector_coloreada(
            m, geo_interactivo, color_field="enso_nivel", color_map=ui.NIVEL_COLOR,
            tooltip_fields=["MPIO_CNMBR", "DPTO_CNMBR", "enso_nivel", "amenaza_principal", "n_emergencias_historicas"],
            tooltip_aliases=["Municipio", "Departamento", "Nivel", "Amenaza principal", "Emergencias históricas"],
            nombre=f"Riesgo ENSO — {fase}",
        )
        agregar_leyenda(m, "Nivel de riesgo", [
            (ui.NIVEL_COLOR["alto"], "Alto"), (ui.NIVEL_COLOR["medio"], "Medio"),
            (ui.NIVEL_COLOR["bajo"], "Bajo"), (ui.NIVEL_COLOR["sin dato"], "Sin dato"),
        ])
        mostrar_mapa(m, key=f"mapa_riesgo_{fase}_{len(tabla_f)}")

with col_detalle:
    st.markdown("**Consulta ciudadana por municipio**")
    deptos_c = sorted(tabla_f["departamento"].dropna().unique()) if len(tabla_f) else []
    depto_sel = st.selectbox("Departamento", ["Todos"] + deptos_c, key="depto_sel_consulta")
    sub = tabla_f if depto_sel == "Todos" else tabla_f[tabla_f["departamento"] == depto_sel]
    munis = sorted(sub["municipio"].dropna().unique())
    muni_sel = st.selectbox("Municipio", munis, key="muni_sel") if munis else None
    if muni_sel:
        rec = sub[sub["municipio"] == muni_sel].iloc[0]
        color = ui.NIVEL_COLOR.get(rec["enso_nivel"], ui.NIVEL_COLOR["sin dato"])
        st.markdown(ui.badge(rec["enso_nivel"].upper(), color), unsafe_allow_html=True)
        st.write(rec["narrativa"])
        if rec["amenazas"]:
            st.caption(f"Amenazas evaluadas: {rec['amenazas']}")
        n_hist = int(rec.get("n_emergencias_historicas") or 0)
        if n_hist:
            st.caption(
                f"📋 Este municipio registra **{n_hist} emergencias históricas** del tipo "
                f"'{rec.get('evento_sala_crisis')}' en Sala de Crisis "
                f"({rec.get('familias_historicas', 0):,.0f} familias afectadas en total)."
            )
        else:
            st.caption("Sin emergencias históricas registradas de este tipo en Sala de Crisis.")

st.divider()
st.markdown(
    "**Tabla técnica** — click en el encabezado de una columna para ordenar (p. ej. por "
    "*Índice de exposición* para priorizar municipios)"
)

st.dataframe(
    tabla_f.rename(columns={
        "cod_dane": "Cód. DANE", "municipio": "Municipio", "departamento": "Departamento",
        "fase_enso": "Fase ENSO", "enso_score": "Índice SNGRD", "enso_nivel": "Nivel",
        "amenazas": "Amenazas (todas)", "amenaza_principal": "Amenaza principal",
        "narrativa": "Narrativa ciudadana", "n_emergencias_historicas": "Emergencias históricas",
        "familias_historicas": "Familias afectadas (histórico)", "indice_exposicion": "Índice de exposición",
    })[[
        "Cód. DANE", "Municipio", "Departamento", "Nivel", "Índice SNGRD", "Amenaza principal",
        "Emergencias históricas", "Familias afectadas (histórico)", "Índice de exposición",
        "Amenazas (todas)", "Narrativa ciudadana",
    ]],
    hide_index=True, width="stretch", height=380,
)

c1, c2 = st.columns(2)
with c1:
    boton_csv(tabla_f, f"riesgo_enso_{fase.replace(' ', '_')}.csv", key="csv_detalle")
with c2:
    boton_geojson(geo_interactivo, f"riesgo_enso_{fase.replace(' ', '_')}.geojson", key="geojson_detalle")

ui.footer()
