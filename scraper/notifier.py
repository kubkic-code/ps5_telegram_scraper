"""
notifier.py — Telegram notifikace — Garmin chytré hodinky
Python Agent | Odesílá nové inzeráty platcím klientům přes Telegram Bot API
"""

from __future__ import annotations

import logging
import os
import textwrap
from typing import Optional

import requests

from scraper import Inzerat

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Konfigurace — hodnoty se načítají z env proměnných (secrets)
# ---------------------------------------------------------------------------

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"

# Maximální délka Telegram zprávy (API limit: 4096 znaků)
MAX_ZPRAVA_DELKA = 4096
# Délka zkráceného popisu v notifikaci
POPIS_MAX_ZNAKY = 300

# Timeout pro HA webhook — krátký, ať nezdruhuje scraping smyčku
HA_WEBHOOK_TIMEOUT = 3


# ---------------------------------------------------------------------------
# Formátování zprávy
# ---------------------------------------------------------------------------

def _formatuj_cenu(cena: str) -> str:
    """Přidá emoji, pokud je cena textová."""
    if "textu" in cena.lower() or cena == "Neuvedena":
        return f"💬 {cena}"
    return f"💰 {cena}"


def formatuj_zpravu(inzerat: Inzerat) -> str:
    """Sestaví Telegram zprávu pro jeden inzerát.

    Výstup je formátovaný MarkdownV2 pro Telegram.

    Returns:
        Telegram zpráva jako řetězec (max MAX_ZPRAVA_DELKA znaků).
    """
    # Escape speciálních znaků pro Telegram MarkdownV2
    def esc(text: str) -> str:
        """Escapuje speciální znaky pro Telegram MarkdownV2."""
        special = r"_*[]()~`>#+-=|{}.!"
        for ch in special:
            text = text.replace(ch, f"\\{ch}")
        return text

    nazev = esc(inzerat.nazev)
    cena = esc(inzerat.cena)
    lokalita = esc(inzerat.lokalita)
    datum = esc(inzerat.datum)
    url = inzerat.url  # URL neescapujeme, vkládáme jako hyperlink

    popis = ""
    if inzerat.popis:
        zkraceny = textwrap.shorten(inzerat.popis, width=POPIS_MAX_ZNAKY, placeholder="…")
        popis = f"\n\n📄 {esc(zkraceny)}"

    # Určení zdroje podle ID prefixu
    if inzerat.id.startswith("vt_"):
        zdroj = "🛍️ *Nový inzerát na Vinted\\.cz\\!*"
    else:
        zdroj = "⌚ *Nový inzerát na Bazoši\\!*"

    zprava = (
        f"{zdroj}\n\n"
        f"📌 *{nazev}*\n"
        f"{_formatuj_cenu_esc(inzerat.cena, esc)}\n"
        f"📍 {lokalita}\n"
        f"📅 {datum}"
        f"{popis}\n\n"
        f"🔗 [Zobrazit inzerát]({url})"
    )

    # Oříznutí na Telegram limit
    if len(zprava) > MAX_ZPRAVA_DELKA:
        zprava = zprava[:MAX_ZPRAVA_DELKA - 3] + "\\.\\.\\."

    return zprava


def _formatuj_cenu_esc(cena: str, esc_fn) -> str:
    """Formátuje cenu s emoji a escapováním."""
    if "textu" in cena.lower() or cena == "Neuvedena":
        return f"💬 {esc_fn(cena)}"
    return f"💰 {esc_fn(cena)}"


# ---------------------------------------------------------------------------
# Home Assistant Webhook
# ---------------------------------------------------------------------------

def posli_ha_webhook(
    inzerat: Inzerat,
    webhook_url: str,
    session: requests.Session,
) -> None:
    """Odešle HTTP POST na Home Assistant Webhook.

    Posílá JSON payload s klíčovými údaji o inzerátu.
    Funkce je fire-and-forget — při chybě (HA offline, špatná URL, timeout)
    pouze zaloguje WARNING a vrátí se bez výjimky.

    Args:
        inzerat:     Inzerát, o kterém HA informujeme.
        webhook_url: URL z env proměnné HA_WEBHOOK_URL.
        session:     requests.Session pro HTTP volání.
    """
    if not webhook_url:
        return

    payload = {
        "id": inzerat.id,
        "nazev": inzerat.nazev,
        "cena": inzerat.cena,
        "lokalita": inzerat.lokalita,
        "url": inzerat.url,
        "zdroj": "vinted" if inzerat.id.startswith("vt_") else "bazos",
    }

    try:
        resp = session.post(webhook_url, json=payload, timeout=HA_WEBHOOK_TIMEOUT)
        resp.raise_for_status()
        logger.debug("[HA] Webhook odeslan (status %s) pro inzerat id=%s", resp.status_code, inzerat.id)
    except requests.RequestException as exc:
        logger.warning("[HA] Webhook selhal pro id=%s: %s", inzerat.id, exc)


