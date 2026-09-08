"""
db.py — Databázová vrstva analytické platformy pro arbitráž hodinek
Python Agent | SQLite3 | Ukládání a správa inzerátů (/data/market.db)
"""

from __future__ import annotations

import datetime
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional, Union

from scraper import Inzerat

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfigurace
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = Path(os.getenv("DB_PATH", "/data/market.db"))

CREATE_TABLE_LISTINGS_SQL = """
CREATE TABLE IF NOT EXISTS listings (
    db_id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT UNIQUE NOT NULL,
    portal TEXT NOT NULL,
    title TEXT NOT NULL,
    parsed_model TEXT,
    price INTEGER,
    url TEXT,
    found_date DATETIME NOT NULL,
    sold_date DATETIME,
    status TEXT NOT NULL CHECK (status IN ('active', 'sold', 'deleted'))
);
"""

CREATE_INDICES_SQL = """
CREATE INDEX IF NOT EXISTS idx_listings_item_id ON listings(item_id);
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);
CREATE INDEX IF NOT EXISTS idx_listings_portal ON listings(portal);
"""


# ---------------------------------------------------------------------------
# Pomocné funkce
# ---------------------------------------------------------------------------

def urci_portal(inzerat: Inzerat) -> str:
    """Určí portál podle ID a URL inzerátu.

    Vinted inzeráty mají prefix 'vt_' nebo doménu vinted.cz.
    Ostatní jsou považovány za Bazoš.
    """
    if inzerat.id.startswith("vt_") or "vinted" in inzerat.url.lower():
        return "vinted"
    return "bazos"


def parsuj_cenu_na_int(cena: Union[str, int, float, None]) -> Optional[int]:
    """Převede textovou nebo číselnou cenu na celé číslo (int) pro DB sloupec price.

    Příklady:
        '8 500 Kč'   -> 8500
        '12.000 Kč'  -> 12000
        '200 €'      -> 200
        '1.500,50 €' -> 1501
        'Neuvedena'  -> None
        'V textu'    -> None
    """
    if cena is None:
        return None

    if isinstance(cena, (int, float)):
        return int(cena + 0.5) if cena >= 0 else int(cena - 0.5)

    cena_str = str(cena).strip()
    if not cena_str:
        return None

    # Ošetření Vinted formátu: '5108.24 Kč, 5381.65 Kč' -> vezmeme jen to první
    if "," in cena_str and ("Kč" in cena_str or "€" in cena_str):
        casti = cena_str.split(",")
        if len(casti) > 1 and any(char.isdigit() for char in casti[1]) and ("Kč" in casti[0] or "€" in casti[0]):
            cena_str = casti[0].strip()

    cena_lower = cena_str.lower()
    textove_vzory = ("neuvedena", "v textu", "dohodou", "dohoda", "zdarma", "vb")
    if any(vzor in cena_lower for vzor in textove_vzory):
        return None

    je_eur = "€" in cena_str or "eur" in cena_lower
    je_czk = "kč" in cena_lower or "czk" in cena_lower

    cislo_match = re.search(r"([\d][\d\s\.\,]*)", cena_str)
    if not cislo_match:
        return None

    cislo_raw = cislo_match.group(1).strip()

    if je_czk or not je_eur:
        # CZK / standardní formát: mezery a tečky jako oddělovače tisíců, podpora Vinted desetinné tečky
        cislo_norm = re.sub(r"\s", "", cislo_raw)
        cislo_norm = re.sub(r"\.(\d{3})(?=[\.,]|$)", r"\1", cislo_norm)
        cislo_norm = cislo_norm.replace(",", ".")
        if cislo_norm.count(".") > 1:
            parts = cislo_norm.split(".")
            cislo_norm = "".join(parts[:-1]) + "." + parts[-1]
    else:
        # EUR formát: '1.500,50' nebo '200'
        cislo_norm = re.sub(r"\s", "", cislo_raw)
        cislo_norm = re.sub(r"\.(\d{3})(?=[\.,]|$)", r"\1", cislo_norm)
        cislo_norm = cislo_norm.replace(",", ".")
        if cislo_norm.count(".") > 1:
            parts = cislo_norm.split(".")
            cislo_norm = "".join(parts[:-1]) + "." + parts[-1]

    try:
        val = float(cislo_norm)
        # Běžné zaokrouhlení (půlky nahoru)
        return int(val + 0.5) if val >= 0 else int(val - 0.5)
    except ValueError:
        logger.debug("Nepodařilo se převést cenu '%s' na int.", cena_str)
        return None


