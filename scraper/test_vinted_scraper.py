"""
test_vinted_scraper.py — Unit testy pro vinted_scraper.py
DevOps Agent | TDD smyčka — ŽÁDNÝ HTTP request na reálný Vinted.
Testy čtou VÝHRADNĚ lokální HTML fixture: fixtures/vinted_ps5.html
"""

import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from scraper import Inzerat
from vinted_scraper import (
    parsuj_html_vinted,
    _extrahuj_vinted_id_z_url,
    _ocisti_cenu,
    ID_PREFIX,
    SEARCH_URL,
    SEARCH_URLS,
)

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "vinted_ps5.html"


def nacti_fixture() -> str:
    """Načte lokální HTML fixture. Test selže, pokud soubor neexistuje."""
    if not FIXTURE_PATH.exists():
        raise FileNotFoundError(
            f"Fixture nenalezena: {FIXTURE_PATH}\n"
            "Zkontroluj, zda soubor fixtures/vinted_ps5.html existuje."
        )
    return FIXTURE_PATH.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Testy pomocných funkcí
# ---------------------------------------------------------------------------

class TestExtrahujVintedId(unittest.TestCase):
    """Testy pro _extrahuj_vinted_id_z_url."""

    def test_standardni_url_relativni(self):
        url = "/items/4567890001-playstation-5-disk-edition"
        self.assertEqual(_extrahuj_vinted_id_z_url(url), "vt_4567890001")

    def test_absolutni_url(self):
        url = "https://www.vinted.cz/items/987654321-ps5-digital"
        self.assertEqual(_extrahuj_vinted_id_z_url(url), "vt_987654321")

    def test_url_bez_items(self):
        url = "https://www.vinted.cz/catalog?search_text=ps5"
        self.assertEqual(_extrahuj_vinted_id_z_url(url), "")

    def test_prazdny_retezec(self):
        self.assertEqual(_extrahuj_vinted_id_z_url(""), "")

    def test_prefix_je_vt(self):
        url = "/items/123456-ps5"
        vysledek = _extrahuj_vinted_id_z_url(url)
        self.assertTrue(vysledek.startswith(ID_PREFIX))


class TestOcistiCenu(unittest.TestCase):

    def test_normalni_cena(self):
        self.assertEqual(_ocisti_cenu("  5 000 Kč  "), "5 000 Kč")

    def test_prazdna_cena(self):
        self.assertEqual(_ocisti_cenu(""), "Neuvedena")

    def test_cena_s_mezerami(self):
        self.assertEqual(_ocisti_cenu("  "), "Neuvedena")

    def test_zdarma(self):
        self.assertEqual(_ocisti_cenu("Zdarma"), "Zdarma")


# ---------------------------------------------------------------------------
# Testy parsování HTML
# ---------------------------------------------------------------------------

