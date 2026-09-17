"""
test_main.py — Integracni testy pro main.py (Bazos + Vinted)
DevOps Agent | Vsechno mockavano — zadny HTTP, zadny Telegram
"""

import pathlib
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from scraper import Inzerat
from filter import uloz_seen_ids
import main as main_module


# ---------------------------------------------------------------------------
# Pomocne tovarny
# ---------------------------------------------------------------------------

def make_bazos_inzerat(id: str = "100", nazev: str = "PlayStation 5 Disk Edition") -> Inzerat:
    return Inzerat(
        id=id,
        nazev=nazev,
        url=f"https://pc.bazos.cz/inzerat/{id}/playstation-5.php",
        cena="9 500 Kč",
        lokalita="Praha",
        datum="5.9. 2026",
        popis="PlayStation 5 s mechanikou, kompletní balení, zánovní stav.",
    )


def make_vinted_inzerat(id: str = "vt_4567890001", nazev: str = "PS5 Slim Digital") -> Inzerat:
    return Inzerat(
        id=id,
        nazev=nazev,
        url=f"https://www.vinted.cz/items/{id[3:]}-ps5-slim",
        cena="8 200 Kč",
        lokalita="Brno",
        datum="VT",
        popis="Perfektní stav, kompletní balení.",
    )


def make_notifier_mock() -> MagicMock:
    notifier = MagicMock()
    notifier.notifikuj_davku.return_value = 1
    return notifier


def make_vinted_session() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Testy jeden_cyklus — oba portaly (Bazos + Vinted)
# ---------------------------------------------------------------------------

