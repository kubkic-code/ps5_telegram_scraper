"""
app.py — Streamlit Analytický Dashboard pro Arbitráž Garmin hodinek
Python Agent | KPI metriky, aktivní příležitosti, analýza likvidity, Plotly grafy
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# Přidání cest pro importy modulů scraper a dashboard
_current_dir = Path(__file__).resolve().parent
_root_dir = _current_dir.parent
_scraper_dir = _root_dir / "scraper"

for p in (str(_root_dir), str(_scraper_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

from dashboard.analytics import (
    extrahuj_model,
    nacti_data_df,
    spocti_agregace_modelu,
    spocti_kpi,
    top_modely_ceny,
)

# ---------------------------------------------------------------------------
# Konfigurace aplikace
# ---------------------------------------------------------------------------

DB_PATH = Path(os.getenv("DB_PATH", "/data/market.db"))

st.set_page_config(
    page_title="Garmin Watch Arbitrage — Analytics",
    page_icon="⌚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS pro moderní a prémiový vzhled
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        letter-spacing: -0.5px;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        color: #888888;
        font-size: 1rem;
        margin-bottom: 1.5rem;
    }
    .metric-box {
        background: linear-gradient(135deg, rgba(255, 255, 255, 0.05) 0%, rgba(255, 255, 255, 0.02) 100%);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 18px 22px;
        backdrop-filter: blur(8px);
    }
    .stMetric label {
        font-size: 0.85rem !important;
        color: #a0a0a0 !important;
    }
    .stMetric [data-testid="stMetricValue"] {
        font-size: 1.8rem !important;
        font-weight: 700 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Načtení dat
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30)
def ziskej_data(cesta_k_db: str) -> pd.DataFrame:
    """Načte data z databáze s krátkou mezipamětí."""
    return nacti_data_df(cesta_k_db)


df_raw = ziskej_data(str(DB_PATH))

# ---------------------------------------------------------------------------
# Postranní panel (Sidebar) — Filtry
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("⚙️ Filtry & Nastavení")

    if st.button("🔄 Obnovit data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.caption(f"📁 Databáze: `{DB_PATH}`")
    st.caption(f"Celkem záznamů v DB: **{len(df_raw)}**")
    st.divider()

    # Filtr portálu
    vybrany_portal = st.selectbox(
        "🌐 Portál",
        options=["Všechny portály", "Bazoš.cz", "Vinted.cz"],
        index=0,
    )

    # Filtr modelů
    dostupne_modely = sorted([m for m in df_raw["model"].dropna().unique() if m != "Ostatní"])
    dostupne_modely.append("Ostatní")

    vybrane_modely = st.multiselect(
        "⌚ Model Garmin",
        options=dostupne_modely,
        default=[],
        placeholder="Všechny modely",
    )

    # Filtr ceny
    ceny_valid = df_raw["price"].dropna()
    min_db_cena = int(ceny_valid.min()) if not ceny_valid.empty else 0
    max_db_cena = int(ceny_valid.max()) if not ceny_valid.empty else 30000

    min_cena, max_cena = st.slider(
        "💰 Cenové rozpětí (Kč)",
        min_value=min_db_cena,
        max_value=max(max_db_cena, min_db_cena + 1000),
        value=(min_db_cena, max(max_db_cena, min_db_cena + 1000)),
        step=500,
    )

    # Textové vyhledávání
    hledany_text = st.text_input("🔍 Vyhledat v názvu", value="").strip().lower()

    st.divider()
    st.markdown(
        """
        **Garmin Arbitrage Platform**  
        • 24/7 Multi-Portal Scraper  
        • Sales Tracker (12h cyklus)  
        • SQLite databáze  
        """
    )

# ---------------------------------------------------------------------------
# Aplikace filtrů na DataFrame
# ---------------------------------------------------------------------------

df_filtered = df_raw.copy()

if vybrany_portal == "Bazoš.cz":
    df_filtered = df_filtered[df_filtered["portal"] == "bazos"]
elif vybrany_portal == "Vinted.cz":
    df_filtered = df_filtered[df_filtered["portal"] == "vinted"]

if vybrane_modely:
    df_filtered = df_filtered[df_filtered["model"].isin(vybrane_modely)]

if not df_filtered.empty and "price" in df_filtered.columns:
    df_filtered = df_filtered[
        (df_filtered["price"].isna())
        | ((df_filtered["price"] >= min_cena) & (df_filtered["price"] <= max_cena))
    ]

if hledany_text and not df_filtered.empty:
    df_filtered = df_filtered[
        df_filtered["title"].str.lower().str.contains(hledany_text, na=False)
    ]

# ---------------------------------------------------------------------------
# Hlavička & KPI Metriky
# ---------------------------------------------------------------------------

st.markdown('<div class="main-title">⌚ Garmin Watch Arbitrage</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Analytická platforma pro sledování trhu chytrých hodinek, identifikaci cenových anomálií a rychlosti prodeje</div>',
    unsafe_allow_html=True,
)

kpi = spocti_kpi(df_filtered)

kpi_col1, kpi_col2, kpi_col3, kpi_col4 = st.columns(4)

with kpi_col1:
    st.metric(
        label="🟢 Aktivní nabídky",
        value=f"{kpi['pocet_aktivnich']} ks",
        help="Aktuálně dostupné inzeráty na trhu se statusem 'active'",
    )

with kpi_col2:
    st.metric(
        label="🏷️ Prodané nabídky",
        value=f"{kpi['pocet_prodanych']} ks",
        help="Inzeráty ověřené Trackerem jako prodané se statusem 'sold'",
    )

with kpi_col3:
    median_h = kpi["median_doby_hodin"]
    zobrazeni_casu = f"{median_h:.1f} h" if median_h < 48 else f"{median_h / 24.0:.1f} dní"
    st.metric(
        label="⏱️ Medián doby do prodeje",
        value=zobrazeni_casu,
        help="Typická doba od zveřejnění po zmizení inzerátu (v hodinách)",
    )

with kpi_col4:
    # Bonusová metrika: Průměrná cena prodaných
    sold_fil = df_filtered[df_filtered["status"] == "sold"]
    avg_sold_price = int(sold_fil["price"].mean()) if not sold_fil.empty and sold_fil["price"].notna().any() else 0
    st.metric(
        label="💎 Průměrná prodejní cena",
        value=f"{avg_sold_price:,} Kč".replace(",", " ") if avg_sold_price > 0 else "N/A",
        help="Průměrná realizovaná cena u prodaných hodinek",
    )

st.write("")

# ---------------------------------------------------------------------------
# Záložky: Aktivní příležitosti & Analýza likvidity
# ---------------------------------------------------------------------------

tab_aktivni, tab_likvidita = st.tabs([
    "🎯 Aktivní příležitosti k arbitráži",
    "📊 Analýza likvidity & Ceny modelů",
])

# --- TAB 1: Aktivní inzeráty ---
with tab_aktivni:
    st.subheader("Aktuálně dostupné inzeráty")

    aktivni_df = df_filtered[df_filtered["status"] == "active"].copy()

    if aktivni_df.empty:
        st.info("Žádné aktivní inzeráty neodpovídají zadaným filtrům.")
    else:
        # Možnosti řazení
        razeni_col1, razeni_col2, _ = st.columns([2, 2, 4])
        with razeni_col1:
            razeni_podle = st.selectbox(
                "Řadit podle:",
                options=[
                    "Nejnovější (výchozí)",
                    "Nejlevnější cena",
                    "Nejdražší cena",
                    "Model (A-Z)",
                ],
            )

        if razeni_podle == "Nejlevnější cena":
            aktivni_df = aktivni_df.sort_values(by=["price", "found_date"], ascending=[True, False])
        elif razeni_podle == "Nejdražší cena":
            aktivni_df = aktivni_df.sort_values(by=["price", "found_date"], ascending=[False, False])
        elif razeni_podle == "Model (A-Z)":
            aktivni_df = aktivni_df.sort_values(by=["model", "found_date"], ascending=[True, False])
        else:
            aktivni_df = aktivni_df.sort_values(by=["found_date", "db_id"], ascending=[False, False])

        # Příprava tabulky pro zobrazení
        zobrazeni_df = aktivni_df[[
            "portal",
            "model",
            "title",
            "price",
            "found_date",
            "url",
        ]].copy()

        # Formátování portálu na hezký text
        zobrazeni_df["portal"] = zobrazeni_df["portal"].map(
            {"bazos": "Bazoš.cz", "vinted": "Vinted.cz"}
        ).fillna(zobrazeni_df["portal"])

        st.dataframe(
            zobrazeni_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "portal": st.column_config.TextColumn("Portál", width="small"),
                "model": st.column_config.TextColumn("Model", width="medium"),
                "title": st.column_config.TextColumn("Název inzerátu", width="large"),
                "price": st.column_config.NumberColumn("Cena", format="%d Kč", width="small"),
                "found_date": st.column_config.DatetimeColumn("Nalezeno", format="D.M.YYYY HH:mm", width="medium"),
                "url": st.column_config.LinkColumn("Odkaz", display_text="Přejít na inzerát ↗", width="medium"),
            },
        )
        st.caption(f"Zobrazeno {len(zobrazeni_df)} aktivních inzerátů.")

# --- TAB 2: Analýza likvidity a cen ---
with tab_likvidita:
    st.subheader("Likvidita a cenové hladiny modelů Garmin")

    agregovano = spocti_agregace_modelu(df_filtered)

    if agregovano.empty:
        st.info("Zatím nejsou k dispozici žádná data o prodaných inzerátech pro zvolené filtry.")
    else:
        graf_col, tab_col = st.columns([5, 4])

        with graf_col:
            st.markdown("##### 🏆 TOP 5 nejprodávanějších modelů — Průměrná cena")
            top5_df = top_modely_ceny(agregovano, n=5)

            fig = px.bar(
                top5_df,
                x="model",
                y="prumerna_cena",
                text="prumerna_cena",
                color="prumerna_cena",
                color_continuous_scale="Tealgrn",
                labels={
                    "model": "Model",
                    "prumerna_cena": "Průměrná prodejní cena (Kč)",
                    "pocet_prodano": "Prodáno kusů",
                },
                hover_data=["pocet_prodano", "prumerna_doba_hodin"],
            )

            fig.update_traces(
                texttemplate="%{text:,} Kč".replace(",", " "),
                textposition="outside",
                cliponaxis=False,
            )
            fig.update_layout(
                xaxis_title="",
                yaxis_title="Cena (Kč)",
                coloraxis_showscale=False,
                margin=dict(l=20, r=20, t=30, b=30),
                height=420,
            )

            st.plotly_chart(fig, use_container_width=True)

        with tab_col:
            st.markdown("##### 📋 Přehled likvidity dle modelů")
            st.dataframe(
                agregovano,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "model": st.column_config.TextColumn("Model"),
                    "pocet_prodano": st.column_config.NumberColumn("Prodáno (ks)"),
                    "prumerna_cena": st.column_config.NumberColumn("Prům. cena", format="%d Kč"),
                    "prumerna_doba_hodin": st.column_config.NumberColumn("Doba prodeje", format="%.1f h"),
                },
            )
            st.caption("Statistiky jsou počítány výhradně z inzerátů se statusem 'sold'.")
