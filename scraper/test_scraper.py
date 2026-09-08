"""
test_scraper.py — Unit testy pro scraper.py (Fáze 1)
DevOps Agent | TDD smyčka — ŽÁDNÝ HTTP request na reálný Bazoš.
Testy čtou VÝHRADNĚ lokální HTML fixture: fixtures/bazos_search.html
"""

import pathlib
import re
import sys
import unittest

# Přidáme scraper/ do sys.path pro import
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from scraper import Inzerat, _extrahuj_id_z_url, parsuj_html

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "bazos_search.html"


def nacti_fixture() -> str:
    """Načte lokální HTML fixture. Test selže, pokud soubor neexistuje."""
    if not FIXTURE_PATH.exists():
        raise FileNotFoundError(
            f"Fixture nenalezena: {FIXTURE_PATH}\n"
            "Spusť: py -c \"...\" pro stažení fixture."
        )
    return FIXTURE_PATH.read_text(encoding="utf-8", errors="replace")


class TestExtrahujId(unittest.TestCase):
    """Testy pro pomocnou funkci _extrahuj_id_z_url."""

    def test_standardni_url(self):
        url = "https://stroje.bazos.cz/inzerat/223396379/minibagr-saurus-10n-diesel.php"
        self.assertEqual(_extrahuj_id_z_url(url), "223396379")

    def test_kratka_url(self):
        url = "https://www.bazos.cz/inzerat/111222333/test.php"
        self.assertEqual(_extrahuj_id_z_url(url), "111222333")

    def test_url_bez_id(self):
        url = "https://www.bazos.cz/search.php?hledat=minibagr"
        self.assertEqual(_extrahuj_id_z_url(url), "")

    def test_prazdny_retezec(self):
        self.assertEqual(_extrahuj_id_z_url(""), "")


class TestParsujHtml(unittest.TestCase):
    """Testy pro hlavní parsovací funkci parsuj_html()."""

    @classmethod
    def setUpClass(cls):
        """Načte fixture jednou pro všechny testy — žádný HTTP."""
        cls.html = nacti_fixture()
        cls.inzeraty = parsuj_html(cls.html)

    # --- Základní smoke testy ---

    def test_vraci_seznam(self):
        self.assertIsInstance(self.inzeraty, list)

    def test_nenulovy_pocet(self):
        self.assertGreater(len(self.inzeraty), 0, "Parser nenašel žádné inzeráty.")

    def test_minimalne_10_inzeratu(self):
        """Stránka Bazoše zobrazuje 20 inzerátů — chceme alespoň 10."""
        self.assertGreaterEqual(
            len(self.inzeraty), 10,
            f"Očekáváno ≥10 inzerátů, nalezeno {len(self.inzeraty)}."
        )

    # --- Datový model ---

    def test_vraci_instance_inzerat(self):
        for item in self.inzeraty:
            self.assertIsInstance(item, Inzerat, f"Nečekaný typ: {type(item)}")

    def test_id_je_numericke(self):
        for item in self.inzeraty:
            self.assertTrue(
                item.id.isdigit(),
                f"ID '{item.id}' není číslo (inzerát: {item.nazev!r})"
            )

    def test_nazev_neprazdny(self):
        for item in self.inzeraty:
            self.assertTrue(
                len(item.nazev) > 0,
                f"Prázdný název pro id={item.id}"
            )

    def test_url_je_absolutni(self):
        for item in self.inzeraty:
            self.assertTrue(
                item.url.startswith("http"),
                f"URL není absolutní: {item.url!r} (id={item.id})"
            )

    def test_url_obsahuje_id(self):
        for item in self.inzeraty:
            self.assertIn(
                item.id, item.url,
                f"ID {item.id} nenalezeno v URL: {item.url!r}"
            )

    def test_cena_neprazdna(self):
        for item in self.inzeraty:
            self.assertTrue(
                len(item.cena) > 0,
                f"Prázdná cena pro id={item.id}"
            )

    def test_lokalita_neprazdna(self):
        for item in self.inzeraty:
            self.assertTrue(
                len(item.lokalita) > 0,
                f"Prázdná lokalita pro id={item.id}"
            )

    def test_datum_neprazdny(self):
        for item in self.inzeraty:
            self.assertTrue(
                len(item.datum) > 0,
                f"Prázdné datum pro id={item.id}"
            )

    def test_datum_format(self):
        """Datum by mělo odpovídat formátu DD.M. YYYY nebo D.M. YYYY."""
        datum_vzor = re.compile(r"\d{1,2}\.\d{1,2}\.\s*\d{4}")
        for item in self.inzeraty:
            self.assertRegex(
                item.datum,
                datum_vzor,
                f"Datum '{item.datum}' neodpovídá očekávanému formátu (id={item.id})"
            )

    # --- Konkrétní inzeráty ze stažené fixture ---

    def test_prvni_inzerat_id(self):
        """Fixture obsahuje inzerát 223396379 jako první výsledek."""
        ids = [i.id for i in self.inzeraty]
        self.assertIn("223396379", ids, "Inzerát 223396379 (Saurus 10N) nebyl nalezen.")

    def test_cena_obsahuje_kc_nebo_v_textu(self):
        """Cena musí obsahovat 'Kč' nebo být 'V textu'."""
        for item in self.inzeraty:
            platna = "Kč" in item.cena or "textu" in item.cena.lower() or "Neuvedena" in item.cena
            self.assertTrue(
                platna,
                f"Nečekaný formát ceny: '{item.cena}' (id={item.id})"
            )

    def test_unikatni_ids(self):
        """Každý inzerát musí mít unikátní ID."""
        ids = [i.id for i in self.inzeraty]
        self.assertEqual(
            len(ids), len(set(ids)),
            f"Nalezeny duplicitní ID: {[x for x in ids if ids.count(x) > 1]}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
