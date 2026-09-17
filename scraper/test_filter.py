"""
test_filter.py - Unit testy pro filter.py - PlayStation 5 konzole
DevOps Agent | TDD smycka - zadny HTTP, zadny filesystem side-effect
"""

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from scraper import Inzerat
from filter import (
    VysledekFiltrace,
    _obsahuje_klicove_slovo,
    _obsahuje_negativni_slovo,
    _je_pod_minimalni_cenou,
    _zkontroluj_cenu,
    _je_scam,
    _je_google_translate,
    je_vinted_inzerat,
    filtruj_inzerat,
    filtruj_seznam,
    nacti_seen_ids,
    uloz_seen_ids,
    odfiltruj_nove,
    zpracuj_davku,
    MIN_CENA_CZK,
    MAX_CENA_CZK,
    MIN_CENA_EUR,
    MAX_CENA_EUR,
    validuj_llm,
    LLMVysledek,
)


def inzerat(
    id="100",
    nazev="PlayStation 5 Disk Edition",
    url="https://www.bazos.cz/inzerat/100/playstation-5.php",
    cena="10 500 Kč",
    lokalita="Praha",
    datum="5.9. 2026",
    popis="PS5 konzole, Disk edice, zanovni stav.",
):
    return Inzerat(id=id, nazev=nazev, url=url, cena=cena,
                   lokalita=lokalita, datum=datum, popis=popis)


def vinted_inzerat(id="vt_4567890001", nazev="PS5 Slim Digital", cena="9 200 Kč"):
    return Inzerat(
        id=id,
        nazev=nazev,
        url=f"https://www.vinted.cz/items/{id[3:]}-ps5",
        cena=cena,
        lokalita="Brno",
        datum="VT",
        popis="Perfektni stav.",
    )


def scam_inzerat():
    return inzerat(id="999", nazev="PS5 prodej levne",
                   popis="Kontaktujte pres WhatsApp +1234, zalohovat do zahranici.")


def google_translate_inzerat():
    return inzerat(
        id="888", nazev="PS5 konzole vyprodej",
        url="https://translate.google.com/translate?hl=cs&u=https://bazos.cz/888.php",
    )


def irelevantni_inzerat():
    return inzerat(id="777", nazev="Xbox Series X 1TB",
                   popis="Prodej Xbox Series X, zanovni.")


class TestKlicovaSlova(unittest.TestCase):

    def test_ps5_v_nazvu(self):
        self.assertTrue(_obsahuje_klicove_slovo(inzerat(nazev="PS5 Disk Edition")))

    def test_playstation5_v_nazvu(self):
        self.assertTrue(_obsahuje_klicove_slovo(inzerat(nazev="PlayStation5 Disk")))

    def test_playstation_5_v_nazvu(self):
        self.assertTrue(_obsahuje_klicove_slovo(inzerat(nazev="PlayStation 5 Slim")))

    def test_play_station_5_v_nazvu(self):
        self.assertTrue(_obsahuje_klicove_slovo(inzerat(nazev="Play Station 5 konzole")))

    def test_ps_5_v_nazvu(self):
        self.assertTrue(_obsahuje_klicove_slovo(inzerat(nazev="PS 5 zanovni")))

    def test_ps5_v_popisu(self):
        self.assertTrue(_obsahuje_klicove_slovo(inzerat(nazev="Konzole", popis="Prodam PS5 Disk.")))

    def test_irelevantni_inzerat(self):
        self.assertFalse(_obsahuje_klicove_slovo(irelevantni_inzerat()))

    def test_case_insensitive(self):
        self.assertTrue(_obsahuje_klicove_slovo(inzerat(nazev="PS5 DISK EDITION")))

    def test_prazdny_popis(self):
        self.assertTrue(_obsahuje_klicove_slovo(inzerat(nazev="PS5 Slim", popis=None)))

    def test_vinted_bez_ps5_projde(self):
        i = vinted_inzerat(nazev="Konzole herni")
        self.assertTrue(_obsahuje_klicove_slovo(i))
        self.assertTrue(je_vinted_inzerat(i))


