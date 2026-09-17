"""
test_tracker.py — Unit testy pro Sales Tracker (modul tracker.py)
Python Agent | Mockování HTTP odpovědí, žádné volání reálného Bazoše/Vinted
"""

from __future__ import annotations

import datetime
import threading
import unittest
from unittest.mock import MagicMock, patch

from db import init_db, nacti_inzerat_dle_item_id, uloz_inzerat, ziskej_pripojeni
from scraper import Inzerat
from tracker import (
    INTERVAL_KONTROLY_SEKUND,
    start_tracker_thread,
    vyhodnot_stav_inzeratu,
    zkontroluj_inzerat,
    zkontroluj_inzeraty,
)


class TestVyhodnotStavInzeratu(unittest.TestCase):
    """Testy detekční logiky prodeje podle portálu, status kódu a obsahu."""

    # --- Bazoš ---

    def test_bazos_404_je_prodan(self):
        self.assertTrue(vyhodnot_stav_inzeratu("bazos", 404, ""))

    def test_bazos_smazan_text_je_prodan(self):
        text = "Omlouváme se, ale inzerát byl smazán uživatelem."
        self.assertTrue(vyhodnot_stav_inzeratu("bazos", 200, text))

    def test_bazos_smazan_bez_diakritiky_je_prodan(self):
        text = "Inzerat byl smazan."
        self.assertTrue(vyhodnot_stav_inzeratu("bazos", 200, text))

    def test_bazos_neexistuje_text_je_prodan(self):
        text = "Tento inzerát již neexistuje."
        self.assertTrue(vyhodnot_stav_inzeratu("bazos", 200, text))

    def test_bazos_chyba_text_je_prodan(self):
        text = "Chyba: požadovaný záznam nebyl nalezen."
        self.assertTrue(vyhodnot_stav_inzeratu("bazos", 200, text))

    def test_bazos_aktivni_inzerat_neni_prodan(self):
        text = "<html><body><h1>PlayStation 5</h1><p>Prodám zánovní konzoli.</p></body></html>"
        self.assertFalse(vyhodnot_stav_inzeratu("bazos", 200, text))

    # --- Vinted ---

    def test_vinted_404_je_prodan(self):
        self.assertTrue(vyhodnot_stav_inzeratu("vinted", 404, ""))

    def test_vinted_presmerovani_status_code_je_prodan(self):
        self.assertTrue(vyhodnot_stav_inzeratu("vinted", 302, "", is_redirect=True))
        self.assertTrue(vyhodnot_stav_inzeratu("vinted", 301, ""))

    def test_vinted_presmerovani_v_historii_je_prodan(self):
        history_mock = [MagicMock(status_code=302)]
        self.assertTrue(
            vyhodnot_stav_inzeratu("vinted", 200, "homepage", history=history_mock)
        )

    def test_vinted_aktivni_inzerat_neni_prodan(self):
        text = "<html><body><h1>PS5 Slim Digital</h1></body></html>"
        self.assertFalse(
            vyhodnot_stav_inzeratu("vinted", 200, text, is_redirect=False, history=[])
        )


