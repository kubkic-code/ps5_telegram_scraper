"""
test_notifier.py — Unit testy pro notifier.py — Garmin chytré hodinky
DevOps Agent | Vše mockováno — žádný skutečný Telegram request
"""

import pathlib
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from scraper import Inzerat
from notifier import (
    TelegramNotifier,
    formatuj_zpravu,
    posli_ha_webhook,
    vytvor_notifier_z_env,
    MAX_ZPRAVA_DELKA,
    HA_WEBHOOK_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Pomocná továrna
# ---------------------------------------------------------------------------

def inzerat(
    id: str = "100",
    nazev: str = "Garmin Fenix 7 Sapphire",
    url: str = "https://www.bazos.cz/inzerat/100/garmin-fenix-7.php",
    cena: str = "8 500 Kč",
    lokalita: str = "Praha",
    datum: str = "5.9. 2026",
    popis: str = "Garmin Fenix 7 Sapphire Solar, zánovní, málo mth.",
) -> Inzerat:
    return Inzerat(id=id, nazev=nazev, url=url, cena=cena,
                   lokalita=lokalita, datum=datum, popis=popis)


def vinted_inzerat(
    id: str = "vt_4567890001",
    nazev: str = "Garmin Forerunner 945",
    cena: str = "5 200 Kč",
) -> Inzerat:
    return Inzerat(
        id=id,
        nazev=nazev,
        url=f"https://www.vinted.cz/items/{id[3:]}-garmin-forerunner",
        cena=cena,
        lokalita="Brno",
        datum="VT",
        popis="Perfektní stav, kompletní balení.",
    )


def mock_session_ok() -> MagicMock:
    """Vrátí mock session, která simuluje úspěšný Telegram API response."""
    session = MagicMock()
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.json.return_value = {"ok": True, "result": {"message_id": 42}}
    session.post.return_value = response
    return session


def mock_session_err() -> MagicMock:
    """Vrátí mock session, která simuluje Telegram API chybu."""
    session = MagicMock()
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"ok": False, "description": "Bad Request"}
    session.post.return_value = response
    return session


# ---------------------------------------------------------------------------
# Testy formatuj_zpravu
# ---------------------------------------------------------------------------

class TestFormatujZpravu(unittest.TestCase):

    def test_obsahuje_nazev(self):
        i = inzerat(nazev="Garmin Fenix 7 Sapphire")
        zprava = formatuj_zpravu(i)
        self.assertIn("Garmin Fenix 7 Sapphire", zprava)

    def test_vinted_zdroj_ma_spravnou_hlavicku(self):
        """Inzerat z Vinted (vt_ prefix) musi mit Vinted hlavicku."""
        i = vinted_inzerat()
        zprava = formatuj_zpravu(i)
        self.assertIn("Vinted", zprava)
        self.assertIn("🛍️", zprava)

    def test_bazos_zdroj_ma_spravnou_hlavicku(self):
        """Inzerat z Bazose (bez vt_ prefixu) musi mit Bazos hlavicku s hodinkama."""
        i = inzerat()
        zprava = formatuj_zpravu(i)
        self.assertIn("Bazoši", zprava)
        self.assertIn("⌚", zprava)

    def test_obsahuje_url(self):
        i = inzerat()
        zprava = formatuj_zpravu(i)
        self.assertIn(i.url, zprava)

    def test_obsahuje_lokalitu(self):
        i = inzerat(lokalita="Brno")
        zprava = formatuj_zpravu(i)
        self.assertIn("Brno", zprava)

    def test_obsahuje_datum(self):
        i = inzerat(datum="5.9. 2026")
        zprava = formatuj_zpravu(i)
        self.assertIn("5", zprava)

    def test_cena_kc(self):
        i = inzerat(cena="8 500 Kč")
        zprava = formatuj_zpravu(i)
        self.assertIn("8 500", zprava)

    def test_cena_v_textu(self):
        i = inzerat(cena="V textu")
        zprava = formatuj_zpravu(i)
        self.assertIn("💬", zprava)

    def test_cena_kc_emoji(self):
        i = inzerat(cena="8 500 Kč")
        zprava = formatuj_zpravu(i)
        self.assertIn("💰", zprava)

    def test_max_delka(self):
        """Zpráva nepřekročí Telegram limit."""
        i = inzerat(popis="x" * 5000)
        zprava = formatuj_zpravu(i)
        self.assertLessEqual(len(zprava), MAX_ZPRAVA_DELKA)

    def test_popis_none(self):
        """Zpráva funguje bez popisu."""
        i = inzerat(popis=None)
        zprava = formatuj_zpravu(i)
        self.assertIsInstance(zprava, str)
        self.assertGreater(len(zprava), 0)

    def test_vraci_retezec(self):
        self.assertIsInstance(formatuj_zpravu(inzerat()), str)


