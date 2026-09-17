"""
analytics.py — Analytické a výpočetní jádro dashboardu PlayStation 5
Python Agent | Edice (Disk/Digital/Unknown), mediánové ceny, kalkulačka profitu
"""

from __future__ import annotations

import logging
import os
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
# Prahová hodnota pro "Super kauf" (podhodnocený inzerát)
# ---------------------------------------------------------------------------

PROFIT_SUPER_KAUF_THRESHOLD = 1_500  # Kč — pokud je profit > 1500, je to super kauf

# ---------------------------------------------------------------------------
# Sloupce DataFrame
# ---------------------------------------------------------------------------

SLOUPCE_DF = [
    "db_id",
    "item_id",
    "portal",
    "title",
    "edition",
    "is_slim",
    "price",
    "url",
    "found_date",
    "sold_date",
    "status",
]


# ---------------------------------------------------------------------------
# Načítání a transformace dat z DB
# ---------------------------------------------------------------------------

def nacti_data_df(
    db_conn: Optional[Union[sqlite3.Connection, str, Path]] = None,
) -> pd.DataFrame:
    """Načte záznamy z tabulky listings do pandas DataFrame a obohatí je o analytické sloupce.

    Přidané sloupce:
        - 'doba_prodeje_hodin': rozdíl mezi sold_date a found_date v hodinách

    Sloupce z DB:
        - 'edition': Disk / Digital / Unknown
        - 'is_slim': True/False
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
        df["doba_prodeje_hodin"] = pd.Series(dtype="float")
        return df

    # Konverze časových razítek
    df["found_date"] = pd.to_datetime(df["found_date"], errors="coerce")
    df["sold_date"] = pd.to_datetime(df["sold_date"], errors="coerce")

    # Doba do prodeje v hodinách (pouze pro prodané s validními daty)
    rozdil_sekund = (df["sold_date"] - df["found_date"]).dt.total_seconds()
    df["doba_prodeje_hodin"] = rozdil_sekund / 3600.0

    # Normalizace edition — pokud chybí sloupec, přidáme výchozí hodnotu
    if "edition" not in df.columns:
        df["edition"] = "Unknown"
    else:
        df["edition"] = df["edition"].fillna("Unknown")

    # Normalizace is_slim
    if "is_slim" not in df.columns:
        df["is_slim"] = False
    else:
        df["is_slim"] = df["is_slim"].astype(bool)

    return df


def nacti_prodana_data_df(
    db_conn: Optional[Union[sqlite3.Connection, str, Path]] = None,
) -> pd.DataFrame:
    """Načte z databáze pouze inzeráty se statusem 'sold' přímo přes pd.read_sql_query.

    Vrací pandas DataFrame s prodanými inzeráty PS5.
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
        query = "SELECT * FROM listings WHERE status = 'sold' ORDER BY db_id DESC;"
        df = pd.read_sql_query(query, conn)
    except Exception as exc:
        logger.warning("Nelze načíst prodaná data z DB: %s", exc)
        df = pd.DataFrame(columns=SLOUPCE_DF)
    finally:
        if vlastni_pripojeni:
            conn.close()

    return df


def exportuj_do_csv_excel(
    df: pd.DataFrame,
    sep: str = ";",
    encoding: str = "utf-8-sig",
) -> bytes:
    """Převede DataFrame na CSV bajty s kódováním UTF-8-SIG (včetně BOM) pro bezproblémové otevření v MS Excel.

    Parametry:
        df: Pandas DataFrame k exportu
        sep: oddělovač sloupců (výchozí ';' pro evropský/český Excel, alternativně ',')
        encoding: kódování znaků (výchozí 'utf-8-sig' s BOM pro zachování diakritiky)
    """
    csv_text = df.to_csv(index=False, sep=sep)
    return csv_text.encode(encoding)


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
# Mediánové ceny dle edice — základ kalkulačky podhodnocení
# ---------------------------------------------------------------------------

def spocti_median_ceny_dle_edice(df: pd.DataFrame) -> dict[str, Optional[float]]:
    """Spočítá mediánovou cenu zvlášť pro Disk a Digital edici z historických dat.

    Bere v úvahu VŠECHNA data (sold i active), aby byl medián co nejpřesnější.
    Pokud je k dispozici dostatek prodaných dat, preferuje prodaná.

    Args:
        df: DataFrame s daty z databáze (musí obsahovat sloupce 'edition' a 'price').

    Returns:
        Slovník s mediánovými cenami:
            {
                'Disk': float nebo None,
                'Digital': float nebo None,
                'Unknown': float nebo None,
            }
    """
    vysledek: dict[str, Optional[float]] = {
        "Disk": None,
        "Digital": None,
        "Unknown": None,
    }

    if df.empty or "edition" not in df.columns or "price" not in df.columns:
        return vysledek

    for edice in ("Disk", "Digital", "Unknown"):
        # Primárně z prodaných inzerátů
        sold_edice = df[
            (df["status"] == "sold")
            & (df["edition"] == edice)
            & df["price"].notna()
            & (df["price"] > 0)
        ]["price"]

        if len(sold_edice) >= 3:
            # Dostatek prodaných dat → použijeme prodaná
            vysledek[edice] = round(float(sold_edice.median()), 0)
        else:
            # Málo prodaných dat → použijeme všechna (prodaná + aktivní)
            vsechna_edice = df[
                (df["edition"] == edice)
                & df["price"].notna()
                & (df["price"] > 0)
            ]["price"]

            if not vsechna_edice.empty:
                vysledek[edice] = round(float(vsechna_edice.median()), 0)

    return vysledek