class TestNegativniSlova(unittest.TestCase):

    def _test_neg(self, slovo, kde="nazev"):
        if kde == "nazev":
            i = inzerat(nazev=f"PS5 {slovo}", popis="Standardni PS5.")
        else:
            i = inzerat(nazev="PS5 konzole", popis=f"Prodam {slovo} k PS5.")
        nalezeno, _ = _obsahuje_negativni_slovo(i)
        self.assertTrue(nalezeno, f"Slovo '{slovo}' nebylo detekováno")

    def test_neg_ovladac(self):       self._test_neg("ovladac")
    def test_neg_controller(self):    self._test_neg("controller")
    def test_neg_dualsense(self):     self._test_neg("dualsense")
    def test_neg_headset(self):       self._test_neg("headset")
    def test_neg_kryt(self):          self._test_neg("kryt")
    def test_neg_kabel(self):         self._test_neg("kabel")
    def test_neg_hdmi(self):          self._test_neg("hdmi")
    def test_neg_stojan(self):        self._test_neg("stojan")
    def test_neg_rozbite(self):       self._test_neg("rozbita")
    def test_neg_nefunkcni(self):     self._test_neg("nefunkcni")
    def test_neg_pronajem(self):      self._test_neg("pujcim")
    def test_neg_hledam(self):        self._test_neg("hledam")
    def test_neg_koupim(self):        self._test_neg("koupim")
    def test_neg_xbox(self):          self._test_neg("xbox")
    def test_neg_nintendo(self):      self._test_neg("nintendo")

    def test_neg_ps4(self):
        i = inzerat(nazev="PS5 + PS4 bundle")
        nalezeno, _ = _obsahuje_negativni_slovo(i)
        self.assertTrue(nalezeno)

    def test_neg_playstation4(self):
        i = inzerat(nazev="PS5 a playstation 4 bundle")
        nalezeno, _ = _obsahuje_negativni_slovo(i)
        self.assertTrue(nalezeno)

    def test_neg_ucet(self):
        i = inzerat(nazev="PS5 ucet na prodej")
        nalezeno, _ = _obsahuje_negativni_slovo(i)
        self.assertTrue(nalezeno)

    def test_neg_account(self):
        i = inzerat(nazev="PS5 account for sale")
        nalezeno, _ = _obsahuje_negativni_slovo(i)
        self.assertTrue(nalezeno)

    def test_neg_vr2(self):
        i = inzerat(nazev="PS5 + VR2 headset bundle")
        nalezeno, _ = _obsahuje_negativni_slovo(i)
        self.assertTrue(nalezeno)

    def test_neg_psvr(self):
        i = inzerat(nazev="PS5 + PSVR2 sada")
        nalezeno, _ = _obsahuje_negativni_slovo(i)
        self.assertTrue(nalezeno)

    def test_neg_volant(self):
        i = inzerat(nazev="PS5 + volant Logitech G29")
        nalezeno, _ = _obsahuje_negativni_slovo(i)
        self.assertTrue(nalezeno)

    def test_neg_krabice(self):
        i = inzerat(nazev="Prazdna krabice od PS5")
        nalezeno, _ = _obsahuje_negativni_slovo(i)
        self.assertTrue(nalezeno)

    def test_cisty_ps5_neni_zamitnut(self):
        i = inzerat(nazev="PlayStation 5 Disk Edition zanovni",
                    popis="Konzole PS5, jeden majitel, plne funkcni.")
        nalezeno, slovo = _obsahuje_negativni_slovo(i)
        self.assertFalse(nalezeno, f"Cisty PS5 zamitnut slovem '{slovo}'")


