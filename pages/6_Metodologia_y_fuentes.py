"""
pages/6_Metodologia_y_fuentes.py
===================================
Transparencia metodológica: cómo se calcula cada análisis, de dónde vienen
los datos, y qué limitaciones tienen. Enlazada desde cada página de análisis
("¿Cómo se calcula esto?").
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import loaders, ui  # noqa: E402

ui.header(
    "Metodología y fuentes",
    "Cómo se calcula cada análisis de este visor, de dónde vienen los datos, y qué limitaciones tienen. "
    "Hardening razonable, no infalible; transparencia total, no promesas que los datos no respaldan.",
)

st.subheader("1. Fase ENSO (El Niño / La Niña / Neutral)")
st.markdown(
    "Se diagnostica con el **Índice Oceánico El Niño (ONI)** publicado por NOAA/CPC: la anomalía de "
    "temperatura superficial del mar en la región Niño 3.4 del Pacífico ecuatorial (120°W–170°W), "
    "promediada en ventanas móviles de 3 meses.\n\n"
    "- **El Niño**: ONI ≥ +0.5 °C\n"
    "- **La Niña**: ONI ≤ −0.5 °C\n"
    "- **Neutral**: entre −0.5 y +0.5 °C\n\n"
    "Para que la fase se considere *consolidada* (no solo una fluctuación puntual), esos valores deben "
    "sostenerse durante al menos 5 trimestres móviles consecutivos — es el criterio estándar de NOAA. "
    "La **intensidad** (débil/moderado/fuerte/muy fuerte) es función del valor absoluto del ONI."
)

st.subheader("2. Cruce ENSO × riesgo municipal")
st.markdown(
    "El cruce **amplifica** el riesgo asociado a la fase vigente; **no lo causa** por sí sola y "
    "**no es una probabilidad condicional** de evento extremo (eso requeriría un análisis histórico "
    "de frecuencias que está fuera del alcance actual — es un desarrollo futuro posible).\n\n"
    "Lo que hace el cruce es **seleccionar y ponderar** los índices de riesgo municipal del SNGRD "
    "que son coherentes con la fase:\n\n"
    "- **El Niño** (condición seca): incendios de cobertura vegetal, desabastecimiento hídrico, déficit "
    "hídrico.\n"
    "- **La Niña** (condición húmeda): inundaciones, crecientes súbitas, avenidas torrenciales, "
    "movimientos en masa.\n"
    "- **Neutral**: no hay amplificación dominante; se pondera de forma más uniforme (vendavales y "
    "otros índices no ligados a la fase).\n\n"
    "El **nivel** (alto/medio/bajo) resulta de terciles sobre el índice ponderado resultante, calculado "
    "sobre los 1.122 municipios evaluados."
)

st.subheader("3. Exposición: familias, ruralidad, estratos y recurrencia histórica")
st.markdown(
    "**Emergencias históricas (Sala de Crisis, UNGRD)**: se cruzan por código DIVIPOLA (5 dígitos) "
    "con los municipios de la capa de riesgo. Los conteos y sumas de familias/personas afectadas "
    "son **recurrencia histórica observada**, no una proyección de población en riesgo hoy.\n\n"
    "**Caracterización poblacional (DANE — familias reales, % rural/urbano, grupos étnicos, estratos "
    "REC-SUI): PENDIENTE.** Se intentó integrar vía la API Socrata de TerriData "
    "(`datos.gov.co/resource/64cq-xb2k`), que devuelve 404 (dataset dado de baja o migrado), y se buscó "
    "un sustituto de cobertura nacional sin éxito — lo disponible en datos.gov.co está fragmentado por "
    "municipio individual, no sirve para un cruce nacional. Se probaron rutas de descarga directa del "
    "Geoportal DANE para los archivos del CNPV 2018, sin resultado verificable. **Regla aplicada: "
    "ninguna fuente entra sin un HEAD/GET 200 y cobertura ≥1.100 municipios comprobada en vivo.** Por "
    "eso estas columnas existen en el modelo de datos (para no romper los cruces) pero están vacías, "
    "marcadas explícitamente como pendientes. Lo único integrado hoy de DANE es la **DIVIPOLA oficial** "
    "(nombres de municipio/departamento y coordenadas), verificada con 1.122 municipios de cobertura."
)

with st.expander("Reporte de no-cruces DIVIPOLA (municipios nuevos / cambios de código)"):
    import pandas as pd
    diag_path = Path(__file__).resolve().parents[1] / "data_lake" / "_diagnostico" / "divipola_no_cruza.csv"
    if diag_path.exists():
        df_diag = pd.read_csv(diag_path)
        st.dataframe(df_diag, hide_index=True, width="stretch")
        st.caption(
            "Generado por `scripts/diagnostico_divipola.py`: compara la capa de riesgo SNGRD, la "
            "DIVIPOLA-DANE y Sala de Crisis. Discrepancias reales (no simple ausencia de emergencias)."
        )
    else:
        ui.sin_datos("divipola_no_cruza", "Corre `python scripts/diagnostico_divipola.py`.")

st.subheader("4. Fuentes y tipos de dato")
st.dataframe(
    {
        "Fuente": ["IDEAM", "IDEAM", "NOAA/CPC", "DANE", "SNGRD", "UNGRD Sala de Crisis"],
        "Qué aporta": [
            "Alertas, observación (estaciones), pronóstico corto (ráster)",
            "BART (reportes tabulares diarios/mensuales)",
            "Índice Oceánico El Niño (ONI) — fase ENSO",
            "DIVIPOLA oficial (nombres/coordenadas de municipio)",
            "Índices de riesgo municipal (incendios, inundación, mov. en masa, etc.)",
            "Registro histórico de emergencias (familias/personas afectadas por evento)",
        ],
        "Tipo": ["vector/ráster", "tabla", "serie temporal", "tabla", "vector (polígonos)", "tabla"],
        "Resolución": [
            "estación / zona hidrográfica", "estación", "mensual (Pacífico ecuatorial)",
            "municipal (DIVIPOLA)", "municipal (DIVIPOLA)", "evento individual, geolocalizado a municipio",
        ],
        "Estado": [
            "preliminar", "preliminar", "oficial", "oficial", "oficial (SNGRD)", "oficial (UNGRD interno)",
        ],
    },
    hide_index=True, width="stretch",
)

st.subheader("5. Limitaciones conocidas")
st.markdown(
    "- Los datos de pronóstico y observación reciente de IDEAM son **preliminares**: sujetos a "
    "revisión y control de calidad por la entidad fuente; se sobrescriben a diario en origen.\n"
    "- Los no-cruces de DIVIPOLA (municipios nuevos, cambios de código) se reportan explícitamente "
    "(ver sección 3); no se inventan ni se rellenan con estimaciones.\n"
    "- La caracterización DANE (estratos, ruralidad, etnia, hogares reales) está pendiente — ver "
    "sección 3.\n"
    "- Las alertas hidrológicas están zonificadas por **zona/subzona hidrográfica**, no por municipio; "
    "el consolidado de Alertas por eso agrega a nivel de **departamento**, no de municipio.\n"
    "- El campo `COMENTARIOS` de Sala de Crisis se enmascara por regex (teléfonos, correos) antes de "
    "publicarse — es un filtro best-effort, no un sistema de anonimización certificado; no se garantiza "
    "remoción total de nombres propios en texto libre.\n"
    "- Esta app **nunca** consulta IDEAM/NOAA/DANE en vivo: todo proviene de snapshots periódicos "
    "(`latest.json`) generados por un cron de GitHub Actions. Si algo cambió en la fuente original hace "
    "unos minutos, el visor aún no lo refleja.\n"
    "- El producto comunica riesgo **amplificado por la fase ENSO**, no una probabilidad de ocurrencia "
    "de eventos extremos."
)

st.subheader("6. Seguridad y datos personales (app pública)")
st.markdown(
    "Este visor es de **solo lectura y público** (sin inicio de sesión). El endurecimiento aplicado es "
    "razonable para ese perfil de riesgo, no un blindaje total:\n\n"
    "- Sin credenciales en el repositorio (los secretos opcionales, como OSS, solo viven en `st.secrets`).\n"
    "- Los filtros de la interfaz (departamento, municipio, fase, nivel) se validan contra listas "
    "cerradas derivadas de los propios datos — no se interpola texto libre del usuario en rutas de "
    "archivo ni en llamadas externas.\n"
    "- Sin `eval`/`exec`/`os.system` sobre ninguna entrada.\n"
    "- Dependencias con versión fija en `requirements.txt` (revisar CVEs periódicamente).\n"
    "- Streamlit Community Cloud gestiona el servidor/proxy: la app puede fijar `enableXsrfProtection`, "
    "pero **no controla** cabeceras como CSP, `X-Content-Type-Options` o `Referrer-Policy` a nivel de "
    "servidor — eso requeriría un proxy propio o self-hosting."
)

ui.footer()
