"""
pages/3_Observacion_diaria.py
===============================
Observación reciente por estación (precipitación y temperatura máxima,
puntos) y reportes tabulares BART (diario, 3 días, mensuales).
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import loaders, ui  # noqa: E402
from src.maps import capa_puntos, mapa_base, mostrar_mapa  # noqa: E402
from src.downloads import boton_csv, boton_geojson, boton_generico  # noqa: E402

ui.header(
    "Observación diaria",
    "Precipitación y temperatura máxima registradas por estación (red IDEAM), y los "
    "reportes tabulares preliminares <b>BART</b> (diario, últimos 3 días y acumulados del mes).",
)

tab_puntos, tab_bart = st.tabs(["📍 Estaciones (mapa)", "📋 Reportes BART (tablas)"])

with tab_puntos:
    variable = st.radio("Variable", ["Precipitación diaria", "Temperatura máxima diaria"], horizontal=True)
    ds = "precipitacion_diaria" if variable == "Precipitación diaria" else "temperatura_max_diaria"
    color = "#1F6FEB" if ds == "precipitacion_diaria" else "#D7263D"
    unidad = "mm" if ds == "precipitacion_diaria" else "°C"

    geo = loaders.cargar_geojson(ds)
    tabla = loaders.cargar_tabla(ds)
    meta = loaders.metadatos(ds)

    if geo is None or tabla is None:
        ui.sin_datos(ds)
    else:
        deptos = sorted(tabla["DEPARTAMEN"].dropna().unique())
        depto_sel = st.selectbox("Departamento", ["Todos"] + deptos, key=f"depto_{ds}")
        tabla_f = tabla if depto_sel == "Todos" else tabla[tabla["DEPARTAMEN"] == depto_sel]
        codigos = set(tabla_f["CODIGO"])
        geo_f = {"type": "FeatureCollection",
                 "features": [f for f in geo["features"] if f["properties"].get("CODIGO") in codigos]}

        ui.kpi_row([
            {"label": "Estaciones", "value": str(len(tabla_f)), "icon": "📍"},
            {"label": f"Promedio ({unidad})", "value": f"{tabla_f['DATO'].mean():.1f}" if len(tabla_f) else "—", "icon": "📊"},
            {"label": f"Máximo ({unidad})", "value": f"{tabla_f['DATO'].max():.1f}" if len(tabla_f) else "—", "icon": "🔺",
             "sub": str(tabla_f.loc[tabla_f["DATO"].idxmax(), "ESTACION"]) if len(tabla_f) else ""},
            {"label": f"Mínimo ({unidad})", "value": f"{tabla_f['DATO'].min():.1f}" if len(tabla_f) else "—", "icon": "🔻"},
        ])

        col_map, col_tabla = st.columns([3, 2])
        with col_map:
            m = mapa_base()
            capa_puntos(
                m, geo_f,
                tooltip_fields=["ESTACION", "MUNICIPIO", "DEPARTAMEN", "DATO", "CATEGORIA"],
                tooltip_aliases=["Estación", "Municipio", "Departamento", f"Dato ({unidad})", "Categoría"],
                nombre=variable, color=color,
            )
            mostrar_mapa(m, key=f"mapa_{ds}")
            ui.meta_caption(meta)
        with col_tabla:
            cols = ["ESTACION", "MUNICIPIO", "DEPARTAMEN", "DATO", "CATEGORIA"]
            st.dataframe(
                tabla_f[cols].rename(columns={
                    "ESTACION": "Estación", "MUNICIPIO": "Municipio", "DEPARTAMEN": "Departamento",
                    "DATO": f"Dato ({unidad})", "CATEGORIA": "Categoría",
                }).sort_values(f"Dato ({unidad})", ascending=False),
                hide_index=True, use_container_width=True, height=430,
            )

        c1, c2 = st.columns(2)
        with c1:
            boton_csv(tabla_f, f"{ds}.csv", key=f"csv_{ds}")
        with c2:
            boton_geojson(geo_f, f"{ds}.geojson", key=f"geojson_{ds}")

with tab_bart:
    grupos = {
        "Diario y 3 días": [("bart_dia", "Reporte diario"), ("bart_tresdias", "Reporte 3 días")],
        "Series diarias del mes": [
            ("bart_precipitacion", "Precipitación diaria"),
            ("bart_temp_min", "Temperatura mínima diaria"),
            ("bart_temp_med", "Temperatura media diaria"),
            ("bart_temp_max", "Temperatura máxima diaria"),
        ],
        "Acumulados del mes": [
            ("acumulado_lluvia_mes", "Acumulado de lluvia"),
            ("acumulado_tempmax_mes", "Acumulado de temperatura máxima"),
            ("reporte_cordoba_mes", "Reporte Córdoba"),
        ],
    }
    for grupo, datasets in grupos.items():
        st.markdown(f"**{grupo}**")
        cols = st.columns(len(datasets))
        for (ds, titulo), col in zip(datasets, cols):
            with col:
                with st.expander(titulo, expanded=False):
                    df, ruta_xlsx = loaders.cargar_tabla_con_respaldo_xlsx(ds)
                    meta = loaders.metadatos(ds)
                    if df is None:
                        ui.sin_datos(ds)
                    else:
                        st.dataframe(df, hide_index=True, use_container_width=True, height=280)
                        ui.meta_caption(meta)
                        boton_csv(df, f"{ds}.csv", key=f"csv_{ds}")
                        if ruta_xlsx and Path(ruta_xlsx).exists():
                            boton_generico(
                                Path(ruta_xlsx).read_bytes(), Path(ruta_xlsx).name,
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                "⬇️ Descargar Excel original", key=f"xlsx_{ds}",
                            )

ui.footer()
