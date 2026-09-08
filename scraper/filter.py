"""
filter.py — Filtrace a deduplikace inzerátů — Garmin chytré hodinky
Python Agent | Klíčová slova, anti-scam, anti-Google Translate, seen_ids
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import NamedTuple

from scraper import Inzerat

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfigurace filtrů
# ---------------------------------------------------------------------------

# Inzerát MUSÍ obsahovat alespoň jedno z těchto klíčových slov (case-insensitive)
# Garmin modely a obecné výrazy pro chytré hodinky
KLICOVA_SLOVA_WHITELIST: list[str] = [
    # --- Hlavní značka ---
    "garmin",
    # --- Populární série Garmin ---
    "fenix",
    "forerunner",
    "venu",
    "epix",
    "instinct",
    "tactix",
    "vivoactive",
    "vivomove",
    "vivosport",
    "vivofit",
    "marq",
    "quatix",
    "enduro",
    "lily",
    "approach",   # Garmin golf serie
    # --- Obecné výrazy pro chytré hodinky (pokud i bez Garmin) ---
    "chytré hodinky",
    "smart watch",
    "smartwatch",
    "sportovní hodinky",
    "gps hodinky",
]

# Inzerát bude ZAMÍTNUT, pokud název nebo popis obsahuje tato negativní slova
# (case-insensitive) — chrání před příslušenstvím, balastem a scamem
NEGATIVNI_SLOVA: list[str] = [
    # --- Příslušenství / ne samotné hodinky ---
    "kryt",
    "case",
    "pouzdro",
    "nabíjecí dok",
    "nabijeci dok",
    "charging cable",
    "charger",
    "dobíječka",
    "dobijecka",
    # --- Rozbité / nefunkční / poškozené ---
    "rozbité",
    "rozbita",
    "nefunkční",
    "nefunkcni",
    "na díly",
    "na součástky",
    "vryp",
    "rýha",
    "ryha",
    "prasklý",
    "praskly",
    # --- Pronájmy (neprodává se) ---
    "pronájem",
    "půjčím",
    "pujcim",
    "k pronájmu",
    # --- Hledám / poptávka (ne nabídka) ---
    "hledám",
    "hledam",
    "sháním",
    "shàním",
    "koupím",
    "koupim",
    "wanted",
    "gesuch",
    # --- Výměny / směny (blokuje 'vyměním za Garmin' apod.) ---
    "vyměním",
    "vymenim",
    "výměna",
    "vymena",
    # --- Konkurenční značky (blokuje 'Apple Watch vyměním za Garmin' apod.) ---
    "apple watch",
    "samsung",
    "galaxy watch",
    "huawei",
    # --- Krabičkování / nerelevantní ---
    "figurka",
    "hračka",
    "tričko",
    "mikina",
    "oblečení",
]

# Minimální a maximální cena
MIN_CENA_CZK = 800      # Kč  — zachytí i levnější Forerunnery a Venu (např. starší generace)
MAX_CENA_CZK = 20_000   # Kč  — nad tím jsou sběratelské kousky, mimo zájem
MIN_CENA_EUR = 30       # EUR — odpovídá cca 800 Kč
MAX_CENA_EUR = 900    # EUR

SCAM_VZORY: list[str] = [
    r"whatsapp",
    r"telegram\s+@",          # podezřelé Telegram kontakty v textu inzerátu
    r"western\s+union",
    r"paypal",
    r"záloha.*zahrani",       # záloha do zahraničí
    r"zaslat\s+pen[íi]ze",
    r"advance\s+payment",
    r"wire\s+transfer",
    r"escrow",
]

# Inzerát bude ZAMÍTNUT, pokud URL obsahuje Google Translate překlad
GOOGLE_TRANSLATE_VZORY: list[str] = [
    r"translate\.google",
    r"translate\.googleusercontent",
    r"&hl=",                   # Google Translate query param
]

# Výchozí umístění souboru se zaviděnými ID
DEFAULT_SEEN_IDS_PATH = Path(__file__).parent / "seen_ids.json"

# ---------------------------------------------------------------------------
# Detekce Garmin modelů a portálu
# ---------------------------------------------------------------------------

GARMIN_MODEL_PATTERNS: list[tuple[re.Pattern, str]] = [
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
    (re.compile(r"\bvivosport\b", re.I), "Vivosport"),
    (re.compile(r"\bvivofit\b", re.I), "Vivofit"),
    (re.compile(r"\bmarq\b", re.I), "Marq"),
    (re.compile(r"\bquatix\b", re.I), "Quatix"),
    (re.compile(r"\bapproach\b", re.I), "Approach"),
    (re.compile(r"\blily\b", re.I), "Lily"),
    (re.compile(r"\bdescent\b", re.I), "Descent"),
    (re.compile(r"\bswim\b", re.I), "Swim"),
]


def _najdi_model_v_textu(text: Optional[str]) -> Optional[str]:
    """Pomocná funkce pro vyhledání modelu v textovém řetězci."""
    if not text:
        return None
    for pattern, model_name in GARMIN_MODEL_PATTERNS:
        if pattern.search(text):
            return model_name
    return None


def detekuj_model(inzerat: Inzerat) -> Optional[str]:
    """Vyhledá model Garmin hodinek nejprve v názvu inzerátu,
    a pokud není nalezen, prohledá tělo inzerátu (popis).

    Returns:
        Rozpoznaný název modelu (např. 'Fenix 7', 'Forerunner 245', 'Venu 2')
        nebo None, pokud žádný specifický model nebyl nalezen.
    """
    # 1. Hledání v názvu
    model = _najdi_model_v_textu(inzerat.nazev)
    if model:
        return model

    # 2. Hledání v těle inzerátu (popis)
    if inzerat.popis:
        model = _najdi_model_v_textu(inzerat.popis)
        if model:
            return model

    return None


def je_vinted_inzerat(inzerat: Inzerat) -> bool:
    """Určí, zda inzerát pochází z portálu Vinted (prefix 'vt_', URL nebo datum 'VT')."""
    return (
        inzerat.id.startswith("vt_")
        or "vinted" in (inzerat.url or "").lower()
        or inzerat.datum == "VT"
    )


# ---------------------------------------------------------------------------
# Výsledek filtrace
# ---------------------------------------------------------------------------

class VysledekFiltrace(NamedTuple):
    """Výsledek rozhodnutí filtru pro jeden inzerát."""
    inzerat: Inzerat
    prijat: bool
    duvod_zamitnuti: str  # prázdný řetězec = přijat
    model: Optional[str] = None


# ---------------------------------------------------------------------------
# Filtrovací funkce
# ---------------------------------------------------------------------------

def _obsahuje_negativni_slovo(inzerat: Inzerat) -> tuple[bool, str]:
    """Vrátí (True, slovo) pokud inzerát obsahuje negativní klíčové slovo."""
    text = f"{inzerat.nazev} {inzerat.popis or ''}".lower()
    for slovo in NEGATIVNI_SLOVA:
        if slovo.lower() in text:
            return True, slovo
    return False, ""


def rozbal_vinted_kompozitni_text(text: str) -> tuple[Optional[str], str, Optional[str]]:
    """Rozbalí kompozitní řetězec z Vintedu, kde jsou do jednoho textu spojené:
    název, metadata (Značka, Stav, Velikost) a ceny na konci.

    Příklad:
        'Garmin Forerunner 570, Značka: Garmin, Stav: Velmi dobrý, Velikost: 47 mm a více, 9299.00 Kč, 9781.95 Kč'
    Vrátí:
        (cena: '9299.00 Kč', cisty_nazev: 'Garmin Forerunner 570', extra_popis: 'Značka: Garmin, Stav: Velmi dobrý, Velikost: 47 mm a více')
    """
    if not text:
        return None, text, None

    # Hledáme cenu / dvojici cen na konci řetězce
    vzor_cena = re.compile(
        r"[,;\s]+(\d+(?:[\.,]\d+)?\s*(?:Kč|€|CZK|EUR))(?:\s*,\s*\d+(?:[\.,]\d+)?\s*(?:Kč|€|CZK|EUR))?[\s\.,;]*$",
        re.IGNORECASE,
    )
    m = vzor_cena.search(text)
    if not m:
        # Zkusíme také hledat cenu kdekoli za 'Stav:' nebo 'Velikost:'
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

    # Oddělíme čistý název a metadata (Značka, Stav, Velikost atd.)
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
    """Zkontroluje cenu inzerátu. Vrátí (True, důvod) pokud má být ZAHAZOVÁN.

    Pravidla:
    - Cena musí být uvedená — VB, Dohodou, prázdná, neparsovatelné → ZAHODIT
    - Cena musí být >= MIN_CENA a <= MAX_CENA (v Kč nebo EUR)
    - Cena v neznámé měně → ZAHODIT

    Parsování českých cen:
    - '5 000 Kč' → 5000
    - '5.000 Kč' → 5000

    Parsování EUR cen:
    - '200 €' → 200
    - '1.500,50 €' → 1500.50
    """
    cena_text = inzerat.cena.strip() if inzerat.cena else ""

    # Pokud inzerat.cena není uvedena nebo je "Neuvedena" nebo neobsahuje číslice,
    # anebo inzerat.nazev obsahuje kompozitní Vinted řetězec, vytáhneme cenu a očistíme název:
    if inzerat.nazev:
        cena_z_nazvu, cisty_nazev, extra_popis = rozbal_vinted_kompozitni_text(inzerat.nazev)
        if cisty_nazev and cisty_nazev != inzerat.nazev:
            inzerat.nazev = cisty_nazev
        if cena_z_nazvu and (not cena_text or cena_text.lower() in ("neuvedena", "") or not any(c.isdigit() for c in cena_text)):
            cena_text = cena_z_nazvu
            inzerat.cena = cena_z_nazvu
        if extra_popis:
            inzerat.popis = f"{extra_popis} | {inzerat.popis}" if inzerat.popis else extra_popis

    # Ošetření Vinted formátu: '5108.24 Kč, 5381.65 Kč' -> vezmeme jen to první
    if "," in cena_text and ("Kč" in cena_text or "€" in cena_text):
        # Rozdělíme podle čárky, ale jen pokud jsou za čárkou další čísla (abychom nerozbili např. 1.500,50 EUR)
        casti = cena_text.split(",")
        if len(casti) > 1 and any(char.isdigit() for char in casti[1]) and ("Kč" in casti[0] or "€" in casti[0]):
            cena_text = casti[0].strip()
            inzerat.cena = cena_text

    # --- Prázdná nebo explicitně neuvedená cena → ZAHODIT ---
    if not cena_text or cena_text.lower() in ("neuvedena", ""):
        return True, "cena není uvedena"

    cena_lower = cena_text.lower()

    # --- VB / Dohodou → ZAHODIT ---
    vb_vzory = ("vb", "verhandlung", "verhandelbar", "dohodou", "dohoda",
                 "v textu", "v dohovore", "zdarma")
    if any(vzor in cena_lower for vzor in vb_vzory):
        return True, f"cena bez čísla (VB/Dohodou): '{cena_text}'"

    # --- Detekce měny ---
    je_eur = "€" in cena_text or "eur" in cena_lower
    je_czk = "kč" in cena_lower or "czk" in cena_lower or "kč" in cena_text

    if not je_eur and not je_czk:
        return True, f"neznámá měna nebo chybí měna: '{cena_text}'"

    # --- Parsování čísla ---
    cislo_match = re.search(r"([\d][\d\s\.\,]*)", cena_text)
    if not cislo_match:
        return True, f"neparsovatelna cena: '{cena_text}'"

    cislo_raw = cislo_match.group(1).strip()

    if je_czk:
        # CZK formát: '5 000' nebo '5.000' (Bazoš oddělovač tisíců),
        # ale i Vinted formát s desetinnou tečkou: '4000.00' nebo '10227.85'
        cislo_norm = re.sub(r"\s", "", cislo_raw)
        cislo_norm = re.sub(r"\.(\d{3})(?=[\.,]|$)", r"\1", cislo_norm)
        cislo_norm = cislo_norm.replace(",", ".")
        if cislo_norm.count(".") > 1:
            parts = cislo_norm.split(".")
            cislo_norm = "".join(parts[:-1]) + "." + parts[-1]
    else:
        # EUR formát: '10.000' = 10000, '1.500,50' = 1500.50, '200' = 200
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

    # --- Porovnání s minimem a maximem ---
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


def _obsahuje_klicove_slovo(inzerat: Inzerat) -> bool:
    """Vrátí True, pokud inzerát splňuje kritéria pro Garmin chytré hodinky.

    Pravidla uvolněné filtrace:
    1. Vinted inzeráty (prefix vt_, vinted URL, datum VT) pocházejí z cíleného hledání
       Garmin hodinek → NESMÍ být zahozeny jen proto, že v názvu chybí konkrétní model.
    2. Generické slovo 'Garmin' v názvu (nebo popisu) stačí pro přijetí, i když v názvu
       chybí konkrétní model (Fenix, Epix atd.).
    3. Pokud název neobsahuje konkrétní model, filtr prohledá tělo inzerátu (description / popis),
       zda se model neskrývá tam.
    4. Běžná klíčová slova z whitelistu (modely Garmin, obecné výrazy pro chytré hodinky).
    """
    # 1. Vinted inzerát → uvolněný filtr, nesmí být zahozen kvůli chybějícímu modelu v názvu
    if je_vinted_inzerat(inzerat):
        return True

    nazev_lower = (inzerat.nazev or "").lower()
    popis_lower = (inzerat.popis or "").lower()

    # 2. Generické slovo 'garmin' v názvu nebo popisu
    if "garmin" in nazev_lower or "garmin" in popis_lower:
        return True

    # 3. Prohledání těla inzerátu (popis) a názvu na konkrétní model Garmin
    if detekuj_model(inzerat) is not None:
        return True

    # 4. Standardní whitelist (klíčová slova v názvu i popisu)
    text = f"{nazev_lower} {popis_lower}"
    return any(kw.lower() in text for kw in KLICOVA_SLOVA_WHITELIST)


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


def filtruj_inzerat(inzerat: Inzerat) -> VysledekFiltrace:
    """Aplikuje všechna pravidla na jeden inzerát.

    Pořadí filtrů (od nejrychlejsích k nejpomalejsím):
    1. Google Translate URL
    2. Scam detekce
    3. Cenový filtr (min + max)
    4. Negativní klíčová slova (příslušenství, balast)
    5. Whitelist klíčových slov (Garmin modely)

    Returns:
        VysledekFiltrace s příznaky prijat/zamítnut a důvodem.
    """
    # 1. Google Translate
    if _je_google_translate(inzerat):
        return VysledekFiltrace(inzerat, False, "Google Translate URL")

    # 2. Scam detekce
    je_scam, duvod = _je_scam(inzerat)
    if je_scam:
        return VysledekFiltrace(inzerat, False, duvod)

    # 3. Kontrola ceny (min + max)
    zahodit_cena, duvod_cena = _zkontroluj_cenu(inzerat)
    if zahodit_cena:
        return VysledekFiltrace(inzerat, False, f"cena: {duvod_cena}")

    # 4. Negativní klíčová slova
    ma_negativni, neg_slovo = _obsahuje_negativni_slovo(inzerat)
    if ma_negativni:
        return VysledekFiltrace(inzerat, False, f"negativní slovo: '{neg_slovo}'")

    # 5. Whitelist klíčových slov (s uvolněním pro Vinted / generické Garmin / model v těle)
    if not _obsahuje_klicove_slovo(inzerat):
        return VysledekFiltrace(inzerat, False, "neobsahuje klíčové slovo")

    model = detekuj_model(inzerat)
    return VysledekFiltrace(inzerat, True, "", model=model)


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
    """Kompletní pipeline: deduplikace + filtrace → nové relevantní inzeráty.

    1. Načte seen_ids
    2. Odfiltruje již viděné
    3. Aplikuje filtry (scam, klíčová slova, Google Translate, cena)
    4. Vrátí seznam nových, relevantních inzerátů
    5. seen_ids NEUKLÁDÁ — to dělá volající po úspěšném odeslání notifikace

    Args:
        inzeraty:       Seznam inzerátů z parseru.
        seen_ids_cesta: Cesta k JSON souboru seen_ids.

    Returns:
        Seznam nových, relevantních inzerátů připravených k odeslání.
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

    logger.info("%d inzerátů prošlo filtrem.", len(prijate))
    return prijate