def vypocti_profit_aktivnich(
    aktivni_df: pd.DataFrame,
    mediany: dict[str, Optional[float]],
) -> pd.DataFrame:
    """Přidá sloupec 'profit_czk' ke DataFrame aktivních inzerátů.

    Výpočet: Mediánová cena dané edice - Cena inzerátu.

    Speciální chování pro 'Unknown' edici:
        - Místo vlastního mediánu Unknown se použije mediánová cena 'Digital' edice.
        - Digital bývá vždy levnější → vytváří konzervativní (bezpečnostní) polštář.
        - Pokud ani Digital medián není k dispozici, profit pro Unknown = None.

    Args:
        aktivni_df: DataFrame aktivních inzerátů.
        mediany: Slovník mediánových cen dle edice (výstup z spocti_median_ceny_dle_edice).

    Returns:
        Kopie DataFrame s novým sloupcem 'profit_czk'.
    """
    df = aktivni_df.copy()

    if df.empty or "edition" not in df.columns or "price" not in df.columns:
        df["profit_czk"] = None
        return df

    def _vypocti_profit(row):
        edice = row.get("edition", "Unknown")
        cena = row.get("price")

        if cena is None or pd.isna(cena):
            return None

        if edice == "Unknown":
            # Konzervativní polštář: použijeme Digital medián (ten je vždy nižší)
            median = mediany.get("Digital")
        else:
            median = mediany.get(edice)

        if median is None:
            return None

        return int(median - cena)

    df["profit_czk"] = df.apply(_vypocti_profit, axis=1)
    return df


# ---------------------------------------------------------------------------
# Analýza likvidity a cen dle edice
# ---------------------------------------------------------------------------

def spocti_agregace_edice(df: pd.DataFrame) -> pd.DataFrame:
    """Vytvoří agregovanou tabulku (GroupBy edition) pro prodané inzeráty ('sold').

    Sloupce:
        - edition: název edice (Disk/Digital/Unknown)
        - pocet_prodano: počet prodaných kusů
        - prumerna_cena: průměrná prodejní cena (Kč)
        - median_cena: mediánová prodejní cena (Kč)
        - prumerna_doba_hodin: průměrná doba do prodeje v hodinách
    """
    ocekavane_sloupce = [
        "edition", "pocet_prodano", "prumerna_cena", "median_cena", "prumerna_doba_hodin"
    ]

    if df.empty or "status" not in df.columns:
        return pd.DataFrame(columns=ocekavane_sloupce)

    sold_df = df[df["status"] == "sold"].copy()
    if sold_df.empty:
        return pd.DataFrame(columns=ocekavane_sloupce)

    # Agregace přes edition
    agregovano = (
        sold_df.groupby("edition")
        .agg(
            pocet_prodano=("edition", "count"),
            prumerna_cena=("price", "mean"),
            median_cena=("price", "median"),
            prumerna_doba_hodin=("doba_prodeje_hodin", "mean"),
        )
        .reset_index()
    )

    # Zaokrouhlení
    agregovano["prumerna_cena"] = agregovano["prumerna_cena"].fillna(0).round(0).astype(int)
    agregovano["median_cena"] = agregovano["median_cena"].fillna(0).round(0).astype(int)
    agregovano["prumerna_doba_hodin"] = agregovano["prumerna_doba_hodin"].fillna(0).round(1)

    # Řazení: nejvíce prodávané nahoře
    agregovano = agregovano.sort_values(
        by=["pocet_prodano", "prumerna_cena"], ascending=[False, False]
    ).reset_index(drop=True)

    return agregovano


# Alias pro zpětnou kompatibilitu s app.py (starý název funkce)
def spocti_agregace_modelu(df: pd.DataFrame) -> pd.DataFrame:
    """Alias pro spocti_agregace_edice() — agregace dle edice PS5."""
    return spocti_agregace_edice(df)


def top_edice_ceny(df_agregovany: pd.DataFrame, n: int = 3) -> pd.DataFrame:
    """Vrátí TOP N nejvíce prodávaných edicí pro vykreslení v grafu."""
    if df_agregovany.empty:
        return pd.DataFrame(columns=df_agregovany.columns)
    return df_agregovany.head(n).copy()


# Alias pro zpětnou kompatibilitu s app.py
def top_modely_ceny(df_agregovany: pd.DataFrame, n: int = 3) -> pd.DataFrame:
    """Alias pro top_edice_ceny() — top edice PS5."""
    return top_edice_ceny(df_agregovany, n)
