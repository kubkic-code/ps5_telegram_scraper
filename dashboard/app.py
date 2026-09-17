"""
app.py — Streamlit Analytický Dashboard pro Arbitráž PlayStation 5
Python Agent | KPI metriky, kalkulačka podhodnocení, analýza likvidity, Plotly grafy
"""

from __future__ import annotations

import os
import sqlite3
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
    exportuj_do_csv_excel,
    nacti_data_df,
    nacti_prodana_data_df,
    spocti_agregace_edice,
    spocti_kpi,
    spocti_median_ceny_dle_edice,
    top_edice_ceny,
    vypocti_profit_aktivnich,
)

# ---------------------------------------------------------------------------
# Konfigurace aplikace
# ---------------------------------------------------------------------------

DB_PATH = Path(os.getenv("DB_PATH", "/data/market.db"))

st.set_page_config(
    page_title="PS5 Arbitrage — Analytics Dashboard",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS — Prémiový PS5 dark design
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .main-title {
        font-size: 2.6rem;
        font-weight: 800;
        letter-spacing: -1px;
        margin-bottom: 0.2rem;
        background: linear-gradient(135deg, #00c8ff 0%, #0070cc 50%, #003fa3 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    .sub-title {
        color: #8892a4;
        font-size: 1rem;
        margin-bottom: 1.8rem;
        font-weight: 400;
    }
    .metric-box {
        background: linear-gradient(135deg, rgba(0,200,255,0.06) 0%, rgba(0,63,163,0.04) 100%);
        border: 1px solid rgba(0,200,255,0.15);
        border-radius: 16px;
        padding: 20px 24px;
        backdrop-filter: blur(10px);
        transition: border-color 0.3s ease;
    }
    .metric-box:hover {
        border-color: rgba(0,200,255,0.35);
    }
    .stMetric label {
        font-size: 0.82rem !important;
        color: #8892a4 !important;
        font-weight: 500 !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .stMetric [data-testid="stMetricValue"] {
        font-size: 1.9rem !important;
        font-weight: 800 !important;
        color: #e8eaf6 !important;
    }

    /* Super kauf badge */
    .super-kauf-badge {
        display: inline-block;
        background: linear-gradient(135deg, #00e676, #00c853);
        color: #003300;
        font-weight: 700;
        font-size: 0.75rem;
        padding: 2px 8px;
        border-radius: 20px;
        margin-left: 6px;
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0% { box-shadow: 0 0 0 0 rgba(0,230,118,0.4); }
        70% { box-shadow: 0 0 0 8px rgba(0,230,118,0); }
        100% { box-shadow: 0 0 0 0 rgba(0,230,118,0); }
    }

    /* Profit positive color */
    .profit-positive {
        color: #00e676;
        font-weight: 700;
    }
    .profit-negative {
        color: #ff5252;
        font-weight: 600;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0a0e1a 0%, #0d1428 100%);
        border-right: 1px solid rgba(0,200,255,0.1);
    }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        font-weight: 600;
        font-size: 0.9rem;
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
    st.markdown("### 🎮 PS5 Arbitrage")
    st.caption("Analytická platforma pro trh PlayStation 5")

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

    # Filtr edice
    dostupne_edice = ["Disk", "Digital", "Unknown"]
    vybrane_edice = st.multiselect(
        "💿 Edice PS5",
        options=dostupne_edice,
        default=[],
        placeholder="Všechny edice",
    )

    # Filtr Slim
    slim_filtr = st.selectbox(
        "🔲 Varianta",
        options=["Všechny", "Pouze Slim", "Pouze Standard"],
        index=0,
    )

    # Filtr ceny
    ceny_valid = df_raw["price"].dropna() if not df_raw.empty else pd.Series(dtype=float)
    min_db_cena = int(ceny_valid.min()) if not ceny_valid.empty else 3000
    max_db_cena = int(ceny_valid.max()) if not ceny_valid.empty else 25000

    min_cena, max_cena = st.slider(
        "💰 Cenové rozpětí (Kč)",
        min_value=min_db_cena,
        max_value=max(max_db_cena, min_db_cena + 5000),
        value=(min_db_cena, max(max_db_cena, min_db_cena + 5000)),
        step=500,
    )

    # Textové vyhledávání
    hledany_text = st.text_input("🔍 Vyhledat v názvu", value="").strip().lower()

    # Prahová hodnota Super kauf
    st.divider()
    st.markdown("**🚀 Kalkulačka podhodnocení**")
    profit_threshold = st.number_input(
        "Práh Super kauf (Kč)",
        min_value=0,
        max_value=10000,
        value=1500,
        step=100,
        help="Inzeráty s profitem nad tuto hodnotu budou označeny jako Super kauf",
    )

    st.divider()
    st.markdown(
        """
        **PS5 Arbitrage Platform**
        • 24/7 Multi-Portal Scraper
        • Sales Tracker (12h cyklus)
        • SQLite databáze
        • Kalkulačka podhodnocení
        """
    )

# ---------------------------------------------------------------------------
# Aplikace filtrů na DataFrame
# ---------------------------------------------------------------------------

df_filtered = df_raw.copy() if not df_raw.empty else pd.DataFrame(columns=df_raw.columns if not df_raw.empty else [])

if not df_filtered.empty:
    if vybrany_portal == "Bazoš.cz":
        df_filtered = df_filtered[df_filtered["portal"] == "bazos"]
    elif vybrany_portal == "Vinted.cz":
        df_filtered = df_filtered[df_filtered["portal"] == "vinted"]

    if vybrane_edice:
        df_filtered = df_filtered[df_filtered["edition"].isin(vybrane_edice)]

    if slim_filtr == "Pouze Slim":
        df_filtered = df_filtered[df_filtered["is_slim"] == True]
    elif slim_filtr == "Pouze Standard":
        df_filtered = df_filtered[df_filtered["is_slim"] == False]

    if "price" in df_filtered.columns:
        df_filtered = df_filtered[
            (df_filtered["price"].isna())
            | ((df_filtered["price"] >= min_cena) & (df_filtered["price"] <= max_cena))
        ]

    if hledany_text:
        df_filtered = df_filtered[
            df_filtered["title"].str.lower().str.contains(hledany_text, na=False)
        ]

# ---------------------------------------------------------------------------
# Výpočet mediánových cen dle edice (pro kalkulačku profitu)
# ---------------------------------------------------------------------------

mediany_dle_edice = spocti_median_ceny_dle_edice(df_filtered)

# ---------------------------------------------------------------------------
# Hlavička & KPI Metriky
# ---------------------------------------------------------------------------

st.markdown('<div class="main-title">🎮 PlayStation 5 Arbitrage</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Analytická platforma pro sledování trhu PS5 konzolí, identifikaci cenových anomálií a rychlosti prodeje</div>',
    unsafe_allow_html=True,
)

kpi = spocti_kpi(df_filtered)

kpi_col1, kpi_col2, kpi_col3, kpi_col4, kpi_col5 = st.columns(5)

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
    median_disk = mediany_dle_edice.get("Disk")
    st.metric(
        label="💿 Medián cena — Disk",
        value=f"{int(median_disk):,} Kč".replace(",", " ") if median_disk else "N/A",
        help="Mediánová tržní cena PS5 Disk edice (základ pro výpočet profitu)",
    )

with kpi_col5:
    median_digital = mediany_dle_edice.get("Digital")
    st.metric(
        label="📲 Medián cena — Digital",
        value=f"{int(median_digital):,} Kč".replace(",", " ") if median_digital else "N/A",
        help="Mediánová tržní cena PS5 Digital edice (základ pro výpočet profitu)",
    )

st.write("")

# ---------------------------------------------------------------------------
# Záložky: Aktivní příležitosti, Kalkulačka profitu, Analýza likvidity, Prodaná tržní data
# ---------------------------------------------------------------------------

tab_aktivni, tab_superkauf, tab_likvidita, tab_prodano = st.tabs([
    "🎯 Aktivní příležitosti",
    "🚀 Super kauf — Kalkulačka podhodnocení",
    "📊 Analýza likvidity & Edice",
    "🏷️ Prodáno — Tržní data",
])

# ---------------------------------------------------------------------------
# TAB 1: Aktivní inzeráty
# ---------------------------------------------------------------------------
with tab_aktivni:
    st.subheader("Aktuálně dostupné PS5 inzeráty")

    aktivni_df = df_filtered[df_filtered["status"] == "active"].copy() if not df_filtered.empty else pd.DataFrame()

    if aktivni_df.empty:
        st.info("Žádné aktivní inzeráty neodpovídají zadaným filtrům.")
    else:
        # Přidání profitu
        aktivni_s_profitem = vypocti_profit_aktivnich(aktivni_df, mediany_dle_edice)

        # Možnosti řazení
        razeni_col1, razeni_col2, _ = st.columns([2, 2, 4])
        with razeni_col1:
            razeni_podle = st.selectbox(
                "Řadit podle:",
                options=[
                    "Nejnovější (výchozí)",
                    "Největší profit",
                    "Nejlevnější cena",
                    "Nejdražší cena",
                    "Edice (A-Z)",
                ],
                key="razeni_aktivni",
            )

        if razeni_podle == "Největší profit":
            aktivni_s_profitem = aktivni_s_profitem.sort_values(
                by=["profit_czk", "found_date"],
                ascending=[False, False],
                na_position="last",
            )
        elif razeni_podle == "Nejlevnější cena":
            aktivni_s_profitem = aktivni_s_profitem.sort_values(by=["price", "found_date"], ascending=[True, False])
        elif razeni_podle == "Nejdražší cena":
            aktivni_s_profitem = aktivni_s_profitem.sort_values(by=["price", "found_date"], ascending=[False, False])
        elif razeni_podle == "Edice (A-Z)":
            aktivni_s_profitem = aktivni_s_profitem.sort_values(by=["edition", "found_date"], ascending=[True, False])
        else:
            aktivni_s_profitem = aktivni_s_profitem.sort_values(by=["found_date", "db_id"], ascending=[False, False])

        # Příprava tabulky pro zobrazení
        # Sloupec pro název: LLM clean_name (standardized_title) s fallbackem na raw title
        if "standardized_title" in aktivni_s_profitem.columns:
            aktivni_s_profitem["display_title"] = (
                aktivni_s_profitem["standardized_title"]
                .fillna(aktivni_s_profitem["title"])
                .where(aktivni_s_profitem["standardized_title"].notna() & (aktivni_s_profitem["standardized_title"] != ""),
                       aktivni_s_profitem["title"])
            )
        else:
            aktivni_s_profitem["display_title"] = aktivni_s_profitem["title"]

        zobrazeni_sloupce = ["portal", "edition", "is_slim", "display_title", "price", "profit_czk", "found_date", "url"]
        dostupne = [c for c in zobrazeni_sloupce if c in aktivni_s_profitem.columns]
        zobrazeni_df = aktivni_s_profitem[dostupne].copy()

        # Formátování portálu
        zobrazeni_df["portal"] = zobrazeni_df["portal"].map(
            {"bazos": "Baz oš.cz", "vinted": "Vinted.cz"}
        ).fillna(zobrazeni_df["portal"])

        # Formátování Slim
        if "is_slim" in zobrazeni_df.columns:
            zobrazeni_df["is_slim"] = zobrazeni_df["is_slim"].map({True: "✅ Slim", False: "Standard", 1: "✅ Slim", 0: "Standard"})

        st.dataframe(
            zobrazeni_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "portal": st.column_config.TextColumn("Portál", width="small"),
                "edition": st.column_config.TextColumn("Edice", width="small"),
                "is_slim": st.column_config.TextColumn("Varianta", width="small"),
                "display_title": st.column_config.TextColumn("🧩 Název konzole", width="large"),
                "price": st.column_config.NumberColumn("Cena", format="%d Kč", width="small"),
                "profit_czk": st.column_config.NumberColumn("Profit (Kč)", format="%d Kč", width="small"),
                "found_date": st.column_config.DatetimeColumn("Nalezeno", format="D.M.YYYY HH:mm", width="medium"),
                "url": st.column_config.LinkColumn("Odkaz", display_text="Přejít ↗", width="medium"),
            },
        )
        st.caption(f"Zobrazeno {len(zobrazeni_df)} aktivních inzerátů PS5.")

# ---------------------------------------------------------------------------
# TAB 2: Super kauf — Kalkulačka podhodnocení
# ---------------------------------------------------------------------------
with tab_superkauf:
    st.subheader("🚀 Super kauf — Podhodnocené PS5 inzeráty")
    st.markdown(
        f"""
        Tato tabulka zobrazuje aktivní inzeráty, kde je **Profit > {profit_threshold:,} Kč**.
        Profit = Mediánová cena dané edice − Cena inzerátu.

        | Edice | Mediánová cena |
        |-------|----------------|
        | 💿 Disk | **{f"{int(mediany_dle_edice['Disk']):,} Kč" if mediany_dle_edice['Disk'] else 'N/A'}** |
        | 📲 Digital | **{f"{int(mediany_dle_edice['Digital']):,} Kč" if mediany_dle_edice['Digital'] else 'N/A'}** |
        """.replace(",", " "),
        unsafe_allow_html=False,
    )

    aktivni_df2 = df_filtered[df_filtered["status"] == "active"].copy() if not df_filtered.empty else pd.DataFrame()

    if aktivni_df2.empty:
        st.info("Žádné aktivní inzeráty v databázi.")
    else:
        aktivni_s_profitem2 = vypocti_profit_aktivnich(aktivni_df2, mediany_dle_edice)

        # Filtr: pouze profit > threshold
        super_kauf_df = aktivni_s_profitem2[
            aktivni_s_profitem2["profit_czk"].notna()
            & (aktivni_s_profitem2["profit_czk"] > profit_threshold)
        ].copy()

        if super_kauf_df.empty:
            st.warning(
                f"Žádné inzeráty s profitem nad **{profit_threshold:,} Kč** nebyly nalezeny. "
                "Zkuste snížit práh nebo přidat více dat do databáze.".replace(",", " ")
            )
        else:
            # Řazení: největší profit nahoře
            super_kauf_df = super_kauf_df.sort_values(
                by="profit_czk", ascending=False, na_position="last"
            )

            st.success(f"🎉 Nalezeno **{len(super_kauf_df)}** podhodnocených inzerátů!")

            # Sloupec pro název: LLM clean_name (standardized_title) s fallbackem na raw title
            if "standardized_title" in super_kauf_df.columns:
                super_kauf_df["display_title"] = (
                    super_kauf_df["standardized_title"]
                    .where(super_kauf_df["standardized_title"].notna() & (super_kauf_df["standardized_title"] != ""),
                           super_kauf_df["title"])
                )
            else:
                super_kauf_df["display_title"] = super_kauf_df["title"]

            # Zobrazení tabulky se zeleným zvýrazněním přes st.dataframe
            dostupne_sloupce = [c for c in ["portal", "edition", "is_slim", "display_title", "price", "profit_czk", "found_date", "url"] if c in super_kauf_df.columns]
            zobrazeni_super = super_kauf_df[dostupne_sloupce].copy()

            # Formátování
            zobrazeni_super["portal"] = zobrazeni_super["portal"].map(
                {"bazos": "Baz oš.cz", "vinted": "Vinted.cz"}
            ).fillna(zobrazeni_super["portal"])

            if "is_slim" in zobrazeni_super.columns:
                zobrazeni_super["is_slim"] = zobrazeni_super["is_slim"].map({
                    True: "✅ Slim", False: "Standard", 1: "✅ Slim", 0: "Standard"
                })

            st.dataframe(
                zobrazeni_super,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "portal": st.column_config.TextColumn("Portál", width="small"),
                    "edition": st.column_config.TextColumn("Edice", width="small"),
                    "is_slim": st.column_config.TextColumn("Varianta", width="small"),
                    "display_title": st.column_config.TextColumn("🧩 Název konzole", width="large"),
                    "price": st.column_config.NumberColumn("Cena", format="%d Kč", width="small"),
                    "profit_czk": st.column_config.NumberColumn(
                        "💰 Profit (Kč)",
                        format="%d Kč",
                        width="small",
                        help="Mediánová cena edice − Cena inzerátu",
                    ),
                    "found_date": st.column_config.DatetimeColumn("Nalezeno", format="D.M.YYYY HH:mm", width="medium"),
                    "url": st.column_config.LinkColumn("Odkaz", display_text="👉 Koupit ↗", width="medium"),
                },
            )

            # Statistiky super kaufů
            st.divider()
            sc1, sc2, sc3 = st.columns(3)
            with sc1:
                st.metric("Průměrný profit", f"{int(super_kauf_df['profit_czk'].mean()):,} Kč".replace(",", " "))
            with sc2:
                st.metric("Maximální profit", f"{int(super_kauf_df['profit_czk'].max()):,} Kč".replace(",", " "))
            with sc3:
                st.metric("Počet super kaufů", f"{len(super_kauf_df)} ks")

# ---------------------------------------------------------------------------
# TAB 3: Analýza likvidity a cen dle edice
# ---------------------------------------------------------------------------
with tab_likvidita:
    st.subheader("Likvidita a cenové hladiny dle edice PS5")

    agregovano = spocti_agregace_edice(df_filtered)

    if agregovano.empty:
        st.info("Zatím nejsou k dispozici žádná data o prodaných inzerátech pro zvolené filtry.")
    else:
        graf_col, tab_col = st.columns([5, 4])

        with graf_col:
            st.markdown("##### 💿 Průměrná prodejní cena dle edice")
            top3_df = top_edice_ceny(agregovano, n=3)

            # Barvy dle edice
            barvy = {"Disk": "#0070cc", "Digital": "#00c8ff", "Unknown": "#6c757d"}
            top3_df["barva"] = top3_df["edition"].map(barvy).fillna("#444")

            fig = px.bar(
                top3_df,
                x="edition",
                y="prumerna_cena",
                text="prumerna_cena",
                color="edition",
                color_discrete_map=barvy,
                labels={
                    "edition": "Edice",
                    "prumerna_cena": "Průměrná prodejní cena (Kč)",
                    "pocet_prodano": "Prodáno kusů",
                },
                hover_data=["pocet_prodano", "median_cena", "prumerna_doba_hodin"],
            )

            fig.update_traces(
                texttemplate="%{text:,} Kč".replace(",", " "),
                textposition="outside",
                cliponaxis=False,
            )
            fig.update_layout(
                xaxis_title="",
                yaxis_title="Cena (Kč)",
                showlegend=False,
                margin=dict(l=20, r=20, t=30, b=30),
                height=420,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e8eaf6"),
                xaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
                yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
            )

            st.plotly_chart(fig, use_container_width=True)

        with tab_col:
            st.markdown("##### 📋 Přehled likvidity dle edice")
            st.dataframe(
                agregovano,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "edition": st.column_config.TextColumn("Edice"),
                    "pocet_prodano": st.column_config.NumberColumn("Prodáno (ks)"),
                    "prumerna_cena": st.column_config.NumberColumn("Prům. cena", format="%d Kč"),
                    "median_cena": st.column_config.NumberColumn("Medián cena", format="%d Kč"),
                    "prumerna_doba_hodin": st.column_config.NumberColumn("Doba prodeje", format="%.1f h"),
                },
            )
            st.caption("Statistiky jsou počítány výhradně z inzerátů se statusem 'sold'.")

        # Graf: Slim vs Standard
        st.divider()
        st.markdown("##### 🔲 Slim vs Standard — zastoupení v databázi")
        if not df_filtered.empty and "is_slim" in df_filtered.columns:
            slim_counts = df_filtered["is_slim"].value_counts().reset_index()
            slim_counts.columns = ["varianta", "pocet"]
            slim_counts["varianta"] = slim_counts["varianta"].map({
                True: "Slim", False: "Standard", 1: "Slim", 0: "Standard"
            })

            fig_pie = px.pie(
                slim_counts,
                values="pocet",
                names="varianta",
                color="varianta",
                color_discrete_map={"Slim": "#00c8ff", "Standard": "#0070cc"},
                hole=0.55,
            )
            fig_pie.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e8eaf6"),
                height=300,
                margin=dict(l=20, r=20, t=20, b=20),
                showlegend=True,
            )
            fig_pie.update_traces(textinfo="percent+label")
            st.plotly_chart(fig_pie, use_container_width=True)