# ---------------------------------------------------------------------------
# Testy TelegramNotifier
# ---------------------------------------------------------------------------

class TestTelegramNotifier(unittest.TestCase):

    def test_init_prazdny_token_vyvolava_chybu(self):
        with self.assertRaises(ValueError):
            TelegramNotifier(token="", chat_ids=["123"])

    def test_init_prazdne_chat_ids_vyvolava_chybu(self):
        with self.assertRaises(ValueError):
            TelegramNotifier(token="abc:xyz", chat_ids=[])

    def test_posli_zpravu_uspech(self):
        session = mock_session_ok()
        notifier = TelegramNotifier("token:test", ["123456"], session)
        result = notifier.posli_zpravu("123456", "Test zpráva")
        self.assertTrue(result)
        session.post.assert_called_once()

    def test_posli_zpravu_api_chyba(self):
        session = mock_session_err()
        notifier = TelegramNotifier("token:test", ["123456"], session)
        result = notifier.posli_zpravu("123456", "Test")
        self.assertFalse(result)

    def test_posli_zpravu_http_exception(self):
        import requests as req
        session = MagicMock()
        session.post.side_effect = req.RequestException("Timeout")
        notifier = TelegramNotifier("token:test", ["123456"], session)
        result = notifier.posli_zpravu("123456", "Test")
        self.assertFalse(result)

    def test_notifikuj_inzerat_vsem_klientum(self):
        session = mock_session_ok()
        notifier = TelegramNotifier("token:test", ["111", "222", "333"], session)
        vysledky = notifier.notifikuj_inzerat(inzerat())
        self.assertEqual(len(vysledky), 3)
        self.assertTrue(all(vysledky.values()))
        # 3 Telegram posty (HA webhook neni nakonfigurovany)
        self.assertEqual(session.post.call_count, 3)

    def test_notifikuj_davku_pocet(self):
        session = mock_session_ok()
        notifier = TelegramNotifier("token:test", ["111", "222"], session)
        inzeraty = [inzerat("1"), inzerat("2"), inzerat("3")]
        pocet = notifier.notifikuj_davku(inzeraty)
        # 3 inzeráty × 2 chat_ids = 6 úspěšných
        self.assertEqual(pocet, 6)

    def test_notifikuj_prazdnou_davku(self):
        session = mock_session_ok()
        notifier = TelegramNotifier("token:test", ["111"], session)
        pocet = notifier.notifikuj_davku([])
        self.assertEqual(pocet, 0)
        session.post.assert_not_called()

    def test_zprava_obsahuje_parse_mode(self):
        """API call musí mít parse_mode=MarkdownV2."""
        session = mock_session_ok()
        notifier = TelegramNotifier("token:test", ["111"], session)
        notifier.posli_zpravu("111", "Test")
        call_kwargs = session.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1]
        self.assertEqual(payload.get("parse_mode"), "MarkdownV2")


# ---------------------------------------------------------------------------
# Testy vytvor_notifier_z_env
# ---------------------------------------------------------------------------

