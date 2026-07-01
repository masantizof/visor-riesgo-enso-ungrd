"""
pages/5_Fuentes_y_descargas.py
=================================
Catálogo navegable de todos los datasets del data_lake: qué son, cuándo se
actualizaron por última vez, de qué fuente vienen, y botón de descarga en
el formato nativo de cada uno (CSV/GeoJSON/PNG/Excel/grilla cruda).
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import loaders, ui  # noqa: E402
from src.downloads import boton_csv, boton_geojson, boton_png, boton_generico  # noqa: E402

ui.header(
    "Fuentes y descargas",
    "Catálogo completo de los datos que alimentan el visor: fuente, fecha de última "
    "actualización y descarga directa. Todo proviene de snapshots periódicos — la app "
    "<b>nunca</b> consulta IDEAM/NOAA en vivo.",
)

disponibles = set(loaders.datasets_disponibles())
n_total = len(loaders.CATALOGO)
n_disp = len(disponibles & set(loaders.CATALOGO))

ui.kpi_row([
    {"label": "Datasets en el catálogo", "value": str(n_total), "icon": "📚"},
    {"label": "Con snapshot disponible", "value": str(n_disp), "icon": "✅"},
    {"label": "Pendientes / sin snapshot", "value": str(n_total - n_disp), "icon": "⏳"},
])

st.divider()

filtro_estado = st.radio("Mostrar", ["Todos", "Solo disponibles", "Solo pendientes"], horizontal=True)

fc1, fc2, fc3 = st.columns(3)
with fc1:
    filtro_texto = st.text_input("Buscar por nombre o descripción", "")
with fc2:
    tipos_disp = sorted({t for _, t, _ in loaders.CATALOGO.values()})
    filtro_tipo = st.multiselect("Tipo de dato", tipos_disp)
with fc3:
    fuentes_disp = sorted({f for _, _, f in loaders.CATALOGO.values()})
    filtro_fuente = st.multiselect("Fuente", fuentes_disp)

for dataset, (nombre, tipo, fuente) in loaders.CATALOGO.items():
    esta = dataset in disponibles
    if filtro_estado == "Solo disponibles" and not esta:
        continue
    if filtro_estado == "Solo pendientes" and esta:
        continue
    if filtro_texto and filtro_texto.lower() not in nombre.lower() and filtro_texto.lower() not in dataset.lower():
        continue
    if filtro_tipo and tipo not in filtro_tipo:
        continue
    if filtro_fuente and fuente not in filtro_fuente:
        continue

    with st.expander(f"{'✅' if esta else '⏳'}  {nombre}  ·  `{dataset}`"):
        st.caption(f"Tipo: {tipo} · Fuente: {fuente}")
        if not esta:
            ui.sin_datos(dataset)
            continue

        meta = loaders.metadatos(dataset)
        ui.meta_caption(meta)
        with st.popover("Ver manifiesto completo (JSON)"):
            st.json(meta)

        kind = meta.get("kind")
        files = meta.get("files", {})

        if kind == "unavailable":
            ui.no_publicado(meta.get("note", "La fuente no tiene publicado este dataset ahora mismo."))

        elif kind == "vector":
            geo = loaders.cargar_geojson(dataset)
            tabla = loaders.cargar_tabla(dataset)
            c1, c2 = st.columns(2)
            with c1:
                if tabla is not None:
                    boton_csv(tabla, f"{dataset}.csv", key=f"cat_csv_{dataset}")
            with c2:
                if geo is not None:
                    boton_geojson(geo, f"{dataset}.geojson", key=f"cat_geo_{dataset}")

        elif kind == "raster":
            r = loaders.cargar_raster(dataset)
            if r:
                png, _, _ = r
                boton_png(png, f"{dataset}.png", key=f"cat_png_{dataset}")

        elif kind == "table":
            df, ruta_xlsx = loaders.cargar_tabla_con_respaldo_xlsx(dataset)
            c1, c2 = st.columns(2)
            with c1:
                if df is not None:
                    boton_csv(df, f"{dataset}.csv", key=f"cat_csv_{dataset}")
            with c2:
                if ruta_xlsx and Path(ruta_xlsx).exists():
                    boton_generico(
                        Path(ruta_xlsx).read_bytes(), Path(ruta_xlsx).name,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "⬇️ Descargar Excel", key=f"cat_xlsx_{dataset}",
                    )

        elif kind == "image_set":
            cols = st.columns(4)
            for i, (clave, ruta) in enumerate(files.items()):
                p = Path(ruta)
                if p.exists():
                    with cols[i % 4]:
                        boton_png(p, p.name, etiqueta=f"⬇️ {clave}", key=f"cat_imgset_{dataset}_{clave}")

        elif kind == "grid":
            p = Path(files.get("data", ""))
            if p.exists():
                boton_generico(
                    p.read_bytes(), p.name, "application/octet-stream",
                    f"⬇️ Descargar {p.name} ({meta.get('size_bytes', 0) / 1e6:.1f} MB)",
                    key=f"cat_grid_{dataset}",
                )

        elif kind == "enso":
            st.json({k: meta.get(k) for k in ("fase", "intensidad", "oni", "trimestre")})
            p = Path(files.get("oni_table", ""))
            if p.exists():
                import pandas as pd
                boton_csv(pd.read_parquet(p), "oni_historico.csv", key=f"cat_csv_{dataset}")

        elif kind == "enso_risk_cross":
            tabla = loaders.cargar_riesgo_enso_tabla()
            geo = loaders.cargar_riesgo_enso_geojson()
            c1, c2 = st.columns(2)
            with c1:
                if tabla is not None:
                    boton_csv(tabla, f"{dataset}.csv", key=f"cat_csv_{dataset}")
            with c2:
                if geo is not None:
                    boton_geojson(geo, f"{dataset}.geojson", key=f"cat_geo_{dataset}")

st.divider()
st.subheader("Datos de referencia estáticos")
st.caption(
    "No forman parte del cron de ingesta diaria: son insumos fijos que se actualizan por separado."
)

with st.expander("✅  Índices de riesgo municipal SNGRD  ·  `indices_riesgo_municipal`"):
    st.caption("Tipo: poligonos · Fuente: SNGRD (geometría simplificada para uso en el navegador)")
    geo_ref = loaders.cargar_referencia_indices_riesgo()
    if geo_ref is not None:
        boton_geojson(geo_ref, "indices_riesgo_municipal.geojson", key="cat_geo_indices_ref")

with st.expander("✅  Emergencias históricas Sala de Crisis  ·  `sala_crisis`"):
    st.caption(
        "Tipo: tabla · Fuente: UNGRD Sala de Crisis. COMENTARIOS enmascarado (teléfonos/correos "
        "ocultos) porque la app es pública."
    )
    emerg = loaders.cargar_emergencias()
    if emerg is not None:
        boton_csv(emerg, "emergencias_sala_crisis.csv", key="cat_csv_sala_crisis")

ui.footer()