class TestCenoveLimity(unittest.TestCase):

    def test_min_cena_czk(self):     self.assertEqual(MIN_CENA_CZK, 3_000)
    def test_max_cena_czk(self):     self.assertEqual(MAX_CENA_CZK, 13_500)
    def test_min_cena_eur(self):     self.assertEqual(MIN_CENA_EUR, 120)
    def test_max_cena_eur(self):     self.assertEqual(MAX_CENA_EUR, 540)

    def test_cena_v_limitu(self):
        self.assertFalse(_zkontroluj_cenu(inzerat(cena="10 500 Kč"))[0])

    def test_cena_pod_minimem(self):
        zahodit, duvod = _zkontroluj_cenu(inzerat(cena="2 999 Kč"))
        self.assertTrue(zahodit)
        self.assertIn("minimum", duvod)

    def test_cena_nad_maximem(self):
        zahodit, duvod = _zkontroluj_cenu(inzerat(cena="14 000 Kč"))
        self.assertTrue(zahodit)
        self.assertIn("maximum", duvod)

    def test_cena_presne_na_maximu_projde(self):
        self.assertFalse(_zkontroluj_cenu(inzerat(cena="13 500 Kč"))[0])

    def test_cena_presne_na_minimu_projde(self):
        self.assertFalse(_zkontroluj_cenu(inzerat(cena="3 000 Kč"))[0])

    def test_vb_zahozena(self):
        zahodit, _ = _zkontroluj_cenu(inzerat(cena="VB"))
        self.assertTrue(zahodit)

    def test_dohodou_zahozena(self):
        self.assertTrue(_zkontroluj_cenu(inzerat(cena="Dohodou"))[0])

    def test_prazdna_cena(self):
        self.assertTrue(_zkontroluj_cenu(inzerat(cena=""))[0])

    def test_eur_v_limitu(self):
        self.assertFalse(_zkontroluj_cenu(inzerat(cena="390 EUR"))[0])

    def test_eur_nad_maximem(self):
        zahodit, duvod = _zkontroluj_cenu(inzerat(cena="600 EUR"))
        self.assertTrue(zahodit)
        self.assertIn("maximum", duvod)

    def test_eur_pod_minimem(self):
        zahodit, _ = _zkontroluj_cenu(inzerat(cena="50 EUR"))
        self.assertTrue(zahodit)

    def test_neznama_mena(self):
        self.assertTrue(_zkontroluj_cenu(inzerat(cena="350 USD"))[0])

    def test_alias_existuje(self):
        self.assertIs(_je_pod_minimalni_cenou, _zkontroluj_cenu)


class TestScamDetekce(unittest.TestCase):

    def test_whatsapp_je_scam(self):
        je_scam, duvod = _je_scam(scam_inzerat())
        self.assertTrue(je_scam)
        self.assertIn("scam", duvod)

    def test_western_union_je_scam(self):
        i = inzerat(popis="Platba pres Western Union, zalohovat 50%.")
        self.assertTrue(_je_scam(i)[0])

    def test_paypal_je_scam(self):
        i = inzerat(popis="Platba pres PayPal only.")
        self.assertTrue(_je_scam(i)[0])

    def test_cisty_inzerat_neni_scam(self):
        self.assertFalse(_je_scam(inzerat())[0])


class TestGoogleTranslate(unittest.TestCase):

    def test_google_translate_url(self):
        self.assertTrue(_je_google_translate(google_translate_inzerat()))

    def test_normalni_url(self):
        self.assertFalse(_je_google_translate(inzerat()))

    def test_hl_parametr(self):
        i = inzerat(url="https://bazos.cz/100.php?&hl=cs")
        self.assertTrue(_je_google_translate(i))


class TestVintedDetekce(unittest.TestCase):

    def test_vt_prefix(self):
        self.assertTrue(je_vinted_inzerat(vinted_inzerat(id="vt_123456")))

    def test_vinted_url(self):
        i = inzerat(id="999", url="https://www.vinted.cz/items/12345-ps5")
        self.assertTrue(je_vinted_inzerat(i))

    def test_datum_vt(self):
        i = inzerat(id="888", datum="VT")
        self.assertTrue(je_vinted_inzerat(i))

    def test_bazos_neni_vinted(self):
        self.assertFalse(je_vinted_inzerat(inzerat()))