class TestZkontrolujInzerat(unittest.TestCase):
    """Testy HTTP kontroly jednoho inzerátu přes mockovanou session."""

    def test_aktivni_inzerat_vraci_false(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Sony PS5 konzole v top stavu"
        mock_resp.history = []

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        inzerat = {
            "db_id": 1,
            "portal": "bazos",
            "url": "https://pc.bazos.cz/inzerat/1/ps5.php",
        }

        vysledek = zkontroluj_inzerat(inzerat, session=mock_session, pauza=False)
        self.assertFalse(vysledek)

    def test_bazos_smazany_vraci_true(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "Inzerát byl smazán"
        mock_resp.history = []

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        inzerat = {
            "db_id": 2,
            "portal": "bazos",
            "url": "https://pc.bazos.cz/inzerat/2/ps5.php",
        }

        vysledek = zkontroluj_inzerat(inzerat, session=mock_session, pauza=False)
        self.assertTrue(vysledek)

    def test_vinted_404_vraci_true(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_resp.history = []

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        inzerat = {
            "db_id": 3,
            "portal": "vinted",
            "url": "https://www.vinted.cz/items/3-ps5",
        }

        vysledek = zkontroluj_inzerat(inzerat, session=mock_session, pauza=False)
        self.assertTrue(vysledek)

    def test_sitova_chyba_neoznaci_jako_prodan(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("Connection timed out")

        inzerat = {
            "db_id": 4,
            "portal": "bazos",
            "url": "https://pc.bazos.cz/inzerat/4/ps5.php",
        }

        # Při výpadku sítě nesmíme chybně označit inzerát jako prodaný
        vysledek = zkontroluj_inzerat(inzerat, session=mock_session, pauza=False)
        self.assertFalse(vysledek)


class TestZkontrolujInzeratyDavka(unittest.TestCase):
    """Testy hromadné kontroly aktivních inzerátů a aktualizace DB."""

    def setUp(self):
        self.conn = ziskej_pripojeni(":memory:")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_zkontroluj_inzeraty_aktualizuje_db(self):
        # 1: Aktivní Bazoš (zůstane active)
        uloz_inzerat(
            Inzerat("101", "PlayStation 5 Disk Edition", "https://pc.bazos.cz/101", "8000 Kč", "Praha", "6.9."),
            db_conn=self.conn,
            status="active",
        )
        # 2: Smazaný Bazoš (stane se sold)
        uloz_inzerat(
            Inzerat("102", "PS5 Slim Digital", "https://pc.bazos.cz/102", "10000 Kč", "Brno", "6.9."),
            db_conn=self.conn,
            status="active",
        )
        # 3: Přesměrovaný Vinted (stane se sold)
        uloz_inzerat(
            Inzerat("vt_103", "Sony PlayStation 5", "https://vinted.cz/items/103", "5000 Kč", "Ostrava", "VT"),
            db_conn=self.conn,
            status="active",
        )

        def mock_get(url, **kwargs):
            resp = MagicMock()
            if "101" in url:
                resp.status_code = 200
                resp.text = "Inzerát je stále platný a aktivní"
                resp.history = []
            elif "102" in url:
                resp.status_code = 200
                resp.text = "Inzerát byl smazán"
                resp.history = []
            elif "103" in url:
                resp.status_code = 200
                resp.text = "Přesměrováno na katalog"
                resp.history = [MagicMock(status_code=302)]
            return resp

        mock_session = MagicMock()
        mock_session.get.side_effect = mock_get

        pocet_prodanych = zkontroluj_inzeraty(
            db_conn=self.conn, session=mock_session, pauza_mezi_dotazy=0.0
        )

        self.assertEqual(pocet_prodanych, 2)

        # Kontrola v DB
        inz101 = nacti_inzerat_dle_item_id("101", db_conn=self.conn)
        inz102 = nacti_inzerat_dle_item_id("102", db_conn=self.conn)
        inz103 = nacti_inzerat_dle_item_id("vt_103", db_conn=self.conn)

        self.assertEqual(inz101["status"], "active")
        self.assertIsNone(inz101["sold_date"])

        self.assertEqual(inz102["status"], "sold")
        self.assertIsNotNone(inz102["sold_date"])

        self.assertEqual(inz103["status"], "sold")
        self.assertIsNotNone(inz103["sold_date"])


class TestStartTrackerThread(unittest.TestCase):
    """Testy startování a řízení vlákna trackeru."""

    def test_interval_je_12_hodin(self):
        self.assertEqual(INTERVAL_KONTROLY_SEKUND, 43200)

    def test_start_tracker_thread_je_daemon(self):
        stop_event = threading.Event()
        stop_event.set()  # Vlákno se okamžitě ukončí

        thread = start_tracker_thread(
            db_path=":memory:",
            interval_sekund=43200,
            stop_event=stop_event,
        )

        self.assertTrue(thread.daemon, "Tracker thread musí mít daemon=True.")
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main(verbosity=2)