# ---------------------------------------------------------------------------
# Správa připojení a inicializace
# ---------------------------------------------------------------------------

def ziskej_pripojeni(db_path: Union[str, Path] = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Otevře spojení do SQLite databáze.

    Pokud databáze není in-memory (':memory:'), zajistí existenci cílového adresáře.
    """
    cesta_str = str(db_path)
    if cesta_str != ":memory:":
        adresar = Path(cesta_str).parent
        try:
            adresar.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Nelze vytvořit adresář pro databázi %s: %s", adresar, exc)

    conn = sqlite3.connect(cesta_str)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_conn: Optional[Union[sqlite3.Connection, str, Path]] = None) -> None:
    """Inicializuje schéma databáze — vytvoří tabulku listings a indexy.

    Args:
        db_conn: Otevřené spojení sqlite3.Connection, cesta k souboru nebo None (použije DEFAULT_DB_PATH).
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
        with conn:
            conn.executescript(CREATE_TABLE_LISTINGS_SQL + CREATE_INDICES_SQL)
        logger.info("Databáze úspěšně inicializována (tabulka 'listings').")
    finally:
        if vlastni_pripojeni:
            conn.close()


# ---------------------------------------------------------------------------
# Operace s inzeráty
# ---------------------------------------------------------------------------

def uloz_inzerat(
    inzerat: Inzerat,
    db_conn: Optional[Union[sqlite3.Connection, str, Path]] = None,
    status: str = "active",
    found_date: Optional[datetime.datetime] = None,
    sold_date: Optional[datetime.datetime] = None,
    parsed_model: Optional[str] = None,
) -> bool:
    """Uloží nový inzerát do databáze. Pokud inzerát s daným item_id již existuje, ignoruje ho.

    Args:
        inzerat:       Datový objekt Inzerat.
        db_conn:       Spojení sqlite3 nebo cesta. Při None použije DEFAULT_DB_PATH.
        status:        Status inzerátu ('active', 'sold', 'deleted'). Výchozí 'active'.
        found_date:    Datum nalezení (datetime). Pokud None, použije se aktuální UTC/lokální čas.
        sold_date:     Datum prodeje (datetime, výchozí None).
        parsed_model:  Rozpoznaný model (např. 'Fenix 7', výchozí None).

    Returns:
        True pokud byl nový inzerát vložen, False pokud byl ignorován (již existuje).
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

    datum_nalezeni = found_date or datetime.datetime.now()
    datum_nalezeni_str = datum_nalezeni.strftime("%Y-%m-%d %H:%M:%S")

    datum_prodeje_str = (
        sold_date.strftime("%Y-%m-%d %H:%M:%S") if sold_date else None
    )

    portal = urci_portal(inzerat)
    cena_int = parsuj_cenu_na_int(inzerat.cena)

    sql = """
    INSERT OR IGNORE INTO listings (
        item_id, portal, title, parsed_model, price, url, found_date, sold_date, status
    ) VALUES (
        :item_id, :portal, :title, :parsed_model, :price, :url, :found_date, :sold_date, :status
    );
    """

    parametry = {
        "item_id": inzerat.id,
        "portal": portal,
        "title": inzerat.nazev,
        "parsed_model": parsed_model,
        "price": cena_int,
        "url": inzerat.url,
        "found_date": datum_nalezeni_str,
        "sold_date": datum_prodeje_str,
        "status": status,
    }

    try:
        with conn:
            cursor = conn.execute(sql, parametry)
            vlozeno = cursor.rowcount > 0
            if vlozeno:
                logger.debug("Inzerát id=%s vložen do DB (%s).", inzerat.id, portal)
            else:
                logger.debug("Inzerát id=%s již v DB existuje, ignoruji.", inzerat.id)
            return vlozeno
    finally:
        if vlastni_pripojeni:
            conn.close()


def uloz_inzeraty_davku(
    inzeraty: list[Inzerat],
    db_conn: Optional[Union[sqlite3.Connection, str, Path]] = None,
    status: str = "active",
) -> int:
    """Uloží celou dávku inzerátů do databáze v rámci jedné transakce.

    Ignoruje inzeráty s již existujícím item_id.

    Returns:
        Počet nově vložených inzerátů.
    """
    if not inzeraty:
        return 0

    vlastni_pripojeni = False
    if db_conn is None:
        conn = ziskej_pripojeni(DEFAULT_DB_PATH)
        vlastni_pripojeni = True
    elif isinstance(db_conn, (str, Path)):
        conn = ziskej_pripojeni(db_conn)
        vlastni_pripojeni = True
    else:
        conn = db_conn

    ted_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sql = """
    INSERT OR IGNORE INTO listings (
        item_id, portal, title, parsed_model, price, url, found_date, sold_date, status
    ) VALUES (
        :item_id, :portal, :title, :parsed_model, :price, :url, :found_date, :sold_date, :status
    );
    """

    vlozeno_celkem = 0
    try:
        with conn:
            for inz in inzeraty:
                cursor = conn.execute(
                    sql,
                    {
                        "item_id": inz.id,
                        "portal": urci_portal(inz),
                        "title": inz.nazev,
                        "parsed_model": None,
                        "price": parsuj_cenu_na_int(inz.cena),
                        "url": inz.url,
                        "found_date": ted_str,
                        "sold_date": None,
                        "status": status,
                    },
                )
                if cursor.rowcount > 0:
                    vlozeno_celkem += 1
        logger.info("Do DB uloženo %d nových inzerátů z dávky %d.", vlozeno_celkem, len(inzeraty))
        return vlozeno_celkem
    finally:
        if vlastni_pripojeni:
            conn.close()


# ---------------------------------------------------------------------------
# Čtecí funkce (pro testování a analytiku)
# ---------------------------------------------------------------------------

def nacti_inzerat_dle_item_id(
    item_id: str,
    db_conn: Optional[Union[sqlite3.Connection, str, Path]] = None,
) -> Optional[dict[str, Any]]:
    """Načte inzerát z DB podle jeho item_id."""
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
        cursor = conn.execute(
            "SELECT * FROM listings WHERE item_id = ? LIMIT 1;", (item_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        if vlastni_pripojeni:
            conn.close()


def nacti_vsechny_inzeraty(
    db_conn: Optional[Union[sqlite3.Connection, str, Path]] = None,
) -> list[dict[str, Any]]:
    """Vrátí všechny záznamy z tabulky listings."""
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
        cursor = conn.execute("SELECT * FROM listings ORDER BY db_id ASC;")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        if vlastni_pripojeni:
            conn.close()


def nacti_aktivni_inzeraty(
    db_conn: Optional[Union[sqlite3.Connection, str, Path]] = None,
) -> list[dict[str, Any]]:
    """Načte všechny inzeráty z DB, které mají status 'active'.

    Returns:
        Seznam inzerátů jako slovníky.
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
        cursor = conn.execute(
            "SELECT * FROM listings WHERE status = 'active' ORDER BY db_id ASC;"
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        if vlastni_pripojeni:
            conn.close()


def oznac_jako_prodane(
    db_id: int,
    sold_date: Optional[Union[datetime.datetime, str]] = None,
    db_conn: Optional[Union[sqlite3.Connection, str, Path]] = None,
) -> bool:
    """Změní status inzerátu na 'sold' a doplní datum prodeje.

    Args:
        db_id:      Primární klíč záznamu v tabulce listings.
        sold_date:  Datum prodeje (datetime nebo řetězec). Při None se použije aktuální čas.
        db_conn:    Spojení nebo cesta k DB.

    Returns:
        True pokud byl záznam aktualizován, False pokud db_id neexistuje.
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

    if sold_date is None:
        datum_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elif isinstance(sold_date, datetime.datetime):
        datum_str = sold_date.strftime("%Y-%m-%d %H:%M:%S")
    else:
        datum_str = str(sold_date)

    sql = "UPDATE listings SET status = 'sold', sold_date = ? WHERE db_id = ?;"

    try:
        with conn:
            cursor = conn.execute(sql, (datum_str, db_id))
            zmeneno = cursor.rowcount > 0
            if zmeneno:
                logger.info("Inzerát db_id=%d označen jako 'sold' (datum: %s).", db_id, datum_str)
            else:
                logger.warning("Inzerát db_id=%d nebyl v DB nalezen pro označení jako 'sold'.", db_id)
            return zmeneno
    finally:
        if vlastni_pripojeni:
            conn.close()

