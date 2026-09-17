"""
vinted_scraper.py — Vinted.cz Scraper (PlayStation 5 konzole)
Python Agent | Samostatný modul, výstup sjednocen do formátu Inzerat

Portál: https://www.vinted.cz/catalog?search_text=ps5&order=newest_first
Kategorie: Herní konzole → PlayStation 5

Anti-bot strategie — curl_cffi místo requests:
- curl_cffi.requests s impersonate='chrome' emuluje TLS fingerprint Chrome
- Cloudflare / JS challenge jsou tím transparentně obejity
- Randomizované prodlevy 6–15 s
- Session s cookies (warm-up přes homepage)
- Referer chain (homepage → výsledky)
- Accept-Language + další realistické hlavičky
"""

from __future__ import annotations

import logging
import random
import re
import time
from typing import Optional
from urllib.parse import urljoin, urlencode

from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup

from scraper import Inzerat
from filter import rozbal_vinted_kompozitni_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfigurace
# ---------------------------------------------------------------------------

BASE_URL = "https://www.vinted.cz"

# Vinted search URL — plošné prohledávání bez omezení na kategorii
SEARCH_URL = "https://www.vinted.cz/catalog?search_text=ps5&order=newest_first"

# Plošná URL pro stažení PS5 inzerátů na Vintedu
SEARCH_URLS: list[str] = [
    SEARCH_URL,
]

# Prefix pro Vinted ID — aby se nepletlo s Bazoš ID v seen_ids.json
ID_PREFIX = "vt_"

# Prodlevy — Vinted má silnou anti-bot ochranu
DELAY_MIN = 6.0
DELAY_MAX = 15.0
DELAY_BETWEEN_REQUESTS = (3.0, 6.0)  # pauza mezi URL v referer chainu

# curl_cffi s impersonate='chrome' automaticky nastaví:
# - správný TLS fingerprint (JA3/JA4) odpovídající Chrome
# - HTTP/2 s pseudo-headers ve správném pořadí
# - realistický User-Agent a Accept hlavičky
HEADERS_JAZYK = {
    "Accept-Language": "cs-CZ,cs;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "sec-ch-ua-platform": '"Windows"',
    "Upgrade-Insecure-Requests": "1",
}

HEADERS_SEARCH = {
    **HEADERS_JAZYK,
    "Referer": BASE_URL + "/",
}

# Typ pro anotace
VintedSession = curl_requests.Session


# ---------------------------------------------------------------------------
# Pomocné funkce
# ---------------------------------------------------------------------------

def _nahodna_pauza(min_s: float = DELAY_MIN, max_s: float = DELAY_MAX) -> None:
    """Čeká náhodnou dobu — simuluje lidské chování."""
    pauza = random.uniform(min_s, max_s)
    logger.debug("[Vinted] Čekám %.1f s…", pauza)
    time.sleep(pauza)


def _extrahuj_vinted_id_z_url(url: str) -> str:
    """Vytáhne ID inzerátu z Vinted URL.

    Příklady:
        /items/123456789-ps5-digital  →  'vt_123456789'
        https://www.vinted.cz/items/987654321-playstation-5  →  'vt_987654321'
    """
    match = re.search(r"/items/(\d+)", url)
    return f"{ID_PREFIX}{match.group(1)}" if match else ""


def _ocisti_cenu(cena_text: str) -> str:
    """Normalizuje formát ceny z Vinted do čitelné formy.

    Příklady: '2 500 Kč' → '2 500 Kč'  |  'Zdarma' → 'Zdarma'
    """
    cena = cena_text.strip()
    if not cena:
        return "Neuvedena"

    # Ošetření Vinted formátu se dvěma cenami: '5108.24 Kč, 5381.65 Kč' -> vezmeme první
    if "," in cena and ("Kč" in cena or "€" in cena):
        casti = cena.split(",")
        if len(casti) > 1 and any(char.isdigit() for char in casti[1]) and ("Kč" in casti[0] or "€" in casti[0]):
            cena = casti[0].strip()

    return cena


