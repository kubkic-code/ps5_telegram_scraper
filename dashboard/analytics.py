"""
analytics.py — Analytické a výpočetní jádro dashboardu Garmin hodinek
Python Agent | Extrakce modelů, výpočet KPI, agregace likvidity a cen
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd

# Přidáme cestu k modulu scraper, pokud ještě není v sys.path
_scraper_dir = str(Path(__file__).resolve().parent.parent / "scraper")
if _scraper_dir not in sys.path:
    sys.path.insert(0, _scraper_dir)

try:
    from db import DEFAULT_DB_PATH, ziskej_pripojeni
except ImportError:
    DEFAULT_DB_PATH = Path(os.getenv("DB_PATH", "/data/market.db"))

    def ziskej_pripojeni(db_path=DEFAULT_DB_PATH):
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pravidla pro extrakci modelů (od nejspecifičtějších k obecnějším)
# ---------------------------------------------------------------------------

MODEL_PATTERNS: list[tuple[re.Pattern, str]] = [
    # --- Fenix série ---
    (re.compile(r"\bfenix\s*8\b", re.I), "Fenix 8"),
    (re.compile(r"\bfenix\s*7\s*pro\b", re.I), "Fenix 7 Pro"),
    (re.compile(r"\bfenix\s*7[xs]?\b", re.I), "Fenix 7"),
    (re.compile(r"\bfenix\s*6\s*pro\b", re.I), "Fenix 6 Pro"),
    (re.compile(r"\bfenix\s*6[xs]?\b", re.I), "Fenix 6"),
    (re.compile(r"\bfenix\s*5\s*plus\b", re.I), "Fenix 5 Plus"),
    (re.compile(r"\bfenix\s*5[xs]?\b", re.I), "Fenix 5"),
    (re.compile(r"\bfenix\s*3\b", re.I), "Fenix 3"),
    (re.compile(r"\bfenix\b", re.I), "Fenix"),
    # --- Epix série ---
    (re.compile(r"\bepix\s*(?:pro|gen\s*2|2)\b", re.I), "Epix Gen 2"),
    (re.compile(r"\bepix\b", re.I), "Epix"),
    # --- Forerunner série ---
    (re.compile(r"\bforerunner\s*965\b", re.I), "Forerunner 965"),
    (re.compile(r"\bforerunner\s*955\b", re.I), "Forerunner 955"),
    (re.compile(r"\bforerunner\s*945\b", re.I), "Forerunner 945"),
    (re.compile(r"\bforerunner\s*935\b", re.I), "Forerunner 935"),
    (re.compile(r"\bforerunner\s*265\b", re.I), "Forerunner 265"),
    (re.compile(r"\bforerunner\s*255\b", re.I), "Forerunner 255"),
    (re.compile(r"\bforerunner\s*245\b", re.I), "Forerunner 245"),
    (re.compile(r"\bforerunner\s*165\b", re.I), "Forerunner 165"),
    (re.compile(r"\bforerunner\s*55\b", re.I), "Forerunner 55"),
    (re.compile(r"\bforerunner\s*45\b", re.I), "Forerunner 45"),
    (re.compile(r"\bforerunner\b", re.I), "Forerunner"),
    # --- Venu série ---
    (re.compile(r"\bvenu\s*3[s]?\b", re.I), "Venu 3"),
    (re.compile(r"\bvenu\s*2\s*plus\b", re.I), "Venu 2 Plus"),
    (re.compile(r"\bvenu\s*2[s]?\b", re.I), "Venu 2"),
    (re.compile(r"\bvenu\s*sq\s*2\b", re.I), "Venu Sq 2"),
    (re.compile(r"\bvenu\s*sq\b", re.I), "Venu Sq"),
    (re.compile(r"\bvenu\b", re.I), "Venu"),
    # --- Instinct série ---
    (re.compile(r"\binstinct\s*2[xs]?\b", re.I), "Instinct 2"),
    (re.compile(r"\binstinct\s*crossover\b", re.I), "Instinct Crossover"),
    (re.compile(r"\binstinct\b", re.I), "Instinct"),
    # --- Tactix série ---
    (re.compile(r"\btactix\s*7\b", re.I), "Tactix 7"),
    (re.compile(r"\btactix\s*delta\b", re.I), "Tactix Delta"),
    (re.compile(r"\btactix\b", re.I), "Tactix"),
    # --- Enduro série ---
    (re.compile(r"\benduro\s*2\b", re.I), "Enduro 2"),
    (re.compile(r"\benduro\b", re.I), "Enduro"),
    # --- Vivoactive série ---
    (re.compile(r"\bvivoactive\s*5\b", re.I), "Vivoactive 5"),
    (re.compile(r"\bvivoactive\s*4[s]?\b", re.I), "Vivoactive 4"),
    (re.compile(r"\bvivoactive\s*3\b", re.I), "Vivoactive 3"),
    (re.compile(r"\bvivoactive\b", re.I), "Vivoactive"),
    # --- Další Garmin řady ---
    (re.compile(r"\bvivomove\b", re.I), "Vivomove"),
    (re.compile(r"\bmarq\b", re.I), "Marq"),
    (re.compile(r"\bquatix\b", re.I), "Quatix"),
    (re.compile(r"\bapproach\b", re.I), "Approach"),
    (re.compile(r"\blily\b", re.I), "Lily"),
]


def extrahuj_model(title: Optional[str]) -> str:
    """Extrahují název modelu Garmin hodinek z textu nadpisu inzerátu.

    Příklady:
        'Garmin Fenix 7 Sapphire Solar' -> 'Fenix 7'
        'Garmin Forerunner 245 Music'   -> 'Forerunner 245'
        'Hodinky Garmin Venu 2 Plus'     -> 'Venu 2 Plus'
        'Chytré hodinky'                -> 'Ostatní'
    """
    if not title or not isinstance(title, str):
        return "Ostatní"

    for pattern, model_name in MODEL_PATTERNS:
        if pattern.search(title):
            return model_name

    return "Ostatní"


# ---------------------------------------------------------------------------
# Načítání a transformace dat z DB
# ---------------------------------------------------------------------------

SLOUPCE_DF = [
    "db_id",
    "item_id",
    "portal",
    "title",
    "parsed_model",
    "price",
    "url",
    "found_date",
    "sold_date",
    "status",
]


def nacti_data_df(
    db_conn: Optional[Union[sqlite3.Connection, str, Path]] = None,
) -> pd.DataFrame:
    """Načte záznamy z tabulky listings do pandas DataFrame a obohatí je o analytické sloupce.

    Přidané sloupce:
        - 'model': detekovaný Garmin model
        - 'doba_prodeje_hodin': rozdíl mezi sold_date a found_date v hodinách
    """
    vlastni_pripojeni = False
    if db_conn is None:
        conn = ziskej_pripojeni(DEFAULT_DB_PATH)
        vlastni_pripojeni = True
    elif isinstance(db_conn, (str, Path)):
        conn = ziskej_pripojeni(db_conn)
        vlastni_pripojeni = True
    else:
        conn = db_conn

    try:
        query = "SELECT * FROM listings ORDER BY db_id DESC;"
        df = pd.read_sql_query(query, conn)
    except Exception as exc:
        logger.warning("Nelze načíst data z DB: %s", exc)
        df = pd.DataFrame(columns=SLOUPCE_DF)
    finally:
        if vlastni_pripojeni:
            conn.close()

    if df.empty:
        # Zajištění existence analytických sloupců i pro prázdný DF
        df["model"] = pd.Series(dtype="str")
        df["doba_prodeje_hodin"] = pd.Series(dtype="float")
        return df

    # Konverze časových razítek
    df["found_date"] = pd.to_datetime(df["found_date"], errors="coerce")
    df["sold_date"] = pd.to_datetime(df["sold_date"], errors="coerce")

    # Doba do prodeje v hodinách (pouze pro prodané s validními daty)
    rozdil_sekund = (df["sold_date"] - df["found_date"]).dt.total_seconds()
    df["doba_prodeje_hodin"] = rozdil_sekund / 3600.0

    # Extrakce modelu
    df["model"] = df["title"].apply(extrahuj_model)

    return df


# ---------------------------------------------------------------------------
# Výpočet KPI
# ---------------------------------------------------------------------------

def spocti_kpi(df: pd.DataFrame) -> dict[str, Any]:
    """Spočte klíčové ukazatele (KPI) z načteného DataFrame:

    - pocet_aktivnich: počet inzerátů se statusem 'active'
    - pocet_prodanych: počet inzerátů se statusem 'sold'
    - median_doby_hodin: medián doby do prodeje v hodinách
    """
    if df.empty or "status" not in df.columns:
        return {
            "pocet_aktivnich": 0,
            "pocet_prodanych": 0,
            "median_doby_hodin": 0.0,
        }

    pocet_aktivnich = int((df["status"] == "active").sum())
    pocet_prodanych = int((df["status"] == "sold").sum())

    # Medián doby prodeje pouze z prodaných záznamů s kladnou dobou
    sold_df = df[
        (df["status"] == "sold")
        & df["doba_prodeje_hodin"].notna()
        & (df["doba_prodeje_hodin"] >= 0)
    ]

    if not sold_df.empty:
        median_doby = round(float(sold_df["doba_prodeje_hodin"].median()), 1)
    else:
        median_doby = 0.0

    return {
        "pocet_aktivnich": pocet_aktivnich,
        "pocet_prodanych": pocet_prodanych,
        "median_doby_hodin": median_doby,
    }


# ---------------------------------------------------------------------------
# Analýza likvidity a cen dle modelů
# ---------------------------------------------------------------------------

def spocti_agregace_modelu(df: pd.DataFrame) -> pd.DataFrame:
    """Vytvoří agregovanou tabulku (GroupBy model) pro prodané inzeráty ('sold'):

    Sloupce:
        - model: název modelu
        - pocet_prodano: počet prodaných kusů
        - prumerna_cena: průměrná prodejní cena (Kč)
        - prumerna_doba_hodin: průměrná doba do prodeje v hodinách
    """
    ocekavane_sloupce = ["model", "pocet_prodano", "prumerna_cena", "prumerna_doba_hodin"]

    if df.empty or "status" not in df.columns:
        return pd.DataFrame(columns=ocekavane_sloupce)

    sold_df = df[df["status"] == "sold"].copy()
    if sold_df.empty:
        return pd.DataFrame(columns=ocekavane_sloupce)

    # Agregace přes model
    agregovano = (
        sold_df.groupby("model")
        .agg(
            pocet_prodano=("model", "count"),
            prumerna_cena=("price", "mean"),
            prumerna_doba_hodin=("doba_prodeje_hodin", "mean"),
        )
        .reset_index()
    )

    # Zaokrouhlení
    agregovano["prumerna_cena"] = agregovano["prumerna_cena"].fillna(0).round(0).astype(int)
    agregovano["prumerna_doba_hodin"] = agregovano["prumerna_doba_hodin"].fillna(0).round(1)

    # Řazení: nejvíce prodávané nahoře
    agregovano = agregovano.sort_values(
        by=["pocet_prodano", "prumerna_cena"], ascending=[False, False]
    ).reset_index(drop=True)

    return agregovano


def top_modely_ceny(df_agregovany: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """Vrátí TOP N nejprodávanějších modelů pro vykreslení v grafu."""
    if df_agregovany.empty:
        return pd.DataFrame(columns=df_agregovany.columns)
    return df_agregovany.head(n).copy()