# ---------------------------------------------------------------------------
# Telegram API
# ---------------------------------------------------------------------------

class TelegramNotifier:
    """Odesílá Telegram zprávy přes Bot API."""

    def __init__(
        self,
        token: str,
        chat_ids: list[str],
        session: Optional[requests.Session] = None,
        ha_webhook_url: str = "",
    ):
        """
        Args:
            token:          Telegram Bot token (z @BotFather).
            chat_ids:       Seznam chat ID příjemců (platící klienti).
            session:        Volitelná requests.Session (pro testování / mock).
            ha_webhook_url: URL Home Assistant Webhooku (volitelné).
                            Pokud prázdné, HA webhook se neposílá.
        """
        if not token:
            raise ValueError("Telegram token nesmí být prázdný.")
        if not chat_ids:
            raise ValueError("Seznam chat_ids nesmí být prázdný.")

        self.token = token
        self.chat_ids = chat_ids
        self._session = session or requests.Session()
        self.ha_webhook_url = ha_webhook_url.strip()

    def _url(self, method: str) -> str:
        return TELEGRAM_API_BASE.format(token=self.token, method=method)

    def posli_zpravu(self, chat_id: str, text: str) -> bool:
        """Odešle zprávu jednomu příjemci.

        Returns:
            True při úspěchu, False při chybě.
        """
        try:
            response = self._session.post(
                self._url("sendMessage"),
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": False,
                },
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                logger.error(
                    "Telegram API chyba pro chat_id=%s: %s",
                    chat_id,
                    data.get("description"),
                )
                return False
            logger.info("Notifikace odeslána na chat_id=%s", chat_id)
            return True
        except requests.RequestException as exc:
            logger.error("HTTP chyba při odesílání na chat_id=%s: %s", chat_id, exc)
            return False

    def _posli_ha_webhook(self, inzerat: Inzerat) -> None:
        """Interní helper — deleguje na modul-level funkci posli_ha_webhook."""
        posli_ha_webhook(inzerat, self.ha_webhook_url, self._session)

    def notifikuj_inzerat(self, inzerat: Inzerat) -> dict[str, bool]:
        """Odešle notifikaci o inzerátu všem klientům.

        Po úspěšném odeslání alespoň jedné Telegram zprávy spustí
        také HA webhook (pokud je nakonfigurován).

        Returns:
            Slovník {chat_id: uspech} pro každého příjemce.
        """
        zprava = formatuj_zpravu(inzerat)
        vysledky: dict[str, bool] = {}
        for chat_id in self.chat_ids:
            vysledky[chat_id] = self.posli_zpravu(chat_id, zprava)

        # HA webhook — voláme jednou, pokud alespoň jeden Telegram uspěl
        if any(vysledky.values()) and self.ha_webhook_url:
            self._posli_ha_webhook(inzerat)

        return vysledky

    def notifikuj_davku(self, inzeraty: list[Inzerat]) -> int:
        """Odešle notifikace pro všechny inzeráty v dávce.

        Returns:
            Počet úspěšně odeslaných zpráv (přes všechny chat_ids).
        """
        uspech = 0
        for i in inzeraty:
            vysledky = self.notifikuj_inzerat(i)
            uspech += sum(1 for v in vysledky.values() if v)
        return uspech


# ---------------------------------------------------------------------------
# Factory z env proměnných
# ---------------------------------------------------------------------------

def vytvor_notifier_z_env(
    session: Optional[requests.Session] = None,
) -> TelegramNotifier:
    """Vytvoří TelegramNotifier z env proměnných.

    Očekávané env proměnné:
        TELEGRAM_TOKEN    — bot token z @BotFather (povinné)
        TELEGRAM_CHAT_IDS — čárkou oddělené chat IDs klientů (povinné)
        HA_WEBHOOK_URL    — URL Home Assistant Webhooku (volitelné)

    Raises:
        RuntimeError: Pokud chybí povinné env proměnné.
    """
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    chat_ids_raw = os.getenv("TELEGRAM_CHAT_IDS", "").strip()
    ha_webhook_url = os.getenv("HA_WEBHOOK_URL", "").strip()

    if not token:
        raise RuntimeError(
            "Env proměnná TELEGRAM_TOKEN není nastavena. "
            "Nastav ji před spuštěním."
        )
    if not chat_ids_raw:
        raise RuntimeError(
            "Env proměnná TELEGRAM_CHAT_IDS není nastavena. "
            "Nastav ji jako čárkou oddělené chat IDs."
        )

    chat_ids = [cid.strip() for cid in chat_ids_raw.split(",") if cid.strip()]
    return TelegramNotifier(
        token=token,
        chat_ids=chat_ids,
        session=session,
        ha_webhook_url=ha_webhook_url,
    )