# ---------------------------------------------------------------------------
# Parser — čistě lokální, žádný HTTP
# ---------------------------------------------------------------------------

def parsuj_html_vinted(html: str) -> list[Inzerat]:
    """Naparsuje HTML stránky výsledků Vinted a vrátí seznam Inzerat.

    Selektor logika (Vinted.cz layout 2026):
    - Container: div[data-testid='grid-item'] nebo article s odkazem na /items/
    - Alternativa: a[href*='/items/'] uvnitř produktové mřížky
    - Název:  data-testid='description-title' nebo img[alt] nebo a[title]
    - URL:    a[href*='/items/']
    - Cena:   data-testid='price-text' nebo span s třídou obsahující 'price'
    - Datum:  Vinted na listingu datum neukazuje → placeholder 'VT'

    Args:
        html: Surový HTML obsah stránky výsledků.

    Returns:
        Seznam datových objektů Inzerat sjednocených s Bazoš formátem.
    """
    soup = BeautifulSoup(html, "html.parser")
    vysledky: list[Inzerat] = []
    seen_ids: set[str] = set()

    # Strategie 1: Vinted renderuje produkty jako <div data-testid="grid-item">
    # nebo jako přímé <a href="/items/..."> uvnitř feed containeru
    polozky = soup.find_all("a", href=re.compile(r"/items/\d+"))

    for link_tag in polozky:
        href = link_tag.get("href", "")
        if not href:
            continue

        # Absolutní URL
        url = urljoin(BASE_URL, href) if not href.startswith("http") else href

        inzerat_id = _extrahuj_vinted_id_z_url(url)
        if not inzerat_id or inzerat_id in seen_ids:
            continue
        seen_ids.add(inzerat_id)

        # Kontejner inzerátu (grid-item / item-box nebo samotný odkaz)
        card = (
            link_tag.find_parent(attrs={"data-testid": re.compile(r"grid-item|item-box", re.I)})
            or link_tag.parent
            or link_tag
        )

        # --- Značka a Název ---
        # Na Vintedu bývá:
        # - data-testid="description-title" (často Značka prodejce, např. 'Sony' nebo 'PlayStation')
        # - data-testid="description-subtitle" (často doplňující název, model, velikost)
        # - data-testid="item-brand" nebo třída 'brand' (explicitní značka)
        title_el = card.find(attrs={"data-testid": "description-title"})
        subtitle_el = card.find(attrs={"data-testid": "description-subtitle"})
        brand_el = card.find(attrs={"data-testid": re.compile(r"item-brand|brand", re.I)})

        title_text = title_el.get_text(strip=True) if title_el else ""
        subtitle_text = subtitle_el.get_text(strip=True) if subtitle_el else ""
        brand_text = brand_el.get_text(strip=True) if brand_el else ""

        img = card.find("img") or link_tag.find("img")
        img_alt = img.get("alt", "").strip() if img else ""
        link_title = link_tag.get("title", "").strip() or card.get("title", "").strip()
        link_text = link_tag.get_text(strip=True)

        # Zjištění značky (pokud prodejce vyplnil jen Značku nebo je značka oddělená)
        znacka = ""
        if brand_text:
            znacka = brand_text
        elif title_text and any(k in title_text.lower() for k in ("sony", "playstation", "ps5")):
            znacka = title_text
        elif subtitle_text and any(k in subtitle_text.lower() for k in ("sony", "playstation", "ps5")):
            znacka = subtitle_text
        elif any(k in img_alt.lower() for k in ("sony", "playstation", "ps5")):
            znacka = "PlayStation"
        elif any(k in url.lower() for k in ("sony", "playstation", "ps5")):
            znacka = "PlayStation"

        # Sestavení názvu inzerátu
        nazev = ""
        if title_text and subtitle_text:
            if title_text.lower() == subtitle_text.lower():
                nazev = title_text
            elif title_text.lower() in subtitle_text.lower():
                nazev = subtitle_text
            elif subtitle_text.lower() in title_text.lower():
                nazev = title_text
            else:
                nazev = f"{title_text} {subtitle_text}"
        elif title_text:
            nazev = title_text
        elif subtitle_text:
            nazev = subtitle_text
        elif img_alt:
            nazev = img_alt
        elif link_title:
            nazev = link_title
        elif link_text:
            nazev = link_text

        # Pokud prodejce vyplnil POUZE Značku (nebo název chybí / je příliš krátký),
        # bezpečně použijeme Značku
        if not nazev or len(nazev) < 3:
            if znacka:
                nazev = znacka
            else:
                # Fallback: extrakce ze slugu v URL
                slug_match = re.search(r"/items/\d+-([^/?#]+)", url)
                if slug_match:
                    slug_nazev = slug_match.group(1).replace("-", " ").strip()
                    if len(slug_nazev) >= 3:
                        nazev = slug_nazev.title()

        # Pokud máme explicitní značku (např. 'Sony') a v sestaveném názvu dosud není,
        # připojíme ji pro jednoznačnost
        if znacka and znacka.lower() not in nazev.lower():
            if brand_text or not any(k in nazev.lower() for k in ("ps5", "playstation", "sony")):
                nazev = f"{znacka} {nazev}".strip()

        if not nazev or len(nazev) < 3:
            logger.debug("[Vinted] Přeskakuji inzerát bez názvu (id=%s)", inzerat_id)
            continue

        # --- Cena ---
        cena_raw = ""
        cena_el = link_tag.find(attrs={"data-testid": "price-text"}) or card.find(attrs={"data-testid": "price-text"})
        if not cena_el:
            # Fallback: hledáme span/div/p s 'price' v class v kartě i v odkazu
            for el in (link_tag.find_all(["span", "div", "p"]) + card.find_all(["span", "div", "p"])):
                klasy = " ".join(el.get("class", []))
                if "price" in klasy.lower():
                    cena_raw = el.get_text(strip=True)
                    break
        else:
            cena_raw = cena_el.get_text(strip=True)

        # Pokud cena nebyla nalezena samostatně, nebo název obsahuje kompozitní Vinted data:
        cena_z_nazvu, cisty_nazev, extra_popis = rozbal_vinted_kompozitni_text(nazev)
        if cisty_nazev and cisty_nazev != nazev:
            nazev = cisty_nazev
        if cena_z_nazvu and not cena_raw:
            cena_raw = cena_z_nazvu

        # Fallback z link_title, img_alt nebo link_text, pokud cena stále chybí
        if not cena_raw:
            for src in (link_title, img_alt, link_text):
                c_src, c_nazev, c_popis = rozbal_vinted_kompozitni_text(src)
                if c_src:
                    cena_raw = c_src
                    if not extra_popis and c_popis:
                        extra_popis = c_popis
                    break

        cena = _ocisti_cenu(cena_raw) if cena_raw else "Neuvedena"

        # --- Lokalita ---
        lokalita = "CZ"  # Vinted.cz → primárně CZ sellers
        lok_el = link_tag.find(attrs={"data-testid": "item-location"}) or card.find(attrs={"data-testid": "item-location"})
        if lok_el:
            lokalita = lok_el.get_text(strip=True) or "CZ"

        # --- Datum ---
        datum = "VT"  # Vinted neukazuje datum na listingu

        # --- Popis ---
        popis = None
        if subtitle_text:
            popis = subtitle_text
        elif extra_popis:
            popis = extra_popis
        else:
            popis_el = card.find(attrs={"data-testid": "description-subtitle"}) or link_tag.find(attrs={"data-testid": "description-subtitle"})
            if popis_el:
                popis = popis_el.get_text(strip=True) or None

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

    logger.info("[Vinted] Naparsováno %d inzerátů.", len(vysledky))
    return vysledky