class TestFiltrujInzerat(unittest.TestCase):

    def test_cisty_ps5_prijat(self):
        v = filtruj_inzerat(inzerat())
        self.assertTrue(v.prijat)

    def test_scam_zamitnut(self):
        v = filtruj_inzerat(scam_inzerat())
        self.assertFalse(v.prijat)
        self.assertIn("scam", v.duvod_zamitnuti)

    def test_google_translate_zamitnut(self):
        v = filtruj_inzerat(google_translate_inzerat())
        self.assertFalse(v.prijat)
        self.assertIn("Google Translate", v.duvod_zamitnuti)

    def test_drahy_ps5_zamitnut(self):
        v = filtruj_inzerat(inzerat(cena="25 000 Kč"))
        self.assertFalse(v.prijat)
        self.assertIn("cena", v.duvod_zamitnuti)

    def test_ps5_s_vr2_zamitnut(self):
        v = filtruj_inzerat(inzerat(nazev="PS5 Disk Edition + VR2 headset"))
        self.assertFalse(v.prijat)

    def test_xbox_zamitnut(self):
        v = filtruj_inzerat(irelevantni_inzerat())
        self.assertFalse(v.prijat)

    def test_ps5_s_ps4_zamitnut(self):
        v = filtruj_inzerat(inzerat(nazev="PS5 + PS4 balicek", cena="9 000 Kč"))
        self.assertFalse(v.prijat)
        self.assertIn("slovo", v.duvod_zamitnuti)

    def test_vinted_ps5_slim_prijat(self):
        v = filtruj_inzerat(vinted_inzerat(nazev="PS5 Slim Digital 1TB"))
        self.assertTrue(v.prijat)

    def test_vysledek_je_instance(self):
        i = inzerat()
        v = filtruj_inzerat(i)
        self.assertIsInstance(v, VysledekFiltrace)
        self.assertIs(v.inzerat, i)

    def test_ucet_zamitnut(self):
        v = filtruj_inzerat(inzerat(nazev="PS5 PSN ucet prodam", cena="5 000 Kč"))
        self.assertFalse(v.prijat)

    def test_account_zamitnut(self):
        v = filtruj_inzerat(inzerat(nazev="PS5 account for sale", cena="4 000 Kč"))
        self.assertFalse(v.prijat)

    def test_krabice_zamitnut(self):
        v = filtruj_inzerat(inzerat(nazev="Prazdna krabice od PS5", cena="500 Kč"))
        self.assertFalse(v.prijat)

    def test_volant_zamitnut(self):
        v = filtruj_inzerat(inzerat(nazev="PS5 + volant Thrustmaster", cena="8 000 Kč"))
        self.assertFalse(v.prijat)


class TestFiltrujSeznam(unittest.TestCase):

    def test_prazdny_seznam(self):
        self.assertEqual(filtruj_seznam([]), [])

    def test_mix_prijatych_a_zamitnutych(self):
        lst = [
            inzerat(id="1", cena="10 000 Kč"),
            scam_inzerat(),
            irelevantni_inzerat(),
            inzerat(id="4", cena="5 500 Kč"),
        ]
        vysledky = filtruj_seznam(lst)
        self.assertEqual(len(vysledky), 4)
        self.assertEqual(len([v for v in vysledky if v.prijat]), 2)

    def test_vsechny_prijaty(self):
        lst = [inzerat(id="1", cena="8 000 Kč"), inzerat(id="2", cena="9 000 Kč")]
        self.assertTrue(all(v.prijat for v in filtruj_seznam(lst)))

    def test_vsechny_zamitnuty(self):
        lst = [scam_inzerat(), google_translate_inzerat()]
        self.assertFalse(any(v.prijat for v in filtruj_seznam(lst)))


