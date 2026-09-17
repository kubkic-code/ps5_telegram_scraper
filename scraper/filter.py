"""
filter.py — Filtrace a deduplikace inzerátů — PlayStation 5 konzole
Python Agent | LLM validace (Gemini 3.5 Flash Lite) + anti-scam + cenový filtr + seen_ids

Validační pipeline:
    1. Google Translate URL          — rychlý drop, bez API
    2. Scam detekce                  — rychlý drop, bez API
    3. Cenový filtr (min + max)      — rychlý drop, bez API
    4. LLM validace (Gemini)         — pokud GEMINI_API_KEY nastaven (rotace klíčů)
       → NEBO keyword fallback       — pokud GEMINI_API_KEY chybí (offline testy)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple, Optional

from scraper import Inzerat

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cenové mantinely
# ---------------------------------------------------------------------------

MIN_CENA_CZK = 3_000    # Kč — pod tuto hranici je podezřelé
MAX_CENA_CZK = 13_500   # Kč — konzervativní limit: vylučuje VR sety a mega balíčky
MIN_CENA_EUR = 120      # EUR — odpovídá cca 3 000 Kč
MAX_CENA_EUR = 540      # EUR — odpovídá cca 13 500 Kč

# ---------------------------------------------------------------------------
# Keyword fallback (používá se, když GEMINI_API_KEY není nastaven)
# Zachovává původní chování — testy mohou běžet offline
# ---------------------------------------------------------------------------

KLICOVA_SLOVA_WHITELIST: list[str] = [
    "ps5",
    "playstation 5",
    "playstation5",
    "play station 5",
    "ps 5",
]

NEGATIVNI_SLOVA: list[str] = [
    "ovladač", "ovladac", "controller", "dualsense", "dual sense",
    "headset", "sluchátka", "sluchatka", "nabíječka", "nabijecka",
    "stojan", "kryt", "skin", "pouzdro", "kabel", "hdmi",
    "chladič", "chladich",
    "hra ",  " hra", "hry", "game ", " game", "games",
    "rozbité", "rozbita", "nefunkční", "nefunkcni",
    "na díly", "na součástky", "poškozená", "poskozen",
    "prasklý", "praskly", "vryp",
    "pronájem", "půjčím", "pujcim", "k pronájmu",
    "hledám", "hledam", "sháním", "koupím", "koupim", "wanted",
    "vyměním", "vymenim", "výměna za",
    "ps4", "ps3", "ps2", "playstation 4", "xbox", "nintendo", "switch",
    "účet", "ucet", "account",
    "vr2", " vr ", "psvr",
    "volant",
    "krabice",
]

SCAM_VZORY: list[str] = [
    r"whatsapp",
    r"telegram\s+@",
    r"western\s+union",
    r"paypal",
    r"záloha.*zahrani",
    r"zaslat\s+pen[íi]ze",
    r"advance\s+payment",
    r"wire\s+transfer",
    r"escrow",
]

GOOGLE_TRANSLATE_VZORY: list[str] = [
    r"translate\.google",
    r"translate\.googleusercontent",
    r"&hl=",
]

DEFAULT_SEEN_IDS_PATH = Path(__file__).parent / "seen_ids.json"

# ---------------------------------------------------------------------------
# LLM odpověď — datová třída
# ---------------------------------------------------------------------------

@dataclass
class LLMVysledek:
    """Strukturovaný výsledek z Gemini LLM validace."""
    is_valid: bool
    clean_name: str
    edition: str          # 'Disk' | 'Digital' | 'Unknown'
    is_slim: bool
    duvod: str = ""       # interní — proč je/není validní (pro debug logy)
    storage: str = ""     # např. '825GB' | '1TB'


# ---------------------------------------------------------------------------
# Výsledek filtrace
# ---------------------------------------------------------------------------

class VysledekFiltrace(NamedTuple):
    """Výsledek rozhodnutí filtru pro jeden inzerát."""
    inzerat: Inzerat
    prijat: bool
    duvod_zamitnuti: str  # prázdný řetězec = přijat


# ---------------------------------------------------------------------------
# Gemini LLM validace
# ---------------------------------------------------------------------------

_GEMINI_SYSTEM_PROMPT = """\
Tvojí rolí je rozeznat, zda inzerát prodává reálnou herní konzoli PlayStation 5.