class TestJedenCyklus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.seen_path = pathlib.Path(self.tmp.name)
        self.seen_path.unlink()

        self.db_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_tmp.close()
        self.db_path = pathlib.Path(self.db_tmp.name)
        from db import init_db
        init_db(self.db_path)

    def tearDown(self):
        self.seen_path.unlink(missing_ok=True)
        self.db_path.unlink(missing_ok=True)

    def _bazos_html(self) -> str:
        fixture = pathlib.Path(__file__).parent / "fixtures" / "bazos_search.html"
        return fixture.read_text(encoding="utf-8", errors="replace")

    def _bazos_ps5_inzeraty(self) -> list[Inzerat]:
        """Vrací PS5 inzeráty pro Bazoš."""
        return [
            Inzerat(
                id="223396379",
                nazev="PlayStation 5 Slim 1TB Disk",
                url="https://pc.bazos.cz/inzerat/223396379/ps5-slim.php",
                cena="9 500 Kč",
                lokalita="Praha",
                datum="5.9. 2026",
                popis="Zánovní PlayStation 5 Slim s mechanikou.",
            ),
            Inzerat(
                id="223396380",
                nazev="Sony PlayStation 5 Digital Edition",
                url="https://pc.bazos.cz/inzerat/223396380/ps5-digital.php",
                cena="8 200 Kč",
                lokalita="Brno",
                datum="5.9. 2026",
                popis="PlayStation 5 Digital, kompletní balení.",
            ),
        ]

    def _vinted_inzeraty(self) -> list[Inzerat]:
        """Načte Vinted inzeráty z lokální fixture — žádný HTTP."""
        from vinted_scraper import parsuj_html_vinted
        fixture = pathlib.Path(__file__).parent / "fixtures" / "vinted_ps5.html"
        html = fixture.read_text(encoding="utf-8", errors="replace")
        return parsuj_html_vinted(html)

    def test_cyklus_zahrnuje_oba_portaly(self):
        """jeden_cyklus musi sloucit inzeraty z Bazose i Vinted."""
        notifier = make_notifier_mock()
        session = MagicMock()
        vinted_session = make_vinted_session()
        bazos_inzeraty = self._bazos_ps5_inzeraty()
        vinted_inzeraty = self._vinted_inzeraty()

        with patch("main.stahni_stranku", return_value=""):
            with patch("main.parsuj_html", return_value=bazos_inzeraty):
                with patch("main.stahni_vsechny_vinted_stranky", return_value=vinted_inzeraty):
                    seen = main_module.jeden_cyklus(
                        session=session,
                        vinted_session=vinted_session,
                        notifier=notifier,
                        seen_ids_cesta=self.seen_path,
                        vinted_enabled=True,
                        db_path=self.db_path,
                    )

        # V seen_ids musi byt ID z obou portalu
        bazos_ids = {i for i in seen if not i.startswith("vt_")}
        vinted_ids = {i for i in seen if i.startswith("vt_")}
        self.assertGreater(len(bazos_ids), 0, "Zadna Bazos ID v seen")
        self.assertGreater(len(vinted_ids), 0, "Zadna Vinted ID v seen")

    def test_cyklus_vinted_disabled(self):
        """Kdyz vinted_enabled=False, Vinted scraper se nevola."""
        notifier = make_notifier_mock()
        session = MagicMock()
        vinted_session = make_vinted_session()

        with patch("main.stahni_stranku", return_value=self._bazos_html()):
            with patch("main.stahni_vsechny_vinted_stranky") as mock_vinted:
                main_module.jeden_cyklus(
                    session=session,
                    vinted_session=vinted_session,
                    notifier=notifier,
                    seen_ids_cesta=self.seen_path,
                    vinted_enabled=False,
                    db_path=self.db_path,
                )
                mock_vinted.assert_not_called()

    def test_cyklus_aktualizuje_seen_ids(self):
        notifier = make_notifier_mock()
        session = MagicMock()
        vinted_session = make_vinted_session()
        bazos_inzeraty = self._bazos_ps5_inzeraty()

        with patch("main.stahni_stranku", return_value=""):
            with patch("main.parsuj_html", return_value=bazos_inzeraty):
                with patch("main.stahni_vsechny_vinted_stranky", return_value=[]):
                    seen = main_module.jeden_cyklus(
                        session=session, vinted_session=vinted_session,
                        notifier=notifier, seen_ids_cesta=self.seen_path,
                        vinted_enabled=True,
                        db_path=self.db_path,
                    )
        self.assertGreater(len(seen), 0)

    def test_cyklus_chyba_bazos_pokracuje_vinted(self):
        """Padne-li Bazos, cyklus pokracuje se zpracovanim Vinted inzeratu."""
        notifier = make_notifier_mock()
        session = MagicMock()
        vinted_session = make_vinted_session()
        vinted_inzeraty = self._vinted_inzeraty()

        with patch("main.stahni_stranku", side_effect=Exception("Bazos timeout")):
            with patch("main.stahni_vsechny_vinted_stranky", return_value=vinted_inzeraty):
                seen = main_module.jeden_cyklus(
                    session=session, vinted_session=vinted_session,
                    notifier=notifier, seen_ids_cesta=self.seen_path,
                    vinted_enabled=True,
                    db_path=self.db_path,
                )
        # Vinted inzeraty musi byt v seen_ids i kdyz Bazos padl
        vinted_ids = {i for i in seen if i.startswith("vt_")}
        self.assertGreater(len(vinted_ids), 0)

    def test_cyklus_chyba_vinted_pokracuje_bazos(self):
        """Padne-li Vinted, cyklus pokracuje se zpracovanim Bazos inzeratu."""
        notifier = make_notifier_mock()
        session = MagicMock()
        vinted_session = make_vinted_session()
        bazos_inzeraty = self._bazos_ps5_inzeraty()

        with patch("main.stahni_stranku", return_value=""):
            with patch("main.parsuj_html", return_value=bazos_inzeraty):
                with patch("main.stahni_vsechny_vinted_stranky", side_effect=Exception("Vinted timeout")):
                    seen = main_module.jeden_cyklus(
                        session=session, vinted_session=vinted_session,
                        notifier=notifier, seen_ids_cesta=self.seen_path,
                        vinted_enabled=True,
                        db_path=self.db_path,
                    )
        bazos_ids = {i for i in seen if not i.startswith("vt_")}
        self.assertGreater(len(bazos_ids), 0)

    def test_cyklus_druhy_bez_notifikace(self):
        """Druhy cyklus se stejnymi daty nesmi odeslat notifikaci."""
        notifier1 = make_notifier_mock()
        session = MagicMock()
        vinted_session = make_vinted_session()

        with patch("main.stahni_stranku", return_value=self._bazos_html()):
            with patch("main.stahni_vsechny_vinted_stranky", return_value=[]):
                main_module.jeden_cyklus(
                    session=session, vinted_session=vinted_session,
                    notifier=notifier1, seen_ids_cesta=self.seen_path,
                    vinted_enabled=True,
                    db_path=self.db_path,
                )

        notifier2 = make_notifier_mock()
        with patch("main.stahni_stranku", return_value=self._bazos_html()):
            with patch("main.stahni_vsechny_vinted_stranky", return_value=[]):
                main_module.jeden_cyklus(
                    session=session, vinted_session=vinted_session,
                    notifier=notifier2, seen_ids_cesta=self.seen_path,
                    vinted_enabled=True,
                    db_path=self.db_path,
                )

        notifier2.notifikuj_davku.assert_not_called()

    def test_cyklus_vraci_mnozinu(self):
        notifier = make_notifier_mock()
        session = MagicMock()
        vinted_session = make_vinted_session()

        with patch("main.stahni_stranku", return_value=self._bazos_html()):
            with patch("main.stahni_vsechny_vinted_stranky", return_value=[]):
                seen = main_module.jeden_cyklus(
                    session=session, vinted_session=vinted_session,
                    notifier=notifier, seen_ids_cesta=self.seen_path,
                    vinted_enabled=True,
                    db_path=self.db_path,
                )
        self.assertIsInstance(seen, set)


# ---------------------------------------------------------------------------
# Testy konfigurace
# ---------------------------------------------------------------------------

