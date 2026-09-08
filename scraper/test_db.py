"""
test_db.py — Unit testy pro modul db.py (SQLite analytická platforma)
Python Agent | Role: TDD přístup, testy na in-memory databázi (:memory:)
"""

from __future__ import annotations

import datetime
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from db import (
    DEFAULT_DB_PATH,
    init_db,
    nacti_aktivni_inzeraty,
    nacti_inzerat_dle_item_id,
    nacti_vsechny_inzeraty,
    oznac_jako_prodane,
    parsuj_cenu_na_int,
    uloz_inzerat,
    uloz_inzeraty_davku,
    urci_portal,
    ziskej_pripojeni,
)
from scraper import Inzerat


class TestDbSchemaAInit(unittest.TestCase):
    """Testy inicializace databáze a struktury schématu tabulky listings."""

    def setUp(self):
        self.conn = ziskej_pripojeni(":memory:")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_tabulka_listings_existuje(self):
        """Ověří, že tabulka listings byla v DB úspěšně vytvořena."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='listings';"
        )
        row = cursor.fetchone()
        self.assertIsNotNone(row, "Tabulka 'listings' nebyla v databázi nalezena.")
        self.assertEqual(row[0], "listings")

    def test_sloupce_tabulky_listings(self):
        """Ověří přítomnost všech požadovaných sloupců v tabulce listings."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(listings);")
        columns = {row[1]: row[2].upper() for row in cursor.fetchall()}

        ocekavane_sloupce = [
            "db_id",
            "item_id",
            "portal",
            "title",
            "parsed_model",
            "price",
            "url",
            "found_date",
            "sold_date",
            "status",
        ]

        for col in ocekavane_sloupce:
            self.assertIn(col, columns, f"Sloupec '{col}' chybí v tabulce listings.")

    def test_db_id_je_primary_key(self):
        """Ověří, že db_id je primární klíč."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(listings);")
        rows = cursor.fetchall()
        # row: (cid, name, type, notnull, dflt_value, pk)
        pk_cols = [r[1] for r in rows if r[5] > 0]
        self.assertEqual(pk_cols, ["db_id"])

    def test_idempotentni_init_db(self):
        """Opakované volání init_db nesmí vyvolat výjimku."""
        init_db(self.conn)
        init_db(self.conn)


class TestPomocneFunkce(unittest.TestCase):
    """Testy pomocných funkcí určení portálu a parsování ceny."""

    def test_urci_portal_bazos(self):
        inzerat = Inzerat(
            id="123456",
            nazev="Garmin Fenix 7",
            url="https://www.bazos.cz/inzerat/123456/garmin.php",
            cena="8 000 Kč",
            lokalita="Praha",
            datum="6.9. 2026",
        )
        self.assertEqual(urci_portal(inzerat), "bazos")

    def test_urci_portal_vinted(self):
        inzerat = Inzerat(
            id="vt_987654",
            nazev="Garmin Forerunner 945",
            url="https://www.vinted.cz/items/987654-garmin",
            cena="5 000 Kč",
            lokalita="Brno",
            datum="VT",
        )
        self.assertEqual(urci_portal(inzerat), "vinted")

    def test_parsuj_cenu_na_int_standardni_czk(self):
        self.assertEqual(parsuj_cenu_na_int("8 500 Kč"), 8500)
        self.assertEqual(parsuj_cenu_na_int("12.000 Kč"), 12000)

    def test_parsuj_cenu_na_int_eur(self):
        self.assertEqual(parsuj_cenu_na_int("200 €"), 200)
        self.assertEqual(parsuj_cenu_na_int("1.500,50 €"), 1501)

    def test_parsuj_cenu_na_int_vinted_dve_ceny(self):
        self.assertEqual(parsuj_cenu_na_int("5108.24 Kč, 5381.65 Kč"), 5108)
        self.assertEqual(parsuj_cenu_na_int("4000.00 Kč, 4218.00 Kč"), 4000)
        self.assertEqual(parsuj_cenu_na_int("10227.85 Kč, 10757.24 Kč"), 10228)
        self.assertEqual(parsuj_cenu_na_int("150.00 €, 170.00 €"), 150)

    def test_parsuj_cenu_na_int_ciselny_vstup(self):
        self.assertEqual(parsuj_cenu_na_int(7500), 7500)
        self.assertEqual(parsuj_cenu_na_int(7500.8), 7501)

    def test_parsuj_cenu_na_int_neuvedena_nebo_neplatna(self):
        self.assertIsNone(parsuj_cenu_na_int("Neuvedena"))
        self.assertIsNone(parsuj_cenu_na_int("V textu"))
        self.assertIsNone(parsuj_cenu_na_int("Dohodou"))
        self.assertIsNone(parsuj_cenu_na_int(""))
        self.assertIsNone(parsuj_cenu_na_int(None))


class TestUlozInzerat(unittest.TestCase):
    """Testy ukládání inzerátů a deduplikace dle item_id."""

    def setUp(self):
        self.conn = ziskej_pripojeni(":memory:")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_uloz_novy_inzerat_uspech(self):
        """Ověří vložení nového inzerátu a jeho hodnot v DB."""
        inzerat = Inzerat(
            id="101010",
            nazev="Garmin Fenix 7 Pro Sapphire",
            url="https://www.bazos.cz/inzerat/101010/garmin-fenix.php",
            cena="11 500 Kč",
            lokalita="Plzeň",
            datum="6.9. 2026",
            popis="Krásné hodinky v záruce.",
        )

        ted = datetime.datetime(2026, 9, 6, 15, 30, 0)
        vysledek = uloz_inzerat(
            inzerat,
            db_conn=self.conn,
            status="active",
            found_date=ted,
            parsed_model="Fenix 7 Pro",
        )

        self.assertTrue(vysledek, "uloz_inzerat měl vrátit True pro nový záznam.")

        zaznam = nacti_inzerat_dle_item_id("101010", db_conn=self.conn)
        self.assertIsNotNone(zaznam)
        self.assertEqual(zaznam["item_id"], "101010")
        self.assertEqual(zaznam["portal"], "bazos")
        self.assertEqual(zaznam["title"], "Garmin Fenix 7 Pro Sapphire")
        self.assertEqual(zaznam["parsed_model"], "Fenix 7 Pro")
        self.assertEqual(zaznam["price"], 11500)
        self.assertEqual(zaznam["url"], "https://www.bazos.cz/inzerat/101010/garmin-fenix.php")
        self.assertEqual(zaznam["found_date"], "2026-09-06 15:30:00")
        self.assertIsNone(zaznam["sold_date"])
        self.assertEqual(zaznam["status"], "active")

    def test_duplicitni_item_id_je_ignorovano(self):
        """Ověří, že duplicitní item_id nevyvolá chybu a vrátí False (ignorováno)."""
        inzerat = Inzerat(
            id="202020",
            nazev="Garmin Epix Gen 2",
            url="https://www.bazos.cz/inzerat/202020/epix.php",
            cena="10 000 Kč",
            lokalita="Ostrava",
            datum="6.9. 2026",
        )

        prvni = uloz_inzerat(inzerat, db_conn=self.conn)
        self.assertTrue(prvni)

        # Druhé vložení se stejným item_id
        druhy = uloz_inzerat(inzerat, db_conn=self.conn)
        self.assertFalse(druhy, "Druhý pokus se stejným item_id měl vrátit False.")

        # V DB musí být stále pouze 1 záznam
        vsechny = nacti_vsechny_inzeraty(db_conn=self.conn)
        self.assertEqual(len(vsechny), 1)

    def test_uloz_inzerat_vychozi_datum_a_status(self):
        """Bez explicitního data se nastaví aktuální datum a status 'active'."""
        inzerat = Inzerat(
            id="vt_303030",
            nazev="Garmin Instinct 2 Solar",
            url="https://www.vinted.cz/items/303030-garmin-instinct",
            cena="4 500 Kč",
            lokalita="Liberec",
            datum="VT",
        )

        vysledek = uloz_inzerat(inzerat, db_conn=self.conn)
        self.assertTrue(vysledek)

        zaznam = nacti_inzerat_dle_item_id("vt_303030", db_conn=self.conn)
        self.assertEqual(zaznam["portal"], "vinted")
        self.assertEqual(zaznam["status"], "active")
        self.assertIsNotNone(zaznam["found_date"])
        self.assertIn("-", zaznam["found_date"])  # YYYY-MM-DD formát

    def test_uloz_inzeraty_davku(self):
        """Ověří uložení celé dávky inzerátů a vrácení počtu nově přidaných."""
        inzeraty = [
            Inzerat(
                id="404041",
                nazev="Garmin Venu 3",
                url="https://www.bazos.cz/inzerat/404041/venu.php",
                cena="6 500 Kč",
                lokalita="Brno",
                datum="6.9. 2026",
            ),
            Inzerat(
                id="404042",
                nazev="Garmin Fenix 6 Pro",
                url="https://www.bazos.cz/inzerat/404042/fenix6.php",
                cena="5 500 Kč",
                lokalita="Praha",
                datum="6.9. 2026",
            ),
        ]

        pridano = uloz_inzeraty_davku(inzeraty, db_conn=self.conn)
        self.assertEqual(pridano, 2)

        # Přidáme dávku se starým i novým inzerátem
        dalsi_davka = [
            inzeraty[0],  # již existuje
            Inzerat(
                id="404043",
                nazev="Garmin Tactix 7",
                url="https://www.bazos.cz/inzerat/404043/tactix.php",
                cena="15 000 Kč",
                lokalita="Pardubice",
                datum="6.9. 2026",
            ),
        ]
        pridano_dalsi = uloz_inzeraty_davku(dalsi_davka, db_conn=self.conn)
        self.assertEqual(pridano_dalsi, 1)

        vsechny = nacti_vsechny_inzeraty(db_conn=self.conn)
        self.assertEqual(len(vsechny), 3)


class TestAktivniAProdaneInzeraty(unittest.TestCase):
    """Testy pro načítání aktivních inzerátů a označování jako prodané."""

    def setUp(self):
        self.conn = ziskej_pripojeni(":memory:")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_nacti_aktivni_inzeraty_prazdna_db(self):
        """V prázdné DB vrátí prázdný seznam."""
        aktivni = nacti_aktivni_inzeraty(db_conn=self.conn)
        self.assertEqual(aktivni, [])

    def test_nacti_aktivni_inzeraty_vraci_pouze_status_active(self):
        """Ověří, že funkce filtruje pouze inzeráty se statusem 'active'."""
        inz1 = Inzerat("111", "Garmin 1", "https://bazos.cz/111", "5000 Kč", "Praha", "6.9.")
        inz2 = Inzerat("222", "Garmin 2", "https://bazos.cz/222", "6000 Kč", "Brno", "6.9.")
        inz3 = Inzerat("333", "Garmin 3", "https://bazos.cz/333", "7000 Kč", "Plzeň", "6.9.")

        uloz_inzerat(inz1, db_conn=self.conn, status="active")
        uloz_inzerat(inz2, db_conn=self.conn, status="sold")
        uloz_inzerat(inz3, db_conn=self.conn, status="deleted")

        aktivni = nacti_aktivni_inzeraty(db_conn=self.conn)
        self.assertEqual(len(aktivni), 1)
        self.assertEqual(aktivni[0]["item_id"], "111")
        self.assertEqual(aktivni[0]["status"], "active")

    def test_oznac_jako_prodane_s_explicitnim_datem(self):
        """Ověří změnu statusu na 'sold' a uložení zadaného data prodeje."""
        inz = Inzerat("555", "Garmin Fenix 7", "https://bazos.cz/555", "8000 Kč", "Praha", "6.9.")
        uloz_inzerat(inz, db_conn=self.conn, status="active")

        zaznam = nacti_inzerat_dle_item_id("555", db_conn=self.conn)
        db_id = zaznam["db_id"]

        prodano_datum = datetime.datetime(2026, 9, 6, 18, 0, 0)
        uspech = oznac_jako_prodane(db_id, sold_date=prodano_datum, db_conn=self.conn)
        self.assertTrue(uspech)

        aktualizovany = nacti_inzerat_dle_item_id("555", db_conn=self.conn)
        self.assertEqual(aktualizovany["status"], "sold")
        self.assertEqual(aktualizovany["sold_date"], "2026-09-06 18:00:00")

    def test_oznac_jako_prodane_s_vychozim_datem(self):
        """Pokud sold_date není zadáno, doplní se aktuální datum a čas."""
        inz = Inzerat("777", "Garmin Epix", "https://bazos.cz/777", "9000 Kč", "Brno", "6.9.")
        uloz_inzerat(inz, db_conn=self.conn, status="active")

        zaznam = nacti_inzerat_dle_item_id("777", db_conn=self.conn)
        db_id = zaznam["db_id"]

        uspech = oznac_jako_prodane(db_id, db_conn=self.conn)
        self.assertTrue(uspech)

        aktualizovany = nacti_inzerat_dle_item_id("777", db_conn=self.conn)
        self.assertEqual(aktualizovany["status"], "sold")
        self.assertIsNotNone(aktualizovany["sold_date"])
        self.assertIn("-", aktualizovany["sold_date"])

    def test_oznac_jako_prodane_neexistujici_id(self):
        """Neexistující db_id vrátí False."""
        uspech = oznac_jako_prodane(999999, db_conn=self.conn)
        self.assertFalse(uspech)


class TestCestaADefault(unittest.TestCase):
    """Test výchozí cesty k DB."""

    def test_default_db_path(self):
        self.assertEqual(str(DEFAULT_DB_PATH).replace("\\", "/"), "/data/market.db")


if __name__ == "__main__":
    unittest.main(verbosity=2)
