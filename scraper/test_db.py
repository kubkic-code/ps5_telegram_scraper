"""
test_db.py — Unit testy pro modul db.py (PS5 Arbitrage Platform)
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
    parsuj_ps5_inzerat,
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
        """Ověří přítomnost všech požadovaných sloupců v tabulce listings.

        Schéma PS5: edition (TEXT), is_slim (BOOLEAN) — parsed_model byl odstraněn.
        """
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(listings);")
        columns = {row[1]: row[2].upper() for row in cursor.fetchall()}

        ocekavane_sloupce = [
            "db_id",
            "item_id",
            "portal",
            "title",
            "standardized_title",  # čistý název z LLM validace
            "edition",    # nový sloupec pro PS5
            "is_slim",    # nový sloupec pro PS5 Slim
            "price",
            "url",
            "found_date",
            "sold_date",
            "status",
        ]

        for col in ocekavane_sloupce:
            self.assertIn(col, columns, f"Sloupec '{col}' chybí v tabulce listings.")

        # Ověříme, že parsed_model NENÍ v novém schématu
        self.assertNotIn("parsed_model", columns,
                         "Sloupec 'parsed_model' byl odstraněn v PS5 schématu.")

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


class TestParsujPs5Inzerat(unittest.TestCase):
    """Testy parsování edice (Disk/Digital/Unknown) a Slim varianty z názvu inzerátu."""

    def test_digital_edition(self):
        """Slova 'digital', 'digitální', 'bez mechaniky' → 'Digital'."""
        self.assertEqual(parsuj_ps5_inzerat("PS5 Digital Edition")[0], "Digital")
        self.assertEqual(parsuj_ps5_inzerat("PlayStation 5 Digitální verze")[0], "Digital")
        self.assertEqual(parsuj_ps5_inzerat("PS5 bez mechaniky")[0], "Digital")
        self.assertEqual(parsuj_ps5_inzerat("Sony PS5 No Disc")[0], "Digital")

    def test_disk_edition(self):
        """Slova 'disk', 'disc', 'mechanik', 'blu-ray' → 'Disk'."""
        self.assertEqual(parsuj_ps5_inzerat("PS5 Disk Edition")[0], "Disk")
        self.assertEqual(parsuj_ps5_inzerat("PlayStation 5 s mechanikou")[0], "Disk")
        self.assertEqual(parsuj_ps5_inzerat("PS5 Blu-ray verze")[0], "Disk")
        self.assertEqual(parsuj_ps5_inzerat("PS5 Disc Edition")[0], "Disk")

    def test_unknown_edition(self):
        """Bez klíčových slov → 'Unknown'."""
        self.assertEqual(parsuj_ps5_inzerat("PS5 konzole")[0], "Unknown")
        self.assertEqual(parsuj_ps5_inzerat("PlayStation 5")[0], "Unknown")
        self.assertEqual(parsuj_ps5_inzerat("")[0], "Unknown")
        self.assertEqual(parsuj_ps5_inzerat(None)[0], "Unknown")

    def test_is_slim_true(self):
        """Slovo 'slim' (case-insensitive) → is_slim = True."""
        self.assertTrue(parsuj_ps5_inzerat("PS5 Slim Digital")[1])
        self.assertTrue(parsuj_ps5_inzerat("PlayStation 5 SLIM")[1])
        self.assertTrue(parsuj_ps5_inzerat("Sony PS5 slim edice")[1])

    def test_is_slim_false(self):
        """Bez 'slim' → is_slim = False."""
        self.assertFalse(parsuj_ps5_inzerat("PS5 Digital Edition")[1])
        self.assertFalse(parsuj_ps5_inzerat("PlayStation 5 Disk")[1])
        self.assertFalse(parsuj_ps5_inzerat("")[1])

    def test_slim_digital_kombinace(self):
        """Kombinace Slim + Digital vrátí ('Digital', True)."""
        edition, is_slim = parsuj_ps5_inzerat("PS5 Slim Digital Edition")
        self.assertEqual(edition, "Digital")
        self.assertTrue(is_slim)

    def test_slim_disk_kombinace(self):
        """Kombinace Slim + Disk vrátí ('Disk', True)."""
        edition, is_slim = parsuj_ps5_inzerat("PS5 Slim Disk Edition")
        self.assertEqual(edition, "Disk")
        self.assertTrue(is_slim)

    def test_case_insensitive(self):
        """Parsování je case-insensitive."""
        self.assertEqual(parsuj_ps5_inzerat("PS5 DIGITAL")[0], "Digital")
        self.assertEqual(parsuj_ps5_inzerat("PS5 DISK")[0], "Disk")
        self.assertTrue(parsuj_ps5_inzerat("PS5 SLIM")[1])


class TestPomocneFunkce(unittest.TestCase):
    """Testy pomocných funkcí určení portálu a parsování ceny."""

    def test_urci_portal_bazos(self):
        inzerat = Inzerat(
            id="123456",
            nazev="PlayStation 5 Slim Digital",
            url="https://www.bazos.cz/inzerat/123456/ps5.php",
            cena="12 000 Kč",
            lokalita="Praha",
            datum="6.9. 2026",
        )
        self.assertEqual(urci_portal(inzerat), "bazos")

    def test_urci_portal_vinted(self):
        inzerat = Inzerat(
            id="vt_987654",
            nazev="PS5 Slim Disk",
            url="https://www.vinted.cz/items/987654-ps5",
            cena="11 500 Kč",
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
    """Testy ukládání inzerátů PS5 a deduplikace dle item_id."""

    def setUp(self):
        self.conn = ziskej_pripojeni(":memory:")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_uloz_novy_inzerat_disk_edition(self):
        """Ověří vložení nového PS5 Disk inzerátu a automatické detekování edition."""
        inzerat = Inzerat(
            id="101010",
            nazev="PlayStation 5 Disk Edition",
            url="https://www.bazos.cz/inzerat/101010/ps5-disk.php",
            cena="13 500 Kč",
            lokalita="Plzeň",
            datum="6.9. 2026",
            popis="Krásná konzole, záruční list v pořádku.",
        )

        ted = datetime.datetime(2026, 9, 6, 15, 30, 0)
        vysledek = uloz_inzerat(
            inzerat,
            db_conn=self.conn,
            status="active",
            found_date=ted,
        )

        self.assertTrue(vysledek, "uloz_inzerat měl vrátit True pro nový záznam.")

        zaznam = nacti_inzerat_dle_item_id("101010", db_conn=self.conn)
        self.assertIsNotNone(zaznam)
        self.assertEqual(zaznam["item_id"], "101010")
        self.assertEqual(zaznam["portal"], "bazos")
        self.assertEqual(zaznam["title"], "PlayStation 5 Disk Edition")
        self.assertEqual(zaznam["edition"], "Disk")
        self.assertEqual(zaznam["is_slim"], 0)
        self.assertEqual(zaznam["price"], 13500)
        self.assertEqual(zaznam["url"], "https://www.bazos.cz/inzerat/101010/ps5-disk.php")
        self.assertEqual(zaznam["found_date"], "2026-09-06 15:30:00")
        self.assertIsNone(zaznam["sold_date"])
        self.assertEqual(zaznam["status"], "active")

    def test_uloz_novy_inzerat_digital_slim(self):
        """Ověří automatickou detekci 'Digital' edice a Slim varianty."""
        inzerat = Inzerat(
            id="202022",
            nazev="PS5 Slim Digital Edition Sony",
            url="https://www.bazos.cz/inzerat/202022/ps5-slim.php",
            cena="11 900 Kč",
            lokalita="Praha",
            datum="6.9. 2026",
        )

        uloz_inzerat(inzerat, db_conn=self.conn)

        zaznam = nacti_inzerat_dle_item_id("202022", db_conn=self.conn)
        self.assertIsNotNone(zaznam)
        self.assertEqual(zaznam["edition"], "Digital")
        self.assertEqual(zaznam["is_slim"], 1)

    def test_uloz_novy_inzerat_unknown_edition(self):
        """Bez klíčových slov = Unknown edice."""
        inzerat = Inzerat(
            id="303033",
            nazev="PS5 konzole super stav",
            url="https://www.bazos.cz/inzerat/303033/ps5.php",
            cena="12 000 Kč",
            lokalita="Brno",
            datum="6.9. 2026",
        )

        uloz_inzerat(inzerat, db_conn=self.conn)

        zaznam = nacti_inzerat_dle_item_id("303033", db_conn=self.conn)
        self.assertEqual(zaznam["edition"], "Unknown")
        self.assertEqual(zaznam["is_slim"], 0)

    def test_uloz_inzerat_s_explicitnim_edition(self):
        """Lze předat edition a is_slim explicitně (přepíše automatickou detekci)."""
        inzerat = Inzerat(
            id="404044",
            nazev="PS5 konzole",  # název bez klíčových slov
            url="https://www.bazos.cz/inzerat/404044/ps5.php",
            cena="10 000 Kč",
            lokalita="Ostrava",
            datum="6.9. 2026",
        )

        uloz_inzerat(inzerat, db_conn=self.conn, edition="Disk", is_slim=True)

        zaznam = nacti_inzerat_dle_item_id("404044", db_conn=self.conn)
        self.assertEqual(zaznam["edition"], "Disk")
        self.assertEqual(zaznam["is_slim"], 1)

    def test_duplicitni_item_id_je_ignorovano(self):
        """Ověří, že duplicitní item_id nevyvolá chybu a vrátí False (ignorováno)."""
        inzerat = Inzerat(
            id="202020",
            nazev="PS5 Disk Edition",
            url="https://www.bazos.cz/inzerat/202020/ps5.php",
            cena="13 000 Kč",
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
            nazev="PS5 Slim Digital",
            url="https://www.vinted.cz/items/303030-ps5",
            cena="11 500 Kč",
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
                nazev="PS5 Disk Edition",
                url="https://www.bazos.cz/inzerat/404041/ps5.php",
                cena="13 500 Kč",
                lokalita="Brno",
                datum="6.9. 2026",
            ),
            Inzerat(
                id="404042",
                nazev="PS5 Slim Digital Edition",
                url="https://www.bazos.cz/inzerat/404042/ps5slim.php",
                cena="11 900 Kč",
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
                nazev="PS5 konzole bez mechaniky",
                url="https://www.bazos.cz/inzerat/404043/ps5digital.php",
                cena="10 000 Kč",
                lokalita="Pardubice",
                datum="6.9. 2026",
            ),
        ]
        pridano_dalsi = uloz_inzeraty_davku(dalsi_davka, db_conn=self.conn)
        self.assertEqual(pridano_dalsi, 1)

        vsechny = nacti_vsechny_inzeraty(db_conn=self.conn)
        self.assertEqual(len(vsechny), 3)

        # Ověř, že davka správně detekovala edice
        zaznam_disk = nacti_inzerat_dle_item_id("404041", db_conn=self.conn)
        self.assertEqual(zaznam_disk["edition"], "Disk")

        zaznam_slim = nacti_inzerat_dle_item_id("404042", db_conn=self.conn)
        self.assertEqual(zaznam_slim["edition"], "Digital")
        self.assertEqual(zaznam_slim["is_slim"], 1)

        zaznam_digital = nacti_inzerat_dle_item_id("404043", db_conn=self.conn)
        self.assertEqual(zaznam_digital["edition"], "Digital")


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
        inz1 = Inzerat("111", "PS5 Disk", "https://bazos.cz/111", "13000 Kč", "Praha", "6.9.")
        inz2 = Inzerat("222", "PS5 Digital", "https://bazos.cz/222", "11500 Kč", "Brno", "6.9.")
        inz3 = Inzerat("333", "PS5 Slim", "https://bazos.cz/333", "12000 Kč", "Plzeň", "6.9.")

        uloz_inzerat(inz1, db_conn=self.conn, status="active")
        uloz_inzerat(inz2, db_conn=self.conn, status="sold")
        uloz_inzerat(inz3, db_conn=self.conn, status="deleted")

        aktivni = nacti_aktivni_inzeraty(db_conn=self.conn)
        self.assertEqual(len(aktivni), 1)
        self.assertEqual(aktivni[0]["item_id"], "111")
        self.assertEqual(aktivni[0]["status"], "active")

    def test_oznac_jako_prodane_s_explicitnim_datem(self):
        """Ověří změnu statusu na 'sold' a uložení zadaného data prodeje."""
        inz = Inzerat("555", "PS5 Disk Edition", "https://bazos.cz/555", "13500 Kč", "Praha", "6.9.")
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
        inz = Inzerat("777", "PS5 Digital", "https://bazos.cz/777", "11000 Kč", "Brno", "6.9.")
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