class TestVytvorNotifierZEnv(unittest.TestCase):

    def test_chybi_token_vyvolava_runtime_error(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                vytvor_notifier_z_env()
            self.assertIn("TELEGRAM_TOKEN", str(ctx.exception))

    def test_chybi_chat_ids_vyvolava_runtime_error(self):
        with patch.dict("os.environ", {"TELEGRAM_TOKEN": "abc:xyz"}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                vytvor_notifier_z_env()
            self.assertIn("TELEGRAM_CHAT_IDS", str(ctx.exception))

    def test_spravne_env_vraci_notifier(self):
        env = {
            "TELEGRAM_TOKEN": "123:abc",
            "TELEGRAM_CHAT_IDS": "111,222,333",
        }
        with patch.dict("os.environ", env, clear=True):
            notifier = vytvor_notifier_z_env()
        self.assertIsInstance(notifier, TelegramNotifier)
        self.assertEqual(notifier.chat_ids, ["111", "222", "333"])

    def test_chat_ids_mezery_ocisteny(self):
        env = {
            "TELEGRAM_TOKEN": "123:abc",
            "TELEGRAM_CHAT_IDS": " 111 , 222 , 333 ",
        }
        with patch.dict("os.environ", env, clear=True):
            notifier = vytvor_notifier_z_env()
        self.assertEqual(notifier.chat_ids, ["111", "222", "333"])

    def test_ha_webhook_url_z_env(self):
        """Pokud je HA_WEBHOOK_URL v env, notifier ji ma nastavenou."""
        env = {
            "TELEGRAM_TOKEN": "123:abc",
            "TELEGRAM_CHAT_IDS": "111",
            "HA_WEBHOOK_URL": "http://homeassistant.local:8123/api/webhook/garmin",
        }
        with patch.dict("os.environ", env, clear=True):
            notifier = vytvor_notifier_z_env()
        self.assertEqual(
            notifier.ha_webhook_url,
            "http://homeassistant.local:8123/api/webhook/garmin",
        )

    def test_ha_webhook_url_prazdna_kdyz_neni_v_env(self):
        """Kdyz HA_WEBHOOK_URL neni v env, notifier ma prazdny retezec."""
        env = {
            "TELEGRAM_TOKEN": "123:abc",
            "TELEGRAM_CHAT_IDS": "111",
        }
        with patch.dict("os.environ", env, clear=True):
            notifier = vytvor_notifier_z_env()
        self.assertEqual(notifier.ha_webhook_url, "")


# ---------------------------------------------------------------------------
# Testy posli_ha_webhook (modularni)
# ---------------------------------------------------------------------------

class TestHaWebhook(unittest.TestCase):

    def test_prazdna_url_nic_neposle(self):
        """Prazdna HA URL = zadny HTTP request."""
        session = MagicMock()
        posli_ha_webhook(inzerat(), "", session)
        session.post.assert_not_called()

    def test_uspesny_webhook_zaloguje_debug(self):
        """Uspesny POST na HA nevyhodi vyjimku."""
        session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = MagicMock()
        session.post.return_value = response

        posli_ha_webhook(inzerat(), "http://ha.local/webhook/garmin", session)
        session.post.assert_called_once()

    def test_webhook_pouziva_spravny_timeout(self):
        """POST musi mit timeout = HA_WEBHOOK_TIMEOUT (3 s)."""
        session = MagicMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        session.post.return_value = response

        posli_ha_webhook(inzerat(), "http://ha.local/webhook/garmin", session)
        _, call_kwargs = session.post.call_args
        self.assertEqual(call_kwargs.get("timeout"), HA_WEBHOOK_TIMEOUT)

    def test_webhook_json_payload_obsahuje_id(self):
        """Payload musi obsahovat id, nazev, cena, url, zdroj."""
        session = MagicMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        session.post.return_value = response
        i = inzerat(id="123", nazev="Garmin Fenix 7")

        posli_ha_webhook(i, "http://ha.local/webhook/garmin", session)
        _, call_kwargs = session.post.call_args
        payload = call_kwargs.get("json")
        self.assertEqual(payload["id"], "123")
        self.assertEqual(payload["nazev"], "Garmin Fenix 7")
        self.assertIn("cena", payload)
        self.assertIn("url", payload)
        self.assertIn("zdroj", payload)

    def test_webhook_zdroj_bazos(self):
        i = inzerat(id="12345")
        session = MagicMock()
        session.post.return_value.raise_for_status = MagicMock()
        posli_ha_webhook(i, "http://ha.local/webhook/g", session)
        _, call_kwargs = session.post.call_args
        self.assertEqual(call_kwargs["json"]["zdroj"], "bazos")

    def test_webhook_zdroj_vinted(self):
        i = vinted_inzerat()  # id zacina na vt_
        session = MagicMock()
        session.post.return_value.raise_for_status = MagicMock()
        posli_ha_webhook(i, "http://ha.local/webhook/g", session)
        _, call_kwargs = session.post.call_args
        self.assertEqual(call_kwargs["json"]["zdroj"], "vinted")

    def test_chyba_siti_je_pouze_warning(self):
        """RequestException nesmi probublat ven — jen WARNING log."""
        import requests as req
        session = MagicMock()
        session.post.side_effect = req.RequestException("HA offline")

        # Nesmí vyhodit výjimku
        posli_ha_webhook(inzerat(), "http://ha.local/webhook/garmin", session)

    def test_http_error_je_pouze_warning(self):
        """HTTP chyba (napr. 404) nesmi probublat."""
        import requests as req
        session = MagicMock()
        response = MagicMock()
        response.raise_for_status.side_effect = req.HTTPError("404")
        session.post.return_value = response

        posli_ha_webhook(inzerat(), "http://ha.local/webhook/garmin", session)


# ---------------------------------------------------------------------------
# Testy integrace HA webhoooku v TelegramNotifier.notifikuj_inzerat
# ---------------------------------------------------------------------------

class TestHaWebhookIntegrace(unittest.TestCase):

    def test_ha_webhook_volan_po_uspesnem_telegramu(self):
        """Kdyz Telegram uspeje a ha_webhook_url je nastaven, HA se zavola."""
        session = mock_session_ok()
        notifier = TelegramNotifier(
            "token:test", ["111"], session,
            ha_webhook_url="http://ha.local/webhook/garmin",
        )
        with patch("notifier.posli_ha_webhook") as mock_ha:
            notifier.notifikuj_inzerat(inzerat())
        mock_ha.assert_called_once()

    def test_ha_webhook_neni_volan_bez_url(self):
        """Kdyz ha_webhook_url je prazdny, posli_ha_webhook se nevola."""
        session = mock_session_ok()
        notifier = TelegramNotifier("token:test", ["111"], session, ha_webhook_url="")
        with patch("notifier.posli_ha_webhook") as mock_ha:
            notifier.notifikuj_inzerat(inzerat())
        mock_ha.assert_not_called()

    def test_ha_webhook_neni_volan_kdyz_telegram_selze(self):
        """Pokud vsechny Telegram posty selhaly, HA webhook se nevola."""
        session = mock_session_err()
        notifier = TelegramNotifier(
            "token:test", ["111"], session,
            ha_webhook_url="http://ha.local/webhook/garmin",
        )
        with patch("notifier.posli_ha_webhook") as mock_ha:
            notifier.notifikuj_inzerat(inzerat())
        mock_ha.assert_not_called()

    def test_ha_webhook_volan_jednou_i_pro_vice_chat_ids(self):
        """HA webhook se vola jednou, i kdyz je vic klientu."""
        session = mock_session_ok()
        notifier = TelegramNotifier(
            "token:test", ["111", "222", "333"], session,
            ha_webhook_url="http://ha.local/webhook/garmin",
        )
        with patch("notifier.posli_ha_webhook") as mock_ha:
            notifier.notifikuj_inzerat(inzerat())
        mock_ha.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
