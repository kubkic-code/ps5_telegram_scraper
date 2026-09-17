"""
scraper.py — Bazoš Scraper — PlayStation 5 konzole
Python Agent | Role: čistý kód, lokální HTML, randomizované prodlevy
"""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Konfigurace
# ---------------------------------------------------------------------------

# Bazoš.cz vyhledávání konzolí PlayStation 5
BASE_URL = "https://www.bazos.cz/search.php"
DEFAULT_PARAMS = {
    "hledat": "ps5",
    "rubriky": "0",
    "hlokalita": "0",
    "humkreis": "25",
    "cenaod": "",
    "cenado": "",
    "Submit": "Hledat",
    "order": "",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "cs-CZ,cs;q=0.9",
    "Referer": "https://www.bazos.cz/search.php?hledat=ps5",
}

# Prodleva mezi dotazy (sekundy) — randomizovaná, aby nás nezabanovali
DELAY_MIN = 4.0
DELAY_MAX = 10.0

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Datový model
# ---------------------------------------------------------------------------

@dataclass
class Inzerat:
    """Jeden inzerát z Bazoše nebo Vinted."""
    id: str                        # numerické ID z URL
    nazev: str                     # název inzerátu
    url: str                       # absolutní URL inzerátu
    cena: str                      # cena jako text (např. "115 000 Kč" nebo "V textu")
    lokalita: str                  # město / PSČ
    datum: str                     # datum zveřejnění nebo TOP stav
    popis: Optional[str] = field(default=None)  # zkrácený popis z výpisu

    def __repr__(self) -> str:
        return f"<Inzerat id={self.id} | {self.nazev!r} | {self.cena} | {self.lokalita}>"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _extrahuj_id_z_url(url: str) -> str:
    """Vytáhne numerické ID inzerátu z URL.

    Příklad:
        https://pc.bazos.cz/inzerat/223396379/playstation-5.php -> '223396379'
    """
    match = re.search(r"/inzerat/(\d+)/", url)
    return match.group(1) if match else ""


def parsuj_html(html: str) -> list[Inzerat]:
    """Naparsuje HTML stránku výsledků Bazoše a vrátí seznam inzerátů.

    Funguje čistě lokálně — žádný HTTP request.

    Args:
        html: Surový HTML obsah stránky výsledků.

    Returns:
        Seznam datových objektů Inzerat.
    """
    soup = BeautifulSoup(html, "html.parser")
    vysledky: list[Inzerat] = []

    # Každý inzerát je v <div class="inzeraty inzeratyflex">
    for kontejner in soup.select("div.inzeraty.inzeratyflex"):
        # --- Název a URL ---
        nadpis_tag = kontejner.select_one("h2.nadpis a")
        if not nadpis_tag:
            logger.debug("Přeskakuji kontejner bez nadpisu.")
            continue

        nazev = nadpis_tag.get_text(strip=True)
        url = nadpis_tag.get("href", "")
        # URL může být relativní — opravíme na absolutní
        if url and not url.startswith("http"):
            url = urljoin("https://www.bazos.cz", url)

        inzerat_id = _extrahuj_id_z_url(url)
        if not inzerat_id:
            logger.warning("Nepodařilo se zjistit ID pro URL: %s", url)
            continue

        # --- Cena ---
        cena_span = kontejner.select_one("div.inzeratycena span[translate='no']")
        cena = cena_span.get_text(strip=True) if cena_span else "Neuvedena"

        # --- Lokalita (text před <br>) ---
        lok_div = kontejner.select_one("div.inzeratylok")
        if lok_div:
            lokalita = lok_div.get_text(separator="|", strip=True).split("|")[0]
        else:
            lokalita = "Neuvedena"

        # --- Datum / TOP status (ze span.velikost10) ---
        datum_span = kontejner.select_one("span.velikost10")
        datum = ""
        if datum_span:
            datum_text = datum_span.get_text(strip=True)
            match = re.search(r"\[(.+?)\]", datum_text)
            datum = match.group(1) if match else datum_text

        # --- Popis (zkrácený) ---
        popis_div = kontejner.select_one("div.popis")
        popis = popis_div.get_text(strip=True) if popis_div else None

        vysledky.append(
            Inzerat(
                id=inzerat_id,
                nazev=nazev,
                url=url,
                cena=cena,
                lokalita=lokalita,
                datum=datum,
                popis=popis,
            )
        )

    logger.info("Naparsováno %d inzerátů.", len(vysledky))
    return vysledky


# ---------------------------------------------------------------------------
# HTTP vrstva (používá se v produkci, NIKOLI v testech)
# ---------------------------------------------------------------------------

def _nahodna_pauza() -> None:
    """Počká náhodný čas mezi DELAY_MIN a DELAY_MAX sekundami."""
    pauza = random.uniform(DELAY_MIN, DELAY_MAX)
    logger.debug("Čekám %.1f s před dalším požadavkem…", pauza)
    time.sleep(pauza)


def stahni_stranku(
    session: requests.Session,
    params: dict | None = None,
    pauza: bool = True,
) -> str:
    """Stáhne HTML výsledků z Bazoše.

    Args:
        session:  Requests session s nastavenými hlavičkami.
        params:   GET parametry (přepíše DEFAULT_PARAMS).
        pauza:    Pokud True, počká náhodnou dobu před requestem.

    Returns:
        HTML obsah stránky jako řetězec.

    Raises:
        requests.HTTPError: Při chybě HTTP.
    """
    if pauza:
        _nahodna_pauza()

    dotaz = {**DEFAULT_PARAMS, **(params or {})}
    response = session.get(BASE_URL, params=dotaz, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def vytvor_session() -> requests.Session:
    """Vytvoří requests.Session s výchozími hlavičkami."""
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


# ---------------------------------------------------------------------------
# Entry point (ruční test)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    session = vytvor_session()
    logger.info("Stahuji stránku z Bazoše (PlayStation 5)…")
    html = stahni_stranku(session, pauza=False)
    inzeraty = parsuj_html(html)

    print(f"\nNalezeno {len(inzeraty)} inzerátů:\n")
    for i in inzeraty:
        print(f"  [{i.datum}] {i.nazev} — {i.cena} — {i.lokalita}")
        print(f"    {i.url}")