PRAVIDLA:
- Vrať is_valid: false pro:
  * Příslušenství: PlayStation Portal, DualSense ovladač, headset, kryty, kabely, stojan, nabíječka
  * Samotné hry: "God of War", "Spider-Man" apod. (bez konzole)
  * Prázdné krabice od PS5
  * Herní účty, PSN účty
  * PC komponenty (ASRock BC-250, těžební karty)
  * Poptávky (hledám, koupím)
  * VR sety bez konzole (PSVR2 samotné)
- Vrať is_valid: true pro:
  * Samotnou PS5 konzoli (Disk nebo Digital edice, Standard nebo Slim)
  * Bundle konzole + hry (konzole je v balíčku — is_valid: true)
- Inzeráty mohou být v češtině, slovenštině nebo polštině. Zpracuj všechny jazyky.
- clean_name: Standardizovaný název VŽDY v češtině. Příklady:
  "PlayStation 5 Disk Edition", "PlayStation 5 Digital Edition",
  "PlayStation 5 Slim Disk", "PlayStation 5 Slim Digital", "PlayStation 5 Pro"
  Ignoruj polská/zmatená jména. Neuváděj hry navíc.
- edition: "Disk" pokud má mechaniku, "Digital" pokud je bez mechaniky, "Unknown" pokud nejasné.
- is_slim: true pokud je Slim verze, jinak false.
- Pokus se z inzerátu vyčíst kapacitu disku (vetšinou to tam lidi píšou). Původní (Fat) verze mívají 825GB, verze Slim mívají 1TB. Pokud je to jasné, vrať hodnotu jako '825GB' nebo '1TB'. Pokud si nejsi jistý, vrať prázdný řetězec.