class TestParsujHtmlVinted(unittest.TestCase):
    """Testy pro hlavní parsovací funkci parsuj_html_vinted()."""

    @classmethod
    def setUpClass(cls):
        """Načte fixture jednou pro všechny testy — žádný HTTP."""
        cls.html = nacti_fixture()
        cls.inzeraty = parsuj_html_vinted(cls.html)

    # --- Základní smoke testy ---

    def test_vraci_seznam(self):
        self.assertIsInstance(self.inzeraty, list)

    def test_nenulovy_pocet(self):
        self.assertGreater(
            len(self.inzeraty), 0,
            "Parser nenašel žádné inzeráty z fixture."
        )

    def test_minimalne_5_inzeratu(self):
        """Fixture obsahuje 11 inzerátů — chceme alespoň 5."""
        self.assertGreaterEqual(
            len(self.inzeraty), 5,
            f"Očekáváno ≥5 inzerátů, nalezeno {len(self.inzeraty)}."
        )

    # --- Datový model ---

    def test_vraci_instance_inzerat(self):
        for item in self.inzeraty:
            self.assertIsInstance(item, Inzerat, f"Nečekaný typ: {type(item)}")

    def test_id_ma_vt_prefix(self):
        for item in self.inzeraty:
            self.assertTrue(
                item.id.startswith("vt_"),
                f"ID '{item.id}' nemá prefix 'vt_' (inzerát: {item.nazev!r})"
            )

    def test_nazev_neprazdny(self):
        for item in self.inzeraty:
            self.assertTrue(
                len(item.nazev) >= 3,
                f"Příliš krátký nebo prázdný název pro id={item.id}"
            )

    def test_url_je_absolutni(self):
        for item in self.inzeraty:
            self.assertTrue(
                item.url.startswith("http"),
                f"URL není absolutní: {item.url!r} (id={item.id})"
            )

    def test_url_obsahuje_items(self):
        for item in self.inzeraty:
            self.assertIn(
                "/items/", item.url,
                f"URL neobsahuje /items/: {item.url!r} (id={item.id})"
            )

    def test_cena_neprazdna(self):
        for item in self.inzeraty:
            self.assertTrue(
                len(item.cena) > 0,
                f"Prázdná cena pro id={item.id}"
            )

    def test_datum_je_vt(self):
        """Vinted neukazuje datum na listingu — datum = 'VT'."""
        for item in self.inzeraty:
            self.assertEqual(
                item.datum, "VT",
                f"Datum by mělo být 'VT', je '{item.datum}' (id={item.id})"
            )

    def test_unikatni_ids(self):
        """Každý inzerát musí mít unikátní ID."""
        ids = [i.id for i in self.inzeraty]
        self.assertEqual(
            len(ids), len(set(ids)),
            f"Nalezeny duplicitní ID: {[x for x in ids if ids.count(x) > 1]}"
        )

    # --- Konkrétní inzeráty ze fixture ---

    def test_ps5_disk_nalezen(self):
        """Fixture obsahuje PS5 Disk — musí být naparsován."""
        nazvy = [i.nazev.lower() for i in self.inzeraty]
        self.assertTrue(
            any("disk" in n for n in nazvy),
            "Inzerát PS5 Disk nebyl nalezen v parsovaných výsledcích."
        )

    def test_ps5_slim_nalezen(self):
        nazvy = [i.nazev.lower() for i in self.inzeraty]
        self.assertTrue(
            any("slim" in n for n in nazvy),
            "Inzerát PS5 Slim nebyl nalezen."
        )

    def test_cena_obsahuje_kc(self):
        """Alespoň jeden inzerát musí mít cenu v Kč."""
        ceny_s_kc = [i for i in self.inzeraty if "Kč" in i.cena]
        self.assertGreater(
            len(ceny_s_kc), 0,
            "Žádný inzerát nemá cenu v Kč."
        )

    def test_konkretni_id_ps5(self):
        """Fixture ID 4567890001 (PS5 Disk) musí být naparsován."""
        ids = [i.id for i in self.inzeraty]
        self.assertIn("vt_4567890001", ids, "ID vt_4567890001 (PS5 Disk) nenalezeno.")


# ---------------------------------------------------------------------------
# Test parsování prázdného HTML
# ---------------------------------------------------------------------------