# ---------------------------------------------------------------------------
# TAB 4: Prodané inzeráty
# ---------------------------------------------------------------------------
with tab_prodano:
    st.subheader("Prodáno — Tržní data PS5")
    st.markdown(
        "Přehled všech PS5 konzolí se statusem **'sold'** načtených přímo z databáze `/data/market.db`. "
        "Data lze stáhnout ve formátu CSV pro analýzu v aplikaci Microsoft Excel."
    )

    try:
        conn = sqlite3.connect(str(DB_PATH))
        df_sold = pd.read_sql_query(
            "SELECT * FROM listings WHERE status = 'sold' ORDER BY db_id DESC;",
            conn,
        )
        conn.close()
    except Exception as exc:
        df_sold = nacti_prodana_data_df(DB_PATH)

    st.dataframe(
        df_sold,
        use_container_width=True,
        hide_index=True,
    )

    if not df_sold.empty:
        st.caption(f"Celkem načteno {len(df_sold)} prodaných PS5 konzolí.")
    else:
        st.info("V databázi zatím nejsou žádné inzeráty se statusem 'sold'.")

    csv_data = exportuj_do_csv_excel(df_sold, sep=";", encoding="utf-8-sig")

    st.download_button(
        label="📥 Stáhnout prodané PS5 (CSV pro Excel)",
        data=csv_data,
        file_name="prodane_ps5.csv",
        mime="text/csv",
        help="Exportuje data prodaných PS5 konzolí do CSV souboru (kódování UTF-8 s BOM, oddělovač ';').",
    )