# ---------------------------------------------------------------------------
# HTTP vrstva — curl_cffi s Chrome impersonací
# ---------------------------------------------------------------------------

def vytvor_vinted_session() -> curl_requests.Session:
    """Vytvoří curl_cffi Session s impersonací Chrome.

    curl_cffi automaticky nastaví:
    - TLS fingerprint (JA3/JA4) odpovídající aktuálnímu Chrome
    - HTTP/2 s pseudo-headers ve správném pořadí
    - realistický User-Agent a Accept hlavičky

    To je klíčový rozdíl od requests — Vinted/Cloudflare detekci
    standardní knihovny requests rozpoznává podle TLS otisku.
    """
    s = curl_requests.Session(impersonate="chrome")
    s.headers.update(HEADERS_JAZYK)
    return s


def _warm_up_session(session: curl_requests.Session) -> None:
    """Zahřeje session návštěvou homepage → získá cookies a session token.

    Toto se dělá JEDNOU při inicializaci — ne před každým requestem.
    """
    try:
        logger.debug("[Vinted] Zahřívám session (homepage)…")
        session.get(BASE_URL + "/", headers=HEADERS_JAZYK, timeout=25)
        _nahodna_pauza(*DELAY_BETWEEN_REQUESTS)
    except Exception as exc:
        logger.warning("[Vinted] Warm-up selhal: %s", exc)


