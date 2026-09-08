"""
main.py — Hlavní smyčka Multi-Portál Scraperu — Garmin chytré hodinky
Python Agent | Bazoš.cz + Vinted.cz | 24/7 | graceful shutdown

Spuštění:
    py main.py

Env proměnné:
    TELEGRAM_TOKEN       — bot token (povinné)
    TELEGRAM_CHAT_IDS    — čárkou oddělená chat IDs klientů (povinné)
    SCRAPE_INTERVAL_MIN  — minimální interval mezi kontrolami v sekundách (výchozí: 120)
    SCRAPE_INTERVAL_MAX  — maximální interval mezi kontrolami v sekundách (výchozí: 300)
    SEEN_IDS_PATH        — cesta k seen_ids.json (výchozí: scraper/seen_ids.json)
    LOG_LEVEL            — úroveň logování (výchozí: INFO)
    VINTED_ENABLED       — zapnout Vinted.cz scraping (výchozí: true)
"""

from __future__ import annotations

import logging
import os
import random
import signal
import sys
import time
from pathlib import Path

from db import DEFAULT_DB_PATH, init_db, uloz_inzeraty_davku
from filter import nacti_seen_ids, uloz_seen_ids, zpracuj_davku
from notifier import vytvor_notifier_z_env
from scraper import Inzerat, parsuj_html, stahni_stranku, vytvor_session
from tracker import start_tracker_thread
from vinted_scraper import (
    parsuj_html_vinted,
    stahni_vsechny_vinted_stranky,
    vytvor_vinted_session,
)

# ---------------------------------------------------------------------------
# Konfigurace z env
# ---------------------------------------------------------------------------

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
SCRAPE_INTERVAL_MIN = int(os.getenv("SCRAPE_INTERVAL_MIN", "120"))
SCRAPE_INTERVAL_MAX = int(os.getenv("SCRAPE_INTERVAL_MAX", "300"))
SEEN_IDS_PATH = Path(os.getenv("SEEN_IDS_PATH", Path(__file__).parent / "seen_ids.json"))
DB_PATH = Path(os.getenv("DB_PATH", DEFAULT_DB_PATH))
VINTED_ENABLED = os.getenv("VINTED_ENABLED", "true").lower() not in ("false", "0", "no")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

_running = True


def _signal_handler(signum, frame):
    global _running
    logger.info("Přijat signál %s — ukončuji po aktuálním cyklu…", signum)
    _running = False


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)

# ---------------------------------------------------------------------------
# Hlavní smyčka
# ---------------------------------------------------------------------------


def jeden_cyklus(
    session,
    vinted_session,
    notifier,
    seen_ids_cesta: Path,
    vinted_enabled: bool = True,
    db_path: Path | str = DB_PATH,
) -> set[str]:
    """Provede jeden kompletní scrape cyklus pro VSECHNY portaly.

    Portaly:
        1. Bazos.cz  — cesky trh (search: garmin)
        2. Vinted.cz — bazar hodinky (pokud vinted_enabled=True)

    Pipeline:
        1. Stahne HTML z obou portalu
        2. Parsuje inzeraty
        3. Odfiltruje nove + relevantni
        4. Odesle Telegram notifikace
        5. Ulozi zaznamy do SQLite DB (status 'active')
        6. Aktualizuje seen_ids

    Returns:
        Aktualizovana mnozina seen_ids.
    """
    seen = nacti_seen_ids(seen_ids_cesta)
    vsechny_inzeraty: list[Inzerat] = []

    # --- Bazos.cz ---
    try:
        logger.info("[Bazos] Stahuji…")
        html = stahni_stranku(session, pauza=False)
        vsechny_inzeraty.extend(parsuj_html(html))
    except Exception as exc:
        logger.error("[Bazos] Chyba: %s", exc)

    # --- Vinted.cz ---
    if vinted_enabled:
        try:
            logger.info("[Vinted] Stahuji…")
            vinted_inzeraty = stahni_vsechny_vinted_stranky(
                vinted_session, pauza=False, warm_up=False
            )
            vsechny_inzeraty.extend(vinted_inzeraty)
            logger.info("[Vinted] Celkem inzeratu: %d", len(vinted_inzeraty))
        except Exception as exc:
            logger.error("[Vinted] Chyba: %s", exc)

    if not vsechny_inzeraty:
        logger.info("Zadne inzeraty stazeny.")
        return seen

    nove = zpracuj_davku(vsechny_inzeraty, seen_ids_cesta)

    if not nove:
        logger.info("Zadne nove relevantni inzeraty.")
        return seen

    logger.info("Nalezeno %d novych inzeratu -> odesílám notifikace…", len(nove))
    notifier.notifikuj_davku(nove)

    # Uložení do DB se statusem 'active' a aktuálním datem
    try:
        pocet_ulozenych = uloz_inzeraty_davku(nove, db_conn=db_path, status="active")
        logger.info(
            "Uloženo %d inzerátů do DB (%s) se statusem 'active'.",
            pocet_ulozenych,
            db_path,
        )
    except Exception as exc:
        logger.error("Chyba při ukládání inzerátů do databáze: %s", exc)

    # Aktualizujeme seen_ids POUZE po úspesnem odeslani
    seen.update(i.id for i in nove)
    uloz_seen_ids(seen, seen_ids_cesta)

    return seen