class TestParsujHtmlVintedPrazdny(unittest.TestCase):

    def test_prazdny_html(self):
        vysledky = parsuj_html_vinted("<html><body></body></html>")
        self.assertEqual(vysledky, [])

    def test_html_bez_inzeratu(self):
        html = "<html><body><div>Žádné výsledky</div></body></html>"
        vysledky = parsuj_html_vinted(html)
        self.assertEqual(vysledky, [])

    def test_html_s_jednim_inzeratem(self):
        html = """
        <html><body>
          <a href="/items/999000001-ps5-test">
            <img alt="PlayStation 5 Test" />
            <span data-testid="description-title">PlayStation 5 Test</span>
            <span data-testid="price-text">8 500 Kč</span>
          </a>
        </body></html>
        """
        vysledky = parsuj_html_vinted(html)
        self.assertEqual(len(vysledky), 1)
        self.assertEqual(vysledky[0].id, "vt_999000001")
        self.assertEqual(vysledky[0].nazev, "PlayStation 5 Test")
        self.assertEqual(vysledky[0].cena, "8 500 Kč")

    def test_inzerat_pouze_se_znackou_sony(self):
        """Pokud prodejce vyplnil pouze Značku, scraper ji bezpečně použije jako název."""
        html = """
        <html><body>
          <div data-testid="grid-item">
            <a href="/items/888111001-item">
              <span data-testid="description-title">Sony</span>
              <span data-testid="price-text">8 500 Kč</span>
            </a>
          </div>
        </body></html>
        """
        vysledky = parsuj_html_vinted(html)
        self.assertEqual(len(vysledky), 1)
        self.assertEqual(vysledky[0].nazev, "Sony")
        self.assertEqual(vysledky[0].cena, "8 500 Kč")

    def test_inzerat_se_znackou_v_item_brand(self):
        """Scraper detekuje Značku i z elementu item-brand a sloučí ji s modelem."""
        html = """
        <html><body>
          <div data-testid="grid-item">
            <a href="/items/888222002-item">
              <span data-testid="item-brand">Sony</span>
              <span data-testid="description-subtitle">PlayStation 5</span>
              <span data-testid="price-text">9 200 Kč</span>
            </a>
          </div>
        </body></html>
        """
        vysledky = parsuj_html_vinted(html)
        self.assertEqual(len(vysledky), 1)
        self.assertEqual(vysledky[0].nazev, "Sony PlayStation 5")

    def test_inzerat_s_oddelenou_znackou_a_modelem(self):
        """Pokud description-title má Sony a subtitle PS5 Slim, název je 'Sony PS5 Slim'."""
        html = """
        <html><body>
          <div data-testid="grid-item">
            <a href="/items/888333003-item">
              <span data-testid="description-title">Sony</span>
              <span data-testid="description-subtitle">PS5 Slim</span>
              <span data-testid="price-text">8 900 Kč</span>
            </a>
          </div>
        </body></html>
        """
        vysledky = parsuj_html_vinted(html)
        self.assertEqual(len(vysledky), 1)
        self.assertEqual(vysledky[0].nazev, "Sony PS5 Slim")


# ---------------------------------------------------------------------------
# Testy konfigurace vyhledávací URL
# ---------------------------------------------------------------------------

class TestVintedSearchUrl(unittest.TestCase):
    """Ověření, že vyhledávací URL stahuje plošně všechny kategorie bez omezení."""

    def test_search_url_je_plosna_bez_kategorie(self):
        self.assertEqual(
            SEARCH_URL,
            "https://www.vinted.cz/catalog?search_text=ps5&order=newest_first",
        )
        self.assertNotIn("catalog[]", SEARCH_URL)
        self.assertIn("search_text=ps5", SEARCH_URL)
        self.assertIn("order=newest_first", SEARCH_URL)

    def test_search_urls_obsahuje_pouze_jedinou_plosnou_url(self):
        self.assertEqual(len(SEARCH_URLS), 1)
        self.assertEqual(SEARCH_URLS[0], SEARCH_URL)


class TestVintedKompozitniText(unittest.TestCase):
    """Testy pro rozbalení kompozitních řetězců Vintedu (Značka, Stav, Velikost, cena na konci)."""

    def test_parsovani_kompozitniho_html(self):
        """Ověří, že HTML s kompozitním title/alt správně extrahuje čistý název, cenu i popis."""
        html = """
        <div data-testid="feed-grid">
          <div data-testid="grid-item">
            <a href="/items/9921837573-sony-ps5-slim-1tb"
               title="Sony PS5 Slim 1TB, Značka: Sony, Stav: Velmi dobrý, 9299.00 Kč, 9781.95 Kč">
              <img alt="Sony PS5 Slim 1TB, Značka: Sony, Stav: Velmi dobrý, 9299.00 Kč, 9781.95 Kč" src="/img/ps5slim.jpg" />
            </a>
          </div>
        </div>
        """
        inzeraty = parsuj_html_vinted(html)
        self.assertEqual(len(inzeraty), 1)
        self.assertEqual(inzeraty[0].id, "vt_9921837573")
        self.assertEqual(inzeraty[0].nazev, "Sony PS5 Slim 1TB")
        self.assertEqual(inzeraty[0].cena, "9299.00 Kč")
        self.assertIn("Stav: Velmi dobrý", inzeraty[0].popis or "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
