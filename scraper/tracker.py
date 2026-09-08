"""
tracker.py — Modul pro sledování prodejů inzerátů (Sales Tracker)
Python Agent | Detekce prodeje na Bazoš.cz a Vinted.cz | curl_cffi | Background Thread
"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional, Union

from curl_cffi import requests as curl_requests

from db import DEFAULT_DB_PATH, nacti_aktivni_inzeraty, oznac_jako_prodane

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfigurace
# ---------------------------------------------------------------------------

# 12 hodin v sekundách (2x denně kontrola prodejů)
INTERVAL_KONTROLY_SEKUND = 43200

# Prodlevy mezi kontrolami jednotlivých inzerátů (ochrana před zabanováním)
PAUZA_MIN_SEKUND = 1.5
PAUZA_MAX_SEKUND = 4.0

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "cs-CZ,cs;q=0.9,en-US;q=0.8,en;q=0.7",
    "sec-ch-ua-platform": '"Windows"',
    "Upgrade-Insecure-Requests": "1",
}


# ---------------------------------------------------------------------------
# Detekční logika prodeje
# ---------------------------------------------------------------------------

def _normalizuj_text(text: str) -> str:
    """Odstraní základní diakritiku a převede na malá písmena pro robustnější porovnání."""
    nahrazeni = {
        "á": "a", "č": "c", "ď": "d", "é": "e", "ě": "e",
        "í": "i", "ň": "n", "ó": "o", "ř": "r", "š": "s",
        "ť": "t", "ú": "u", "ů": "u", "ý": "y", "ž": "z",
    }
    t = text.lower()
    for s, b in nahrazeni.items():
        t = t.replace(s, b)
    return t


def vyhodnot_stav_inzeratu(
    portal: str,
    status_code: int,
    text: str,
    is_redirect: bool = False,
    history: Optional[list] = None,
) -> bool:
    """Vyhodnotí, zda je inzerát již prodán/smazán.

    Pravidla:
    - Bazoš:
        - HTTP 404
        - Text obsahuje 'inzerát byl smazán', 'neexistuje' nebo 'chyba'
    - Vinted:
        - HTTP 404
        - Přesměrování (is_redirect=True, redirect status kódy, neprázdná historie)

    Returns:
        True pokud je inzerát prodán/smazán, False pokud je stále aktivní.
    """
    portal_lower = (portal or "").lower()

    if status_code == 404:
        return True

    if portal_lower == "bazos":
        norm_text = _normalizuj_text(text)
        bazos_vzory = [
            "inzerat byl smazan",
            "neexistuje",
            "chyba",
        ]
        if any(vzor in norm_text for vzor in bazos_vzory):
            return True
        return False

    elif portal_lower == "vinted":
        # Vinted při smazání/prodeji přesměruje zpět na katalog nebo vrátí 404
        if is_redirect or status_code in (301, 302, 303, 307, 308):
            return True
        if history and len(history) > 0:
            return True
        return False

    # Obecný fallback pro ostatní nebo neznámé portály
    if status_code >= 400:
        return True
    norm_text = _normalizuj_text(text)
    if "smazan" in norm_text or "neexistuje" in norm_text:
        return True

    return False


# ---------------------------------------------------------------------------
# HTTP vrstva (curl_cffi Session)
# ---------------------------------------------------------------------------

def vytvor_tracker_session() -> curl_requests.Session:
    """Vytvoří curl_cffi Session s impersonací Chrome pro obcházení anti-bot ochran."""
    s = curl_requests.Session(impersonate="chrome")
    s.headers.update(HEADERS)
    return s


def zkontroluj_inzerat(
    inzerat: dict[str, Any],
    session: Optional[curl_requests.Session] = None,
    pauza: bool = True,
) -> bool:
    """Zkontroluje stav jednoho inzerátu přes HTTP GET dotaz.

    Args:
        inzerat: Slovník s daty inzerátu z DB (musí obsahovat 'url' a 'portal').
        session: Volitelná instance curl_cffi Session (pokud None, vytvoří se nová).
        pauza:   Zda vložit náhodnou prodlevu před požadavkem.

    Returns:
        True pokud je inzerát prodán/smazán, False pokud je stále aktivní (nebo při síťové chybě).
    """
    url = inzerat.get("url", "")
    portal = inzerat.get("portal", "")

    if not url:
        logger.warning("Inzerát db_id=%s nemá URL, nelze zkontrolovat.", inzerat.get("db_id"))
        return False

    if pauza:
        pauza_doba = random.uniform(PAUZA_MIN_SEKUND, PAUZA_MAX_SEKUND)
        time.sleep(pauza_doba)

    vlastni_session = False
    if session is None:
        session = vytvor_tracker_session()
        vlastni_session = True

    try:
        response = session.get(url, timeout=20, allow_redirects=True)
        is_redirect = (
            bool(response.history)
            or response.status_code in (301, 302, 303, 307, 308)
        )
        prodan = vyhodnot_stav_inzeratu(
            portal=portal,
            status_code=response.status_code,
            text=response.text or "",
            is_redirect=is_redirect,
            history=getattr(response, "history", None),
        )
        if prodan:
            logger.info(
                "[Tracker] Inzerát db_id=%s vyhodnocen jako PRODÁN/SMAZÁN (portal=%s, status=%s).",
                inzerat.get("db_id"),
                portal,
                response.status_code,
            )
        return prodan

    except Exception as exc:
        logger.warning(
            "[Tracker] Chyba při ověřování URL pro db_id=%s (%s): %s",
            inzerat.get("db_id"),
            url,
            exc,
        )
        # Při dočasné síťové chybě inzerát NEUZNÁME za prodaný
        return False
    finally:
        if vlastni_session:
            try:
                session.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Hromadná kontrola aktivních inzerátů
# ---------------------------------------------------------------------------

def zkontroluj_inzeraty(
    db_conn: Optional[Union[Path, str, Any]] = None,
    session: Optional[curl_requests.Session] = None,
    pauza_mezi_dotazy: float = 2.0,
) -> int:
    """Proj瀋e všechny aktivní inzeráty z DB a ověří jejich dostupnost.

    Inzeráty, které již nejsou dostupné, označí v DB jako 'sold' s aktuálním časem prodeje.

    Args:
        db_conn:           Cesta nebo spojení do SQLite databáze.
        session:           Volitelná curl_cffi Session.
        pauza_mezi_dotazy: Prodleva mezi požadavky v sekundách (pokud <= 0, bez prodlevy).

    Returns:
        Počet inzerátů označených jako prodané.
    """
    aktivni = nacti_aktivni_inzeraty(db_conn=db_conn)
    logger.info("[Tracker] Zahajuji kontrolu %d aktivních inzerátů.", len(aktivni))

    if not aktivni:
        return 0

    vlastni_session = False
    if session is None:
        session = vytvor_tracker_session()
        vlastni_session = True

    oznaceno_jako_prodane = 0

    try:
        for index, inz in enumerate(aktivni):
            musi_pauza = pauza_mezi_dotazy > 0 and index > 0
            if musi_pauza:
                pauza = random.uniform(pauza_mezi_dotazy * 0.8, pauza_mezi_dotazy * 1.2)
                time.sleep(pauza)

            je_prodan = zkontroluj_inzerat(inz, session=session, pauza=False)
            if je_prodan:
                db_id = inz.get("db_id")
                if db_id and oznac_jako_prodane(db_id, db_conn=db_conn):
                    oznaceno_jako_prodane += 1

        logger.info(
            "[Tracker] Kontrola dokončena. Celkem zkontrolováno: %d, nově označeno jako prodané: %d.",
            len(aktivni),
            oznaceno_jako_prodane,
        )
        return oznaceno_jako_prodane
    finally:
        if vlastni_session:
            try:
                session.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Běh v pozadí (Background Thread)
# ---------------------------------------------------------------------------

def _tracker_worker(
    db_path: Union[Path, str],
    interval_sekund: int,
    stop_event: threading.Event,
) -> None:
    """Pracovní smyčka běžící v samostatném vlákně."""
    logger.info(
        "[Tracker] Vlákno trackeru spuštěno (interval: %d s / %.1f h).",
        interval_sekund,
        interval_sekund / 3600.0,
    )

    while not stop_event.is_set():
        try:
            zkontroluj_inzeraty(db_conn=db_path)
        except Exception as exc:
            logger.exception("[Tracker] Neočekávaná chyba v cyklu trackeru: %s", exc)

        # Čekání s možností okamžitého probuzení při ukončení aplikace
        if stop_event.wait(timeout=interval_sekund):
            break

    logger.info("[Tracker] Vlákno trackeru bylo korektně ukončeno.")


def start_tracker_thread(
    db_path: Union[Path, str] = DEFAULT_DB_PATH,
    interval_sekund: int = INTERVAL_KONTROLY_SEKUND,
    stop_event: Optional[threading.Event] = None,
) -> threading.Thread:
    """Spustí sledování prodejů v samostatném daemon vlákně.

    Vlákno běží v nekonečné smyčce s pauzou 12 hodin (43200 sekund)
    a neblokuje hlavní scrapovací proces scraperu.

    Args:
        db_path:         Cesta k SQLite databázi.
        interval_sekund: Interval mezi kontrolami (výchozí 43200 s = 12 h).
        stop_event:      Volitelný threading.Event pro řízené zastavení vlákna.

    Returns:
        Instance spuštěného threading.Thread s daemon=True.
    """
    event = stop_event if stop_event is not None else threading.Event()
    thread = threading.Thread(
        target=_tracker_worker,
        args=(db_path, interval_sekund, event),
        name="SalesTrackerThread",
        daemon=True,
    )
    thread.start()
    logger.info("Vlákno SalesTrackerThread nastartováno.")
    return thread