def spust():
    """Spusti hlavni smycku multi-portal scraperu."""
    logger.info("=== Garmin Watch Scraper START ===")
    logger.info(
        "Portaly: Bazos.cz%s | Interval: %d-%d s | seen_ids: %s | DB: %s",
        " + Vinted.cz" if VINTED_ENABLED else " (Vinted vypnut)",
        SCRAPE_INTERVAL_MIN,
        SCRAPE_INTERVAL_MAX,
        SEEN_IDS_PATH,
        DB_PATH,
    )

    try:
        notifier = vytvor_notifier_z_env()
    except RuntimeError as exc:
        logger.critical("Chyba konfigurace: %s", exc)
        sys.exit(1)

    # Inicializace SQLite databáze
    try:
        init_db(DB_PATH)
        logger.info("SQLite databáze připravena: %s", DB_PATH)
    except Exception as exc:
        logger.error("Inicializace DB selhala: %s", exc)

    # Spuštění Sales Trackeru v samostatném daemon vlákně
    try:
        start_tracker_thread(db_path=DB_PATH)
        logger.info("Sales Tracker úspěšně nastartován (daemon thread).")
    except Exception as exc:
        logger.error("Spuštění Sales Trackeru selhalo: %s", exc)

    session = vytvor_session()
    vinted_session = vytvor_vinted_session()

    # Zahrejeme Vinted session jednou na zacatku (ziska cookies)
    if VINTED_ENABLED:
        try:
            logger.info("[Vinted] Zahrivam session (homepage)…")
            vinted_session.get("https://www.vinted.cz/", timeout=20)
        except Exception as exc:
            logger.warning("[Vinted] Warm-up selhal: %s", exc)

    while _running:
        logger.info("--- Spoustim cyklus scrapovani ---")
        try:
            jeden_cyklus(
                session=session,
                vinted_session=vinted_session,
                notifier=notifier,
                seen_ids_cesta=SEEN_IDS_PATH,
                vinted_enabled=VINTED_ENABLED,
                db_path=DB_PATH,
            )
        except Exception as exc:
            logger.exception("Neocekavana chyba v cyklu: %s", exc)

        if not _running:
            break

        interval = random.randint(SCRAPE_INTERVAL_MIN, SCRAPE_INTERVAL_MAX)
        logger.info("Cekam %d s do dalsiho cyklu…", interval)

        # Prerusitelny sleep — kontrolujeme _running kazdou sekundu
        for _ in range(interval):
            if not _running:
                break
            time.sleep(1)

    logger.info("=== Garmin Watch Scraper STOP ===")


if __name__ == "__main__":
    spust()
