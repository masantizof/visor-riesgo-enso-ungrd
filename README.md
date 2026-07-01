# Visor de Riesgo Climático ENSO — UNGRD

Visor web (Streamlit) de la **Subdirección para el Conocimiento del Riesgo** de la
Unidad Nacional para la Gestión del Riesgo de Desastres (UNGRD). Permite consultar,
analizar, visualizar y **descargar** los datos hidrometeorológicos y de riesgo que
alimentan el seguimiento del fenómeno ENSO (El Niño / La Niña) en Colombia.

## Principio de diseño: la app nunca llama a IDEAM/NOAA en vivo

```
GitHub Actions (cron)  ──►  extractores  ──►  data_lake/{dataset}/dt=YYYY-MM-DD/ + latest.json
                                                            │
                                                Streamlit lee vía src/loaders.py  ◄── usuario
```

- `ideam_extractor.py` — capas ArcGIS (vector/ráster) y reportes BART (Excel).
- `ideam_wrf_cpt.py` — grillas WRF/GFS, predicción estacional CPT, índices ENSO (ONI/NOAA).
- `ideam_enso_risk.py` — cruce fase ENSO × índices de riesgo municipal (SNGRD).

Los tres son a la vez **script** (los corre el cron de `.github/workflows/ingesta-ideam.yml`)
y **módulo** (la app importa sus funciones `load_*`/`latest_meta`). Si un dataset no
tiene snapshot todavía, la página lo indica sin romperse.

## Estructura

```
app.py                          # Inicio · Panorama ENSO
pages/
  1_Riesgo_climatico_ENSO.py    # producto central: selector de fase + mapa + tabla
  2_Alertas.py                  # alertas hidrológicas, IDD, ICV
  3_Observacion_diaria.py       # estaciones (mapa) + reportes BART (tablas)
  4_Pronostico.py               # ráster corto plazo + galería CPT + grillas WRF/GFS
  5_Fuentes_y_descargas.py      # catálogo completo con descarga por dataset
src/
  loaders.py                    # wrappers cacheados sobre los load_* de los 3 scripts
  maps.py                       # folium: capas vectoriales, puntos, ráster, leyenda
  ui.py                         # paleta UNGRD, header/footer, KPIs, semáforo ENSO
  downloads.py                  # botones de descarga CSV/GeoJSON/PNG
data/reference/indices_riesgo_municipal.geojson   # capa SNGRD simplificada (~5.6 MB)
data_lake/                      # snapshots (los produce el extractor / Actions)
ideam_extractor.py, ideam_wrf_cpt.py, ideam_enso_risk.py   # extractores (raíz del repo)
scripts/simplificar_indices_riesgo.py   # preparación única (no corre en producción)
.github/workflows/ingesta-ideam.yml     # cron de ingesta
```

## Paleta institucional

Extraída del logo (`assets/LOGO_UNGRD.png`) por muestreo de píxeles, no inventada:

| Color | Hex | Uso |
|---|---|---|
| Azul institucional | `#1F3460` | sidebar, títulos, capa primaria |
| Amarillo/dorado | `#FECC17` | acentos, alerta amarilla |
| Rojo | `#D80C28` | alerta roja / riesgo alto |

Definida en `.streamlit/config.toml` (`[theme]`) y en `src/ui.py` (`COLORS`).

## Correr en local

```bash
pip install -r requirements.txt
# (opcional) sembrar datos reales antes de correr la app:
python ideam_extractor.py --all
python ideam_wrf_cpt.py --all
python ideam_enso_risk.py --indices data/reference/indices_riesgo_municipal.geojson

streamlit run app.py
```

Si `data_lake/` está vacío, la app corre igual: cada sección muestra un aviso de
"sin snapshot disponible" en vez de fallar.

### Regenerar la capa de referencia (solo si cambia la fuente)

`data/reference/indices_riesgo_municipal.geojson` es una versión simplificada
(Douglas-Peucker, ~5.6 MB) del insumo original de 252 MB, para que sea viable
commitearla a GitHub y renderizarla en el navegador. Si llega una versión nueva
del insumo:

```bash
python scripts/simplificar_indices_riesgo.py \
  --entrada DatosIndice.geojson \
  --salida data/reference/indices_riesgo_municipal.geojson \
  --tolerancia 0.001
```

## Desplegar

1. **GitHub**: pushear este repo (ya incluye `.gitignore` para no subir el insumo
   crudo de 252 MB ni las grillas pesadas de WRF/GFS).
2. **Streamlit Community Cloud**: conectar el repo, `app.py` como entrypoint.
   No requiere `geopandas`/`leafmap` (evitados deliberadamente: rompen el build ahí).
3. **Activar la ingesta**: la Action `.github/workflows/ingesta-ideam.yml` ya trae
   `workflow_dispatch` (correrla a mano la primera vez desde la pestaña *Actions*)
   y un cron programado. Necesita permiso `contents: write` (ya declarado) para
   commitear los snapshots nuevos de vuelta al repo.
4. **OSS (opcional)**: si se quiere espejar a Alibaba OSS, definir en *Settings →
   Secrets* del repo: `OSS_ENDPOINT`, `OSS_BUCKET`, `OSS_ACCESS_KEY_ID`,
   `OSS_ACCESS_KEY_SECRET`. Sin esos secrets, es un no-op.

## Pendientes conocidos

- `alertas_idd` y `alertas_icv` (capas vectoriales) devolvieron error 500 del
  servidor de IDEAM en la última corrida; la página **Alertas** lo muestra con
  gracia y el cron reintenta cada 2 h.
- Algunos reportes BART (Excel con tipos de dato mixtos en la fuente) no se
  logran tabular a Parquet automáticamente; la app ofrece igual el Excel crudo
  para descarga.
- Los datos de pronóstico y observación reciente son **preliminares**: no
  reemplazan los boletines oficiales de IDEAM ni las alertas de UNGRD.