class TestSeenIds(unittest.TestCase):

    def test_nacti_seen_ids_neexistujici(self):
        ids = nacti_seen_ids(pathlib.Path("/tmp/neexistujici_ps5_xyz.json"))
        self.assertEqual(ids, set())

    def test_uloz_a_nacti(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            cesta = pathlib.Path(f.name)
        try:
            ids = {"bazos_1001", "bazos_1002", "vt_5000"}
            uloz_seen_ids(ids, cesta)
            self.assertEqual(nacti_seen_ids(cesta), ids)
        finally:
            cesta.unlink(missing_ok=True)

    def test_odfiltruj_nove_vylucuje_videne(self):
        lst = [inzerat(id="1000"), inzerat(id="1001"), inzerat(id="1002")]
        nove = odfiltruj_nove(lst, {"1000", "1001"})
        self.assertEqual(len(nove), 1)
        self.assertEqual(nove[0].id, "1002")

    def test_odfiltruj_nove_prazdna_seen(self):
        lst = [inzerat(id="1"), inzerat(id="2")]
        self.assertEqual(len(odfiltruj_nove(lst, set())), 2)

    def test_odfiltruj_nove_vsechny_videny(self):
        lst = [inzerat(id="1"), inzerat(id="2")]
        self.assertEqual(odfiltruj_nove(lst, {"1", "2"}), [])

    def test_zpracuj_davku(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            cesta = pathlib.Path(f.name)
        try:
            uloz_seen_ids({"999"}, cesta)
            lst = [
                inzerat(id="101", cena="10 000 Kč"),
                scam_inzerat(),
                inzerat(id="102", cena="25 000 Kč"),
                irelevantni_inzerat(),
            ]
            prijate = zpracuj_davku(lst, cesta)
            self.assertEqual(len(prijate), 1)
            self.assertEqual(prijate[0].id, "101")
        finally:
            cesta.unlink(missing_ok=True)


class TestHranicniPripady(unittest.TestCase):

    def test_cena_13501_nad_limitem(self):
        zahodit, duvod = _zkontroluj_cenu(inzerat(cena="13 501 Kč"))
        self.assertTrue(zahodit)
        self.assertIn("maximum", duvod)

    def test_cena_2999_pod_limitem(self):
        self.assertTrue(_zkontroluj_cenu(inzerat(cena="2 999 Kč"))[0])

    def test_slim_digital_projde_filtrem(self):
        v = filtruj_inzerat(vinted_inzerat(nazev="PS5 Slim Digital 1TB", cena="9 500 Kč"))
        self.assertTrue(v.prijat)

    def test_playstation_4_v_bundle_zamitnut(self):
        v = filtruj_inzerat(inzerat(
            nazev="Prodam PlayStation 5 + PlayStation 4 konzoli",
            cena="10 000 Kč",
        ))
        self.assertFalse(v.prijat)


class TestGeminiKeyRotation(unittest.TestCase):
    """Testy pro rotaci GEMINI_API_KEY a chování validuj_llm."""

    def setUp(self):
        import os
        self.orig_env = os.environ.get("GEMINI_API_KEY")
        self.orig_google = sys.modules.get("google")
        self.orig_genai = sys.modules.get("google.genai")
        self.orig_types = sys.modules.get("google.genai.types")

    def tearDown(self):
        import os
        if self.orig_env is not None:
            os.environ["GEMINI_API_KEY"] = self.orig_env
        else:
            os.environ.pop("GEMINI_API_KEY", None)

        for mod, orig in [
            ("google", self.orig_google),
            ("google.genai", self.orig_genai),
            ("google.genai.types", self.orig_types),
        ]:
            if orig is not None:
                sys.modules[mod] = orig
            else:
                sys.modules.pop(mod, None)

    def _setup_mock_google(self):
        from unittest.mock import MagicMock
        mock_google = MagicMock()
        mock_genai = MagicMock()
        mock_types = MagicMock()
        mock_google.genai = mock_genai
        sys.modules["google"] = mock_google
        sys.modules["google.genai"] = mock_genai
        sys.modules["google.genai.types"] = mock_types
        return mock_genai, mock_types

    def test_rotace_klice_pri_429(self):
        import os
        from unittest.mock import MagicMock
        os.environ["GEMINI_API_KEY"] = "key1,key2"
        mock_genai, mock_types = self._setup_mock_google()

        client1 = MagicMock()
        client1.models.generate_content.side_effect = Exception("429 Resource has been exhausted")

        client2 = MagicMock()
        resp2 = MagicMock()
        resp2.text = json.dumps({
            "is_valid": True,
            "clean_name": "PlayStation 5 Slim Disk",
            "edition": "Disk",
            "is_slim": True,
            "duvod": "Validní PS5 konzole",
        })
        client2.models.generate_content.return_value = resp2

        mock_genai.Client.side_effect = [client1, client2]

        with self.assertLogs("filter", level="WARNING") as log_cm:
            res = validuj_llm(inzerat(nazev="PlayStation 5 Slim Disk"))

        self.assertIsNotNone(res)
        self.assertTrue(res.is_valid)
        self.assertEqual(res.clean_name, "PlayStation 5 Slim Disk")
        self.assertEqual(res.edition, "Disk")
        self.assertTrue(res.is_slim)
        self.assertTrue(any("Klíč vyčerpán, přepínám na další..." in m for m in log_cm.output))
        self.assertEqual(mock_genai.Client.call_count, 2)
        mock_genai.Client.assert_any_call(api_key="key1")
        mock_genai.Client.assert_any_call(api_key="key2")

    def test_zamitnuti_inzeratu_loguje_zahazuji(self):
        import os
        from unittest.mock import MagicMock
        os.environ["GEMINI_API_KEY"] = "key_single"
        mock_genai, _ = self._setup_mock_google()

        client = MagicMock()
        resp = MagicMock()
        resp.text = json.dumps({
            "is_valid": False,
            "clean_name": "DualSense Controller",
            "edition": "Unknown",
            "is_slim": False,
            "duvod": "Samostatný ovladač, ne konzole",
        })
        client.models.generate_content.return_value = resp
        mock_genai.Client.return_value = client

        with self.assertLogs("filter", level="INFO") as log_cm:
            res = validuj_llm(inzerat(nazev="DualSense ovladač"))

        self.assertIsNotNone(res)
        self.assertFalse(res.is_valid)
        self.assertTrue(
            any("Zahazuji: DualSense ovladač | Důvod: Samostatný ovladač, ne konzole" in m for m in log_cm.output)
        )

    def test_vsechny_klice_vycerpany_vrati_none(self):
        import os
        from unittest.mock import MagicMock
        os.environ["GEMINI_API_KEY"] = "key1,key2"
        mock_genai, _ = self._setup_mock_google()

        mock_genai.Client.side_effect = [
            MagicMock(models=MagicMock(generate_content=MagicMock(side_effect=Exception("Rate limit reached")))),
            MagicMock(models=MagicMock(generate_content=MagicMock(side_effect=Exception("quota exceeded")))),
        ]

        with self.assertLogs("filter", level="WARNING") as log_cm:
            res = validuj_llm(inzerat(nazev="PS5 konzole"))

        self.assertIsNone(res)
        warning_count = sum("Klíč vyčerpán, přepínám na další..." in m for m in log_cm.output)
        self.assertEqual(warning_count, 2)

    def test_storage_pripojeno_k_nazvu(self):
        import os
        from unittest.mock import MagicMock
        os.environ["GEMINI_API_KEY"] = "key_storage"
        mock_genai, _ = self._setup_mock_google()

        client = MagicMock()
        resp = MagicMock()
        resp.text = json.dumps({
            "is_valid": True,
            "clean_name": "PlayStation 5 Slim",
            "edition": "Digital",
            "is_slim": True,
            "storage": "1TB",
            "duvod": "Konzole PS5 Slim Digital 1TB",
        })
        client.models.generate_content.return_value = resp
        mock_genai.Client.return_value = client

        res = validuj_llm(inzerat(nazev="PS5 Slim Digital"))
        self.assertIsNotNone(res)
        self.assertEqual(res.clean_name, "PlayStation 5 Slim 1TB")
        self.assertEqual(res.storage, "1TB")

    def test_storage_nezdvojuje_se_kdyz_uz_je_v_nazvu(self):
        import os
        from unittest.mock import MagicMock
        os.environ["GEMINI_API_KEY"] = "key_storage"
        mock_genai, _ = self._setup_mock_google()

        client = MagicMock()
        resp = MagicMock()
        resp.text = json.dumps({
            "is_valid": True,
            "clean_name": "PlayStation 5 Slim 1TB",
            "edition": "Disk",
            "is_slim": True,
            "storage": "1TB",
            "duvod": "Konzole",
        })
        client.models.generate_content.return_value = resp
        mock_genai.Client.return_value = client

        res = validuj_llm(inzerat(nazev="PS5 1TB"))
        self.assertIsNotNone(res)
        self.assertEqual(res.clean_name, "PlayStation 5 Slim 1TB")
        self.assertNotIn("1TB 1TB", res.clean_name)

    def test_storage_prazdne_nemeni_nazev(self):
        import os
        from unittest.mock import MagicMock
        os.environ["GEMINI_API_KEY"] = "key_storage"
        mock_genai, _ = self._setup_mock_google()

        client = MagicMock()
        resp = MagicMock()
        resp.text = json.dumps({
            "is_valid": True,
            "clean_name": "PlayStation 5 Disk Edition",
            "edition": "Disk",
            "is_slim": False,
            "storage": "",
            "duvod": "Fat verze",
        })
        client.models.generate_content.return_value = resp
        mock_genai.Client.return_value = client

        res = validuj_llm(inzerat(nazev="PS5 Disk"))
        self.assertIsNotNone(res)
        self.assertEqual(res.clean_name, "PlayStation 5 Disk Edition")


if __name__ == "__main__":
    unittest.main(verbosity=2)