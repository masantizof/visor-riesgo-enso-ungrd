"""
src/ui.py
=========
Componentes de marca UNGRD: paleta institucional (extraída del logo,
`assets/LOGO_UNGRD.png`), CSS global, encabezado, pie de página, tarjetas
KPI y semáforo de fase ENSO. Se reutilizan en todas las páginas para que
la distribución y el estilo calquen las imágenes de referencia.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
LOGO_PATH = ROOT / "assets" / "LOGO_UNGRD.png"


@st.cache_data(show_spinner=False)
def _logo_base64() -> str:
    return base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")

# --------------------------------------------------------------------------- #
# Paleta institucional UNGRD — extraída por muestreo de píxeles del logo
# (no inventada). Colores de nivel de riesgo: escala semáforo accesible.
# --------------------------------------------------------------------------- #
COLORS = {
    "navy": "#1F3460",       # azul institucional (dominante en el logo)
    "navy_dark": "#16264A",  # variante oscura (sidebar/hover)
    "gold": "#FECC17",       # amarillo/dorado institucional (mano del logo)
    "red": "#D80C28",        # rojo institucional (franja del logo)
    "white": "#FFFFFF",
    "gray_bg": "#F2F4F8",
    "gray_text": "#5B6472",
}

NIVEL_COLOR = {
    "alto": "#D7263D",
    "medio": "#F4A83D",
    "bajo": "#2E8B57",
    "sin dato": "#B0B0B0",
}

FASE_COLOR = {
    "El Niño": "#D7263D",
    "La Niña": "#1F6FEB",
    "Neutral": "#5B6472",
}

KPI_PALETTE = [
    ("#E7F0FA", "#1F3460"),  # azul
    ("#E9F7EF", "#1E8449"),  # verde
    ("#FDEDEC", "#C0392B"),  # rojo
    ("#FEF6E0", "#B7860B"),  # ámbar
    ("#F1EAFB", "#6C3FBF"),  # morado
    ("#EAF6F8", "#117A8B"),  # cian
]


def inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .stApp {{ background-color: {COLORS['white']}; }}

        [data-testid="stSidebar"] {{
            background-color: {COLORS['navy']};
        }}
        [data-testid="stSidebar"] * {{
            color: {COLORS['white']} !important;
        }}
        [data-testid="stSidebarNav"] a {{
            border-radius: 8px;
            margin: 2px 8px;
        }}
        [data-testid="stSidebarNav"] a:hover {{
            background-color: {COLORS['navy_dark']};
        }}
        [data-testid="stSidebarNav"] a[aria-current="page"] {{
            background-color: {COLORS['white']};
        }}
        [data-testid="stSidebarNav"] a[aria-current="page"] span {{
            color: {COLORS['navy']} !important;
            font-weight: 700;
        }}

        [data-testid="stSidebarContent"] {{
            display: flex;
            flex-direction: column;
        }}
        [data-testid="stSidebarContent"] div:has(> .ungrd-sidebar-brand) {{
            order: -1;
        }}

        .ungrd-sidebar-brand {{
            background-color: {COLORS['white']};
            border-radius: 12px;
            padding: 10px 14px;
            margin: 6px 8px 2px 8px;
        }}
        .ungrd-sidebar-title {{
            color: {COLORS['white']} !important;
            font-weight: 800;
            font-size: 1.15rem;
            line-height: 1.35rem;
            text-align: center;
            margin: 10px 8px 18px 8px;
        }}

        .ungrd-header-title {{
            color: {COLORS['navy']};
            font-weight: 800;
            font-size: 2.1rem;
            margin-bottom: 0.15rem;
        }}
        .ungrd-header-sub {{
            color: {COLORS['gray_text']};
            font-size: 0.98rem;
            line-height: 1.5rem;
            margin-bottom: 1.1rem;
        }}
        .ungrd-header-sub b {{ color: {COLORS['navy']}; }}

        .ungrd-kpi-card {{
            border-radius: 14px;
            padding: 14px 16px;
            height: 100%;
        }}
        .ungrd-kpi-icon {{ font-size: 1.3rem; }}
        .ungrd-kpi-value {{ font-size: 1.7rem; font-weight: 800; line-height: 2rem; }}
        .ungrd-kpi-label {{ font-size: 0.82rem; font-weight: 600; opacity: 0.85; }}
        .ungrd-kpi-sub {{ font-size: 0.78rem; opacity: 0.7; }}

        .ungrd-badge {{
            display: inline-block; padding: 3px 12px; border-radius: 999px;
            font-weight: 700; font-size: 0.82rem; color: white;
        }}

        .ungrd-footer {{
            margin-top: 2.2rem; padding-top: 0.8rem;
            border-top: 1px solid #E3E6EC;
            color: {COLORS['gray_text']}; font-size: 0.78rem; line-height: 1.35rem;
        }}
        .ungrd-meta {{
            color: {COLORS['gray_text']}; font-size: 0.78rem; margin-top: -6px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def sidebar_brand() -> None:
    """Tarjeta blanca con el logo + nombre del visor, arriba del menú (como en las
    imágenes de referencia). Se llama una sola vez, desde app.py."""
    inject_css()
    with st.sidebar:
        img_html = (
            f'<img src="data:image/png;base64,{_logo_base64()}" style="width:100%;" />'
            if LOGO_PATH.exists() else ""
        )
        st.markdown(
            f"""
            <div class="ungrd-sidebar-brand">{img_html}</div>
            <div class="ungrd-sidebar-title">Visor de Riesgo<br/>Climático ENSO</div>
            """,
            unsafe_allow_html=True,
        )


def header(titulo: str, subtitulo_html: str = "") -> None:
    inject_css()
    st.markdown(f"<div class='ungrd-header-title'>{titulo}</div>", unsafe_allow_html=True)
    if subtitulo_html:
        st.markdown(f"<div class='ungrd-header-sub'>{subtitulo_html}</div>", unsafe_allow_html=True)


def footer() -> None:
    st.markdown(
        f"""
        <div class="ungrd-footer">
        <b>Fuentes:</b> IDEAM (OSPA / BART / WRF-GFS) y NOAA/CPC (índices ENSO).
        Los datos de pronóstico y observación reciente son <b>preliminares</b> y están
        sujetos a revisión y control de calidad por parte de las entidades fuente.
        Este visor no reemplaza los boletines oficiales de IDEAM ni las alertas de UNGRD.<br/>
        Subdirección para el Conocimiento del Riesgo — Unidad Nacional para la Gestión del Riesgo de Desastres (UNGRD).
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi_card(label: str, value: str, sub: str = "", icon: str = "📊", palette_idx: int = 0) -> str:
    bg, fg = KPI_PALETTE[palette_idx % len(KPI_PALETTE)]
    return f"""
    <div class="ungrd-kpi-card" style="background-color:{bg}; color:{fg};">
        <div class="ungrd-kpi-icon">{icon}</div>
        <div class="ungrd-kpi-value">{value}</div>
        <div class="ungrd-kpi-label">{label}</div>
        {f'<div class="ungrd-kpi-sub">{sub}</div>' if sub else ''}
    </div>
    """


def kpi_row(cards: list[dict]) -> None:
    """cards: [{label, value, sub, icon}], se colorean en secuencia con KPI_PALETTE."""
    cols = st.columns(len(cards))
    for i, (c, col) in enumerate(zip(cards, cols)):
        with col:
            st.markdown(
                kpi_card(c.get("label", ""), c.get("value", "—"), c.get("sub", ""),
                         c.get("icon", "📊"), i),
                unsafe_allow_html=True,
            )


def badge(texto: str, color: str) -> str:
    return f'<span class="ungrd-badge" style="background-color:{color};">{texto}</span>'


def semaforo_enso(assessment: Optional[dict]) -> None:
    """Bloque de semáforo con la fase ENSO vigente (ONI), intensidad y teleconexión."""
    if assessment is None:
        st.info("Aún no hay snapshot de índices ENSO. Corre `ideam_wrf_cpt.py --enso` para generarlo.")
        return
    fase = assessment.get("fase", "Neutral")
    color = FASE_COLOR.get(fase, COLORS["gray_text"])
    oni = assessment.get("oni")
    intensidad = assessment.get("intensidad", "—")
    tele = assessment.get("teleconexion_colombia", {})

    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown(
            f"""
            <div style="text-align:center; padding: 18px; border-radius: 16px;
                        background-color:{COLORS['gray_bg']};">
                <div style="width:78px;height:78px;border-radius:50%;background-color:{color};
                            margin:0 auto 10px auto;"></div>
                <div style="font-size:1.3rem;font-weight:800;color:{color};">{fase}</div>
                <div style="color:{COLORS['gray_text']};font-size:0.85rem;">
                    Intensidad: {intensidad} · ONI: {oni:+.2f} °C
                </div>
                <div style="color:{COLORS['gray_text']};font-size:0.75rem;margin-top:4px;">
                    {assessment.get('trimestre','')} {assessment.get('anio','')}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(f"**Precipitación esperada:** {tele.get('precipitacion','—')}")
        st.markdown(f"**Temperatura esperada:** {tele.get('temperatura','—')}")
        riesgos = tele.get("riesgos", [])
        if riesgos:
            st.markdown("**Riesgos que la fase amplifica:** " + ", ".join(riesgos))
        st.caption(assessment.get("nota", ""))
    st.caption(f"Actualizado: {assessment.get('actualizado','—')} · Fuente: {assessment.get('fuente','NOAA/CPC')}")


def meta_caption(meta: Optional[dict]) -> None:
    """Caption estándar 'Actualizado: ... · Fuente: ...' para cualquier dataset."""
    if meta is None:
        st.caption("Sin snapshot disponible todavía.")
        return
    st.caption(
        f"Actualizado: {meta.get('updated_at','—')} · "
        f"Fuente: {meta.get('descripcion', meta.get('source_url','IDEAM'))}"
    )


def sin_datos(dataset: str, detalle: str = "") -> None:
    st.warning(
        f"No hay snapshot disponible para **{dataset}** todavía. "
        "El extractor lo generará en la próxima corrida programada (o corre el script manualmente). "
        + detalle
    )