def stahni_vinted_stranku(
    session: curl_requests.Session,
    url: str = SEARCH_URL,
    pauza: bool = True,
    warm_up: bool = False,
) -> str:
    """Stáhne HTML výsledků z Vinted pomocí curl_cffi.

    Args:
        session:  curl_cffi Session s impersonate='chrome'.
        url:      URL stránky výsledků.
        pauza:    Pokud True, čeká náhodnou dobu před requestem.
        warm_up:  Pokud True, nejprve navštíví homepage.

    Returns:
        HTML obsah stránky jako řetězec.

    Raises:
        curl_cffi.requests.errors.RequestsError: Při síťové chybě.
        Exception: Při HTTP chybě (403 → raise po logu).
    """
    if warm_up:
        _warm_up_session(session)

    if pauza:
        _nahodna_pauza()

    response = session.get(url, headers=HEADERS_SEARCH, timeout=30)

    if response.status_code == 403:
        logger.warning(
            "[Vinted] HTTP 403 — anti-bot detekce. "
            "Zkontroluj verzi curl_cffi a zkus jiný impersonate target."
        )
        response.raise_for_status()

    response.raise_for_status()
    return response.text


def stahni_vsechny_vinted_stranky(
    session: curl_requests.Session,
    pauza: bool = True,
    warm_up: bool = True,
) -> list[Inzerat]:
    """Stáhne a zparsuje inzeráty ze všech nakonfigurovaných SEARCH_URLS.

    Args:
        session: curl_cffi Session.
        pauza:   Zda čekat mezi requesty.
        warm_up: Zda zahřát session před prvním requestem.

    Returns:
        Sjednocený seznam inzerátů ze všech URL (bez duplikátů).
    """
    vsechny: list[Inzerat] = []
    seen_ids: set[str] = set()

    first = True
    for url in SEARCH_URLS:
        try:
            html = stahni_vinted_stranku(
                session,
                url=url,
                pauza=pauza,
                warm_up=(warm_up and first),
            )
            inzeraty = parsuj_html_vinted(html)
            for i in inzeraty:
                if i.id not in seen_ids:
                    vsechny.append(i)
                    seen_ids.add(i.id)
            if pauza and not first:
                _nahodna_pauza(*DELAY_BETWEEN_REQUESTS)
        except Exception as exc:
            logger.error("[Vinted] Chyba při stahování %s: %s", url, exc)
        first = False

    return vsechny