class TestKonfigurace(unittest.TestCase):

    def test_vinted_enabled_default_true(self):
        import importlib
        with patch.dict("os.environ", {}, clear=True):
            import main as m
            importlib.reload(m)
            self.assertTrue(m.VINTED_ENABLED)

    def test_vinted_enabled_false(self):
        import importlib
        with patch.dict("os.environ", {"VINTED_ENABLED": "false"}):
            import main as m
            importlib.reload(m)
            self.assertFalse(m.VINTED_ENABLED)

    def test_vinted_enabled_zero(self):
        import importlib
        with patch.dict("os.environ", {"VINTED_ENABLED": "0"}):
            import main as m
            importlib.reload(m)
            self.assertFalse(m.VINTED_ENABLED)

    def test_interval_min_max_z_env(self):
        import importlib
        with patch.dict("os.environ", {
            "SCRAPE_INTERVAL_MIN": "60",
            "SCRAPE_INTERVAL_MAX": "180",
        }):
            import main as m
            importlib.reload(m)
            self.assertEqual(m.SCRAPE_INTERVAL_MIN, 60)
            self.assertEqual(m.SCRAPE_INTERVAL_MAX, 180)

    def test_db_path_z_env(self):
        import importlib
        with patch.dict("os.environ", {
            "DB_PATH": "/custom/path/market.db",
        }):
            import main as m
            importlib.reload(m)
            self.assertEqual(str(m.DB_PATH).replace("\\", "/"), "/custom/path/market.db")


# ---------------------------------------------------------------------------
# Testy DB integrace v jeden_cyklus
# ---------------------------------------------------------------------------

class TestDbIntegraceVMain(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.seen_path = pathlib.Path(self.tmp.name)
        self.seen_path.unlink()

        self.db_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_tmp.close()
        self.db_path = pathlib.Path(self.db_tmp.name)
        from db import init_db
        init_db(self.db_path)

    def tearDown(self):
        self.seen_path.unlink(missing_ok=True)
        self.db_path.unlink(missing_ok=True)

    def test_inzeraty_se_ulozit_do_db_po_odeslani_notifikace(self):
        """Ověří, že nalezené inzeráty se po notifikaci uloží do DB se statusem 'active'."""
        from db import nacti_vsechny_inzeraty
        notifier = make_notifier_mock()
        session = MagicMock()
        vinted_session = make_vinted_session()

        inzeraty = [
            make_bazos_inzerat("555111", "PlayStation 5 Slim Disk"),
            make_vinted_inzerat("vt_777222", "PS5 Digital Edition"),
        ]

        with patch("main.stahni_stranku", return_value=""):
            with patch("main.parsuj_html", return_value=[inzeraty[0]]):
                with patch("main.stahni_vsechny_vinted_stranky", return_value=[inzeraty[1]]):
                    main_module.jeden_cyklus(
                        session=session,
                        vinted_session=vinted_session,
                        notifier=notifier,
                        seen_ids_cesta=self.seen_path,
                        vinted_enabled=True,
                        db_path=self.db_path,
                    )

        # Ověříme, že notifier byl zavolán
        notifier.notifikuj_davku.assert_called_once()

        # Ověříme záznamy v DB
        zaznamy = nacti_vsechny_inzeraty(self.db_path)
        self.assertEqual(len(zaznamy), 2)
        item_ids = {z["item_id"] for z in zaznamy}
        self.assertEqual(item_ids, {"555111", "vt_777222"})

        for z in zaznamy:
            self.assertEqual(z["status"], "active")
            self.assertIsNotNone(z["found_date"])
            self.assertIsNone(z["sold_date"])

    def test_db_chyba_nezastavi_aktualizaci_seen_ids(self):
        """Při selhání DB se cyklus nezhroutí a seen_ids se stále aktualizují."""
        notifier = make_notifier_mock()
        session = MagicMock()
        vinted_session = make_vinted_session()
        inzeraty = [make_bazos_inzerat("999888")]

        with patch("main.stahni_stranku", return_value=""):
            with patch("main.parsuj_html", return_value=inzeraty):
                with patch("main.stahni_vsechny_vinted_stranky", return_value=[]):
                    with patch("main.uloz_inzeraty_davku", side_effect=Exception("DB lock")):
                        seen = main_module.jeden_cyklus(
                            session=session,
                            vinted_session=vinted_session,
                            notifier=notifier,
                            seen_ids_cesta=self.seen_path,
                            vinted_enabled=True,
                            db_path=self.db_path,
                        )

        self.assertIn("999888", seen)

    def test_spust_startuje_tracker_thread(self):
        """Ověří, že funkce spust() inicializuje DB a odstartuje tracker thread."""
        with patch("main.vytvor_notifier_z_env"):
            with patch("main.init_db"):
                with patch("main.start_tracker_thread") as mock_tracker:
                    with patch("main.vytvor_session"):
                        with patch("main.vytvor_vinted_session"):
                            with patch("main._running", False):
                                main_module.spust()
                                mock_tracker.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)