Vrať POUZE JSON objekt bez markdown bloků:
{"is_valid": bool, "clean_name": str, "edition": "Disk"|"Digital"|"Unknown", "is_slim": bool, "storage": str, "duvod": str}
"""

# Gemini klient — inicializován lazy při prvním volání
_gemini_client = None
_gemini_key_checked = False


def _get_gemini_client():
    """Vrátí Gemini klient (lazy init). Vrátí None pokud API key chybí.

    Používá nový oficiální balíček google-genai (from google import genai).
    Podporuje více klíčů oddělených čárkou (vrátí klienta pro první platný klíč).
    """
    global _gemini_client, _gemini_key_checked
    if _gemini_key_checked:
        return _gemini_client

    _gemini_key_checked = True
    raw_keys = os.getenv("GEMINI_API_KEY", "").strip()
    api_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]

    # --- Diagnostický log: klíč je/není nastaven (BEZ vypsání hodnoty!) ---
    logger.info("GEMINI_API_KEY nastaven: %s", "Ano" if api_keys else "Ne")

    if not api_keys:
        logger.info(
            "GEMINI_API_KEY není nastaven — LLM validace vypnuta, použije se keyword fallback."
        )
        return None

    try:
        from google import genai  # type: ignore

        _gemini_client = genai.Client(api_key=api_keys[0])
        logger.info("Gemini klient (google-genai) úspěšně inicializován.")
    except ImportError:
        logger.warning(
            "Knihovna google-genai není nainstalovaná. "
            "Spusť: pip install google-genai==2.23.0. Použije se keyword fallback."
        )
        _gemini_client = None
    except Exception as exc:
        logger.error("Kritická chyba při inicializaci Gemini klienta: %s", exc)
        _gemini_client = None

    return _gemini_client


# Alias pro zpětnou kompatibilitu (interní použití)
_get_gemini_model = _get_gemini_client


def validuj_llm(inzerat: Inzerat) -> Optional[LLMVysledek]:
    """Pošle inzerát do Gemini a vrátí strukturovaný výsledek.

    Používá nový google-genai SDK (from google import genai).
    Model: gemini-3.5-flash-lite — rychlý, bezplatný, stabilní v API v1.
    Podporuje rotaci API klíčů při vyčerpání limitů (429 / quota / exhausted / rate limit).

    Vrátí None pokud:
    - GEMINI_API_KEY není nastaven (→ caller použije keyword fallback)
    - Knihovna google-genai není nainstalována (→ caller použije keyword fallback)
    - Všechny klíče selžou / vyčerpají limit  (→ caller použije keyword fallback)

    Args:
        inzerat: Parsovaný inzerát z Bazoše / Vintedu.

    Returns:
        LLMVysledek nebo None (při chybě / bez API klíče).
    """
    raw_keys = os.getenv("GEMINI_API_KEY", "")
    if not raw_keys.strip():
        return None

    api_keys = raw_keys.split(",")

    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except ImportError:
        logger.warning(
            "Knihovna google-genai není nainstalovaná. "
            "Spusť: pip install google-genai==2.23.0. Použije se keyword fallback."
        )
        return None

    nazev_inzeratu = (inzerat.nazev or "").strip()
    popis = (inzerat.popis or "").strip()[:800]   # omezíme délku pro úsporu tokenů
    cena = (inzerat.cena or "").strip()

    prompt = (
        f"Název inzerátu: {nazev_inzeratu}\n"
        f"Popis: {popis}\n"
        f"Cena: {cena}"
    )

    # response_schema explicitně definuje strukturu JSON výstupu.
    _response_schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "is_valid":   types.Schema(type=types.Type.BOOLEAN),
            "clean_name": types.Schema(type=types.Type.STRING),
            "edition":    types.Schema(
                type=types.Type.STRING,
                enum=["Disk", "Digital", "Unknown"],
            ),
            "is_slim":    types.Schema(type=types.Type.BOOLEAN),
            "storage":    types.Schema(type=types.Type.STRING),
            "duvod":      types.Schema(type=types.Type.STRING),
        },
        required=["is_valid", "clean_name", "edition", "is_slim"],
    )

    response = None
    for key in api_keys:
        if not key.strip():
            continue
        try:
            client = genai.Client(api_key=key.strip())
            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=_GEMINI_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=_response_schema,
                    temperature=0.0,
                    max_output_tokens=256,
                ),
            )
            break
        except Exception as exc:
            err_msg = str(exc).lower()
            if any(term in err_msg for term in ("429", "quota", "exhausted", "rate limit")):
                logger.warning("Klíč vyčerpán, přepínám na další...")
                continue
            logger.error("Kritická chyba LLM API pro '%s': %s", nazev_inzeratu, exc)
            continue

    if response is None:
        return None

    try:
        raw = (response.text or "").strip()

        # Odstraníme případné markdown obalení (obranná vrstva)
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)

        is_valid = bool(data.get("is_valid", False))
        duvod_z_jsonu = str(data.get("duvod", ""))

        if not is_valid:
            logger.info(f"Zahazuji: {nazev_inzeratu} | Důvod: {duvod_z_jsonu}")

        edition = data.get("edition", "Unknown")
        if edition not in ("Disk", "Digital", "Unknown"):
            edition = "Unknown"

        clean_name = str(data.get("clean_name", nazev_inzeratu)).strip() or nazev_inzeratu
        storage = str(data.get("storage", "")).strip()

        # Připojíme nalezené storage na konec clean_name, pokud tam ještě nebylo obsaženo
        if storage:
            storage_clean = re.sub(r"\s+", "", storage).lower()
            clean_name_compact = re.sub(r"\s+", "", clean_name).lower()
            if storage_clean not in clean_name_compact:
                clean_name = f"{clean_name} {storage}".strip()

        return LLMVysledek(
            is_valid=is_valid,
            clean_name=clean_name,
            edition=edition,
            is_slim=bool(data.get("is_slim", False)),
            duvod=duvod_z_jsonu,
            storage=storage,
        )

    except (json.JSONDecodeError, KeyError, AttributeError) as exc:
        logger.error("Kritická chyba LLM API — neparsovatelná odpověď pro '%s': %s", nazev_inzeratu, exc)
        return None


# ---------------------------------------------------------------------------
# Keyword fallback funkce (zachovány pro offline testy + fallback)
# ---------------------------------------------------------------------------

def _obsahuje_negativni_slovo(inzerat: Inzerat) -> tuple[bool, str]:
    """Vrátí (True, slovo) pokud inzerát obsahuje negativní klíčové slovo."""
    text = f"{inzerat.nazev} {inzerat.popis or ''}".lower()
    for slovo in NEGATIVNI_SLOVA:
        if slovo.lower() in text:
            return True, slovo
    return False, ""


def _obsahuje_klicove_slovo(inzerat: Inzerat) -> bool:
    """Keyword whitelist fallback — použije se bez GEMINI_API_KEY."""
    if je_vinted_inzerat(inzerat):
        return True

    nazev_lower = (inzerat.nazev or "").lower()
    popis_lower = (inzerat.popis or "").lower()
    text = f"{nazev_lower} {popis_lower}"
    return any(kw.lower() in text for kw in KLICOVA_SLOVA_WHITELIST)


def je_vinted_inzerat(inzerat: Inzerat) -> bool:
    """Určí, zda inzerát pochází z portálu Vinted."""
    return (
        inzerat.id.startswith("vt_")
        or "vinted" in (inzerat.url or "").lower()
        or inzerat.datum == "VT"
    )


def rozbal_vinted_kompozitni_text(text: str) -> tuple[Optional[str], str, Optional[str]]:
    """Rozbalí kompozitní řetězec z Vintedu (název + metadata + ceny).

    Příklad:
        'PS5 Slim Digital, Značka: Sony, Stav: Velmi dobrý, 11299.00 Kč, 11899.00 Kč'
    Vrátí:
        (cena: '11299.00 Kč', cisty_nazev: 'PS5 Slim Digital', extra_popis: 'Značka: Sony, ...')
    """
    if not text:
        return None, text, None

    vzor_cena = re.compile(
        r"[,;\s]+(\d+(?:[\.,]\d+)?\s*(?:Kč|€|CZK|EUR))(?:\s*,\s*\d+(?:[\.,]\d+)?\s*(?:Kč|€|CZK|EUR))?[\s\.,;]*$",
        re.IGNORECASE,
    )
    m = vzor_cena.search(text)
    if not m:
        vzor_cena_kdekoli = re.compile(
            r"(?:Stav|Velikost|Condition|Size)[^,]*,\s*(\d+(?:[\.,]\d+)?\s*(?:Kč|€|CZK|EUR))",
            re.IGNORECASE,
        )
        m_kde = vzor_cena_kdekoli.search(text)
        if m_kde:
            cena = m_kde.group(1).strip()
            pred_cenou = text[:m_kde.start()].strip().rstrip(",;")
        else:
            return None, text, None
    else:
        cena = m.group(1).strip()
        pred_cenou = text[:m.start()].strip().rstrip(",;")

    vzor_meta = re.compile(
        r"[,;\s]+((?:Značka|Brand|Stav|Condition|Velikost|Size)\s*:.*)$",
        re.IGNORECASE,
    )
    m_meta = vzor_meta.search(pred_cenou)
    if m_meta:
        cisty_nazev = pred_cenou[:m_meta.start()].strip().rstrip(",;")
        extra_popis = m_meta.group(1).strip()
    else:
        cisty_nazev = pred_cenou
        extra_popis = None

    return cena, (cisty_nazev or text), extra_popis


def _zkontroluj_cenu(inzerat: Inzerat) -> tuple[bool, str]:
    """Zkontroluje cenu inzerátu. Vrátí (True, důvod) pokud má být ZAHAZOVÁN."""
    cena_text = inzerat.cena.strip() if inzerat.cena else ""

    if inzerat.nazev:
        cena_z_nazvu, cisty_nazev, extra_popis = rozbal_vinted_kompozitni_text(inzerat.nazev)
        if cisty_nazev and cisty_nazev != inzerat.nazev:
            inzerat.nazev = cisty_nazev
        if cena_z_nazvu and (
            not cena_text
            or cena_text.lower() in ("neuvedena", "")
            or not any(c.isdigit() for c in cena_text)
        ):
            cena_text = cena_z_nazvu
            inzerat.cena = cena_z_nazvu
        if extra_popis:
            inzerat.popis = f"{extra_popis} | {inzerat.popis}" if inzerat.popis else extra_popis

    if "," in cena_text and ("Kč" in cena_text or "€" in cena_text):
        casti = cena_text.split(",")
        if (
            len(casti) > 1
            and any(char.isdigit() for char in casti[1])
            and ("Kč" in casti[0] or "€" in casti[0])
        ):
            cena_text = casti[0].strip()
            inzerat.cena = cena_text

    if not cena_text or cena_text.lower() in ("neuvedena", ""):
        return True, "cena není uvedena"

    cena_lower = cena_text.lower()

    vb_vzory = ("vb", "verhandlung", "verhandelbar", "dohodou", "dohoda",
                 "v textu", "v dohovore", "zdarma")
    if any(vzor in cena_lower for vzor in vb_vzory):
        return True, f"cena bez čísla (VB/Dohodou): '{cena_text}'"

    je_eur = "€" in cena_text or "eur" in cena_lower
    je_czk = "kč" in cena_lower or "czk" in cena_lower or "kč" in cena_text

    if not je_eur and not je_czk:
        return True, f"neznámá měna nebo chybí měna: '{cena_text}'"

    cislo_match = re.search(r"([\d][\d\s\.\,]*)", cena_text)
    if not cislo_match:
        return True, f"neparsovatelna cena: '{cena_text}'"

    cislo_raw = cislo_match.group(1).strip()

    if je_czk:
        cislo_norm = re.sub(r"\s", "", cislo_raw)
        cislo_norm = re.sub(r"\.(\d{3})(?=[\.,]|$)", r"\1", cislo_norm)
        cislo_norm = cislo_norm.replace(",", ".")
        if cislo_norm.count(".") > 1:
            parts = cislo_norm.split(".")
            cislo_norm = "".join(parts[:-1]) + "." + parts[-1]
    else:
        cislo_norm = cislo_raw
        cislo_norm = re.sub(r"\s", "", cislo_norm)
        cislo_norm = re.sub(r"\.(\d{3})(?=[\.,]|$)", r"\1", cislo_norm)
        cislo_norm = cislo_norm.replace(",", ".")
        if cislo_norm.count(".") > 1:
            parts = cislo_norm.split(".")
            cislo_norm = "".join(parts[:-1]) + "." + parts[-1]

    try:
        hodnota = float(cislo_norm)
    except ValueError:
        return True, f"neparsovatelna hodnota: '{cislo_raw}' -> '{cislo_norm}'"

    if je_eur:
        if hodnota < MIN_CENA_EUR:
            return True, f"cena {hodnota:.0f} EUR < minimum {MIN_CENA_EUR} EUR"
        if hodnota > MAX_CENA_EUR:
            return True, f"cena {hodnota:.0f} EUR > maximum {MAX_CENA_EUR} EUR"
    if je_czk:
        if hodnota < MIN_CENA_CZK:
            return True, f"cena {hodnota:.0f} Kč < minimum {MIN_CENA_CZK} Kč"
        if hodnota > MAX_CENA_CZK:
            return True, f"cena {hodnota:.0f} Kč > maximum {MAX_CENA_CZK} Kč"

    return False, ""


# Alias pro zpětnou kompatibilitu s testy
_je_pod_minimalni_cenou = _zkontroluj_cenu


def _je_scam(inzerat: Inzerat) -> tuple[bool, str]:
    """Vrátí (True, duvod) pokud inzerát vypadá jako scam."""
    text = f"{inzerat.nazev} {inzerat.popis or ''}".lower()
    for vzor in SCAM_VZORY:
        if re.search(vzor, text, re.IGNORECASE):
            return True, f"scam vzor: '{vzor}'"
    return False, ""


def _je_google_translate(inzerat: Inzerat) -> bool:
    """Vrátí True, pokud URL nebo popis pochází z Google Translate."""
    text = f"{inzerat.url} {inzerat.popis or ''}".lower()
    return any(re.search(vzor, text, re.IGNORECASE) for vzor in GOOGLE_TRANSLATE_VZORY)


# ---------------------------------------------------------------------------
# Hlavní filtrovací funkce
# ---------------------------------------------------------------------------

def filtruj_inzerat(inzerat: Inzerat) -> VysledekFiltrace:
    """Aplikuje všechna pravidla na jeden inzerát PS5.

    Pořadí filtrů:
        1. Google Translate URL      — okamžité odmítnutí, bez API
        2. Scam detekce              — okamžité odmítnutí, bez API
        3. Cenový filtr (min + max)  — okamžité odmítnutí, bez API
        4a. LLM validace (Gemini)    — pokud GEMINI_API_KEY nastaven
            - is_valid: false        → odmítnout
            - is_valid: true         → přijmout, uložit clean_name/edition/is_slim do inzerátu
        4b. Keyword fallback         — pokud GEMINI_API_KEY NENÍ nastaven
            - negativní slova        → odmítnout
            - whitelist              → přijmout / odmítnout

    Returns:
        VysledekFiltrace s příznaky prijat/zamítnut a důvodem.
    """
    # 1. Google Translate
    if _je_google_translate(inzerat):
        return VysledekFiltrace(inzerat, False, "Google Translate URL")

    # 2. Scam detekce
    je_scam, duvod_scam = _je_scam(inzerat)
    if je_scam:
        return VysledekFiltrace(inzerat, False, duvod_scam)

    # 3. Kontrola ceny (min + max)
    zahodit_cena, duvod_cena = _zkontroluj_cenu(inzerat)
    if zahodit_cena:
        return VysledekFiltrace(inzerat, False, f"cena: {duvod_cena}")

    # 4a. LLM validace (Gemini 3.5 Flash Lite)
    llm = validuj_llm(inzerat)
    if llm is not None:
        # LLM odpověděl — použijeme jeho rozhodnutí
        if not llm.is_valid:
            logger.debug(
                "LLM zamítl [%s] '%s' — %s",
                inzerat.id, inzerat.nazev, llm.duvod,
            )
            return VysledekFiltrace(inzerat, False, f"LLM: {llm.duvod or 'není PS5 konzole'}")

        # Přijato — obohacujeme inzerát o standardizované hodnoty
        if llm.clean_name:
            inzerat.nazev = llm.clean_name
        # Uložíme edition a is_slim jako atributy (db.py je z parsuj_ps5_inzerat() přepíše
        # pouze pokud nejsou předány; zde přepíšeme přes přímé volání uloz_inzerat s parametry)
        # Pro propagaci do DB ukládáme do pomocných atributů (nedestruktivní)
        inzerat._llm_edition = llm.edition    # type: ignore[attr-defined]
        inzerat._llm_is_slim = llm.is_slim    # type: ignore[attr-defined]
        inzerat._llm_storage = llm.storage    # type: ignore[attr-defined]

        logger.debug(
            "LLM přijal [%s] '%s' — edice: %s, slim: %s, storage: %s",
            inzerat.id, inzerat.nazev, llm.edition, llm.is_slim, llm.storage,
        )
        return VysledekFiltrace(inzerat, True, "")

    # 4b. Keyword fallback (offline / bez API klíče)
    ma_negativni, neg_slovo = _obsahuje_negativni_slovo(inzerat)
    if ma_negativni:
        return VysledekFiltrace(inzerat, False, f"negativní slovo: '{neg_slovo}'")

    if not _obsahuje_klicove_slovo(inzerat):
        return VysledekFiltrace(inzerat, False, "neobsahuje klíčové slovo PS5")

    return VysledekFiltrace(inzerat, True, "")


def filtruj_seznam(inzeraty: list[Inzerat]) -> list[VysledekFiltrace]:
    """Aplikuje filtry na celý seznam inzerátů."""
    return [filtruj_inzerat(i) for i in inzeraty]


# ---------------------------------------------------------------------------
# Deduplikace (seen_ids.json)
# ---------------------------------------------------------------------------

def nacti_seen_ids(cesta: Path = DEFAULT_SEEN_IDS_PATH) -> set[str]:
    """Načte množinu již odeslaných ID z JSON souboru."""
    if not cesta.exists():
        return set()
    try:
        data = json.loads(cesta.read_text(encoding="utf-8"))
        return set(data.get("ids", []))
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Nelze načíst seen_ids (%s): %s", cesta, exc)
        return set()


def uloz_seen_ids(ids: set[str], cesta: Path = DEFAULT_SEEN_IDS_PATH) -> None:
    """Uloží množinu odeslaných ID do JSON souboru."""
    cesta.write_text(
        json.dumps({"ids": sorted(ids)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.debug("Uloženo %d seen IDs do %s", len(ids), cesta)


def odfiltruj_nove(
    inzeraty: list[Inzerat],
    seen_ids: set[str],
) -> list[Inzerat]:
    """Vrátí pouze inzeráty, jejichž ID dosud není v seen_ids."""
    return [i for i in inzeraty if i.id not in seen_ids]


def zpracuj_davku(
    inzeraty: list[Inzerat],
    seen_ids_cesta: Path = DEFAULT_SEEN_IDS_PATH,
) -> list[Inzerat]:
    """Kompletní pipeline: deduplikace + filtrace → nové relevantní inzeráty PS5.

    1. Načte seen_ids
    2. Odfiltruje již viděné
    3. Aplikuje filtry (scam, cena, LLM / keyword fallback, Google Translate)
    4. Vrátí seznam nových, relevantních inzerátů
    5. seen_ids NEUKLÁDÁ — to dělá volající po úspěšném odeslání notifikace

    Args:
        inzeraty:       Seznam inzerátů z parseru.
        seen_ids_cesta: Cesta k JSON souboru seen_ids.

    Returns:
        Seznam nových, relevantních inzerátů PS5 připravených k odeslání.
    """
    seen = nacti_seen_ids(seen_ids_cesta)
    nove = odfiltruj_nove(inzeraty, seen)
    logger.info("%d inzerátů celkem, %d nových (dosud neviděných).", len(inzeraty), len(nove))

    prijate: list[Inzerat] = []
    for vysledek in filtruj_seznam(nove):
        if vysledek.prijat:
            prijate.append(vysledek.inzerat)
        else:
            logger.debug(
                "Zamítnut [%s] %r — %s",
                vysledek.inzerat.id,
                vysledek.inzerat.nazev,
                vysledek.duvod_zamitnuti,
            )

    logger.info("%d inzerátů PS5 prošlo filtrem.", len(prijate))
    return prijate
