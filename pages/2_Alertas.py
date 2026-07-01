"""
pages/2_Alertas.py
===================
Alertas hidrológicas vigentes (vector, coloreadas por nivel) + capas de
amenaza por deslizamientos (IDD) e incendios de cobertura vegetal (ICV).
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import loaders, ui  # noqa: E402
from src.maps import capa_vector_coloreada, capa_raster, mapa_base, mostrar_mapa, agregar_leyenda  # noqa: E402
from src.downloads import boton_csv, boton_geojson, boton_png  # noqa: E402

ui.header(
    "Alertas",
    "Alertas <b>hidrológicas</b> vigentes por zona hidrográfica (IDEAM) y capas de "
    "<b>amenaza</b> por deslizamientos e incendios de cobertura vegetal. "
    "<a href='/Metodologia_y_fuentes' target='_self'>¿Cómo se calcula esto?</a>",
)

ALERTA_COLOR = {"ALERTA ROJA": "#D7263D", "ALERTA NARANJA": "#F4A83D", "ALERTA AMARILLA": ui.COLORS["gold"]}
ALERTA_RANGO = {"ALERTA ROJA": 3, "ALERTA NARANJA": 2, "ALERTA AMARILLA": 1}

geo = loaders.cargar_geojson("alertas_hidrologicas")
meta = loaders.metadatos("alertas_hidrologicas")
tabla = loaders.cargar_tabla("alertas_hidrologicas")

# --------------------------------------------------------------------------- #
# Consolidado por departamento: nivel más alto vigente + recurrencia histórica
# (Sala de Crisis). Se agrupa por departamento porque las alertas hidrológicas
# están zonificadas por área/zona hidrográfica, no por municipio.
# --------------------------------------------------------------------------- #
st.subheader("Consolidado de alertas por departamento")
if tabla is not None:
    eventos_dpto = loaders.cargar_eventos_por_departamento()
    cons = tabla.copy()
    cons["_rango"] = cons["NIVEL_A"].map(ALERTA_RANGO).fillna(0)
    resumen = cons.groupby("DEP").agg(
        zonas_en_alerta=("NIVEL_A", "count"),
        nivel_mas_alto=("_rango", "max"),
    ).reset_index()
    inv_rango = {v: k.replace("ALERTA ", "") for k, v in ALERTA_RANGO.items()}
    resumen["Nivel más alto"] = resumen["nivel_mas_alto"].map(inv_rango)
    if eventos_dpto is not None:
        emerg_dpto = eventos_dpto.groupby("Nombre Departamento")["n_emergencias"].sum().reset_index()
        resumen = resumen.merge(
            emerg_dpto, left_on="DEP", right_on="Nombre Departamento", how="left"
        ).drop(columns=["Nombre Departamento"])
        resumen["n_emergencias"] = resumen["n_emergencias"].fillna(0).astype(int)
    else:
        resumen["n_emergencias"] = None
    resumen = resumen.sort_values("nivel_mas_alto", ascending=False)

    n_rojo = int((resumen["nivel_mas_alto"] == 3).sum())
    n_naranja = int((resumen["nivel_mas_alto"] == 2).sum())
    ui.kpi_row([
        {"label": "Departamentos con alerta ROJA", "value": str(n_rojo), "icon": "🔴"},
        {"label": "Departamentos con alerta NARANJA (máx.)", "value": str(n_naranja), "icon": "🟠"},
        {"label": "Departamentos con alguna alerta", "value": str(len(resumen)), "icon": "📍"},
        {"label": "Zonas/subzonas en alerta (nacional)", "value": str(len(tabla)), "icon": "💧"},
    ])
    st.dataframe(
        resumen.rename(columns={
            "DEP": "Departamento", "zonas_en_alerta": "Zonas en alerta",
            "n_emergencias": "Emergencias históricas (Sala de Crisis)",
        })[["Departamento", "Nivel más alto", "Zonas en alerta", "Emergencias históricas (Sala de Crisis)"]],
        hide_index=True, width="stretch", height=280,
    )
    boton_csv(resumen, "consolidado_alertas_departamento.csv", key="csv_consolidado")
else:
    ui.sin_datos("alertas_hidrologicas")

st.divider()
st.subheader("Alertas hidrológicas vigentes")
st.caption(
    "Alertas por **nivel de las corrientes de agua** (ríos y quebradas), emitidas por IDEAM "
    "para cada zona/subzona hidrográfica del país — no se refieren a lluvia ni a deslizamientos. "
    "🔴 **Roja**: nivel crítico, crecida en curso o inminente. "
    "🟠 **Naranja**: nivel alto, monitoreo permanente. "
    "🟡 **Amarilla**: nivel de vigilancia preventiva."
)
if geo is None or tabla is None:
    ui.sin_datos("alertas_hidrologicas")
else:
    conteo = tabla["NIVEL_A"].value_counts()
    ui.kpi_row([
        {"label": "Alerta ROJA", "value": str(int(conteo.get("ALERTA ROJA", 0))), "icon": "🔴"},
        {"label": "Alerta NARANJA", "value": str(int(conteo.get("ALERTA NARANJA", 0))), "icon": "🟠"},
        {"label": "Alerta AMARILLA", "value": str(int(conteo.get("ALERTA AMARILLA", 0))), "icon": "🟡"},
        {"label": "Zonas/subzonas con alerta", "value": str(len(tabla)), "icon": "💧"},
    ])

    deptos = sorted(set(tabla["DEP"].dropna().unique()) | set(tabla["DEP_1"].dropna().unique()))
    deptos = [d for d in deptos if d.strip()]
    c1, c2 = st.columns(2)
    with c1:
        depto_sel = st.selectbox("Departamento", ["Todos"] + deptos)
    with c2:
        nivel_sel = st.multiselect("Nivel de alerta", sorted(tabla["NIVEL_A"].dropna().unique()))

    def _filtra_geo(geo, depto, niveles):
        feats = geo["features"]
        if depto != "Todos":
            feats = [f for f in feats if depto in (f["properties"].get("DEP", ""), f["properties"].get("DEP_1", ""))]
        if niveles:
            feats = [f for f in feats if f["properties"].get("NIVEL_A") in niveles]
        return {"type": "FeatureCollection", "features": feats}

    geo_f = _filtra_geo(geo, depto_sel, nivel_sel)
    tabla_f = tabla.copy()
    if depto_sel != "Todos":
        tabla_f = tabla_f[(tabla_f["DEP"] == depto_sel) | (tabla_f["DEP_1"] == depto_sel)]
    if nivel_sel:
        tabla_f = tabla_f[tabla_f["NIVEL_A"].isin(nivel_sel)]

    col_map, col_tabla = st.columns([3, 2])
    with col_map:
        m = mapa_base()
        capa_vector_coloreada(
            m, geo_f, color_field="NIVEL_A", color_map=ALERTA_COLOR,
            tooltip_fields=["NOMAH", "NOMZH", "NOMSZH", "DEP", "NIVEL_A"],
            tooltip_aliases=["Área hidrográfica", "Zona hidrográfica", "Subzona", "Departamento", "Nivel"],
            nombre="Alertas hidrológicas",
        )
        agregar_leyenda(m, "Nivel de alerta", [(v, k.replace("ALERTA ", "")) for k, v in ALERTA_COLOR.items()])
        mostrar_mapa(m, key="mapa_alertas_hidro")
        ui.meta_caption(meta)
    with col_tabla:
        cols = ["NOMAH", "NOMZH", "NOMSZH", "DEP", "NIVEL_A"]
        st.dataframe(
            tabla_f[cols].rename(columns={
                "NOMAH": "Área hidrográfica", "NOMZH": "Zona hidrográfica", "NOMSZH": "Subzona",
                "DEP": "Departamento", "NIVEL_A": "Nivel",
            }),
            hide_index=True, width="stretch", height=430,
        )

    c1, c2 = st.columns(2)
    with c1:
        boton_csv(tabla_f, "alertas_hidrologicas.csv", key="csv_alertas_hidro")
    with c2:
        boton_geojson(geo_f, "alertas_hidrologicas.geojson", key="geojson_alertas_hidro")

st.divider()
st.subheader("Alertas por deslizamientos (IDD) e incendios (ICV)")
st.caption(
    "IDD = índice de deslizamientos disparados por lluvia; ICV = incendios de cobertura vegetal. "
    "Son capas independientes de las alertas hidrológicas de arriba."
)
c1, c2 = st.columns(2)
for col, ds, titulo in ((c1, "alertas_idd", "Deslizamientos (IDD)"), (c2, "alertas_icv", "Incendios de cobertura vegetal (ICV)")):
    with col:
        st.markdown(f"**{titulo}**")
        g = loaders.cargar_geojson(ds)
        if g is None:
            ui.sin_datos(ds, "Esta capa venía fallando en el servidor de IDEAM al momento de la última corrida del extractor.")
        else:
            t = loaders.cargar_tabla(ds)
            st.dataframe(t, hide_index=True, width="stretch", height=250)
            boton_csv(t, f"{ds}.csv", key=f"csv_{ds}")
            boton_geojson(g, f"{ds}.geojson", key=f"geojson_{ds}")

st.divider()
st.subheader("Capas de amenaza (ráster)")
st.caption("Mapa de fondo de susceptibilidad (no vigente/puntual como las alertas de arriba, sino condición estructural del territorio).")
c1, c2 = st.columns(2)
for col, ds, titulo in ((c1, "amenaza_idd", "Amenaza por deslizamientos"), (c2, "amenaza_icv", "Amenaza por incendios")):
    with col:
        st.markdown(f"**{titulo}**")
        r = loaders.cargar_raster(ds)
        if r is None:
            ui.sin_datos(ds)
            continue
        png, bounds, legend = r
        opacidad = st.slider(f"Opacidad — {titulo}", 0.0, 1.0, 0.7, key=f"op_{ds}")
        m = mapa_base()
        capa_raster(m, png, bounds, nombre=titulo, opacidad=opacidad)
        mostrar_mapa(m, key=f"mapa_{ds}", height=380)
        ui.meta_caption(loaders.metadatos(ds))
        boton_png(png, f"{ds}.png", key=f"png_{ds}")

ui.footer()
