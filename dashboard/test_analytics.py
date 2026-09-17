"""
test_analytics.py — Unit testy pro analytické funkce dashboardu PS5
Python Agent | Role: TDD přístup pro edice, mediány, kalkulačku profitu a KPI
"""

from __future__ import annotations

import datetime
import sqlite3
import unittest
from pathlib import Path

import pandas as pd

from dashboard.analytics import (
    exportuj_do_csv_excel,
    nacti_data_df,
    nacti_prodana_data_df,
    spocti_agregace_edice,
    spocti_kpi,
    spocti_median_ceny_dle_edice,
    top_edice_ceny,
    vypocti_profit_aktivnich,
)
from db import init_db, uloz_inzerat, ziskej_pripojeni
from scraper import Inzerat


class TestSpoctiKpi(unittest.TestCase):
    """Testy výpočtu klíčových metrik (KPI)."""

    def test_spocti_kpi_prazdny_dataframe(self):
        df = pd.DataFrame(columns=["status", "doba_prodeje_hodin"])
        kpi = spocti_kpi(df)
        self.assertEqual(kpi["pocet_aktivnich"], 0)
        self.assertEqual(kpi["pocet_prodanych"], 0)
        self.assertEqual(kpi["median_doby_hodin"], 0.0)

    def test_spocti_kpi_s_daty(self):
        data = {
            "status": ["active", "active", "sold", "sold", "sold", "deleted"],
            "doba_prodeje_hodin": [None, None, 10.0, 20.0, 30.0, None],
        }
        df = pd.DataFrame(data)
        kpi = spocti_kpi(df)
        self.assertEqual(kpi["pocet_aktivnich"], 2)
        self.assertEqual(kpi["pocet_prodanych"], 3)
        self.assertEqual(kpi["median_doby_hodin"], 20.0)


class TestSpoctiMedianCenyDleEdice(unittest.TestCase):
    """Testy výpočtu mediánových cen dle edice PS5."""

    def test_prazdny_dataframe(self):
        """Prázdný DF vrátí None pro všechny edice."""
        df = pd.DataFrame(columns=["status", "edition", "price"])
        mediany = spocti_median_ceny_dle_edice(df)
        self.assertIsNone(mediany["Disk"])
        self.assertIsNone(mediany["Digital"])
        self.assertIsNone(mediany["Unknown"])

    def test_median_ze_soumestnich_dat(self):
        """Medián z prodaných dat (>=3 záznamy) je počítán z prodaných."""
        data = {
            "status": ["sold", "sold", "sold", "active", "active"],
            "edition": ["Disk", "Disk", "Disk", "Disk", "Disk"],
            "price": [12000, 14000, 13000, 11000, 10000],  # aktivní nesmí ovlivnit sold medián
            "doba_prodeje_hodin": [24.0, 48.0, 12.0, None, None],
        }
        df = pd.DataFrame(data)
        mediany = spocti_median_ceny_dle_edice(df)
        # sold: 12000, 13000, 14000 → medián = 13000
        self.assertEqual(mediany["Disk"], 13000.0)

    def test_median_disk_a_digital_oddelene(self):
        """Medián se počítá zvlášť pro Disk a Digital edici."""
        data = {
            "status": ["sold", "sold", "sold", "sold", "sold", "sold"],
            "edition": ["Disk", "Disk", "Disk", "Digital", "Digital", "Digital"],
            "price": [12000, 13000, 14000, 10000, 11000, 12000],
            "doba_prodeje_hodin": [12.0] * 6,
        }
        df = pd.DataFrame(data)
        mediany = spocti_median_ceny_dle_edice(df)
        self.assertEqual(mediany["Disk"], 13000.0)    # medián z 12000, 13000, 14000
        self.assertEqual(mediany["Digital"], 11000.0)  # medián z 10000, 11000, 12000

    def test_fallback_na_vsechna_data_pri_malo_prodanych(self):
        """Pokud jsou méně než 3 prodané záznamy, použijeme všechna data."""
        data = {
            "status": ["sold", "sold", "active", "active"],  # jen 2 sold
            "edition": ["Digital", "Digital", "Digital", "Digital"],
            "price": [10000, 12000, 9000, 11000],
        }
        df = pd.DataFrame(data)
        mediany = spocti_median_ceny_dle_edice(df)
        # Méně než 3 sold → medián ze všech 4: 9000, 10000, 11000, 12000 → 10500
        self.assertEqual(mediany["Digital"], 10500.0)


class TestVypoctiProfitAktivnich(unittest.TestCase):
    """Testy výpočtu profitu aktivních inzerátů."""

    def test_profit_vypocet(self):
        """Profit = Medián edice − Cena inzerátu."""
        aktivni_df = pd.DataFrame({
            "edition": ["Disk", "Digital", "Disk"],
            "price": [10000, 9000, 12000],
            "status": ["active", "active", "active"],
        })
        mediany = {"Disk": 13000.0, "Digital": 11000.0, "Unknown": None}

        df_s_profitem = vypocti_profit_aktivnich(aktivni_df, mediany)

        self.assertIn("profit_czk", df_s_profitem.columns)
        self.assertEqual(df_s_profitem.iloc[0]["profit_czk"], 3000)   # 13000 - 10000
        self.assertEqual(df_s_profitem.iloc[1]["profit_czk"], 2000)   # 11000 - 9000
        self.assertEqual(df_s_profitem.iloc[2]["profit_czk"], 1000)   # 13000 - 12000

    def test_profit_unknown_pouziva_digital_median(self):
        """Unknown edice používá konzervativně Digital medián (bezpečnostní polštář)."""
        aktivni_df = pd.DataFrame({
            "edition": ["Unknown"],
            "price": [8000],
            "status": ["active"],
        })
        # Unknown má svůj medián 13000, ale NESMÍ ho použít — použije Digital 11000
        mediany = {"Disk": 13000.0, "Digital": 11000.0, "Unknown": 13000.0}

        df_s_profitem = vypocti_profit_aktivnich(aktivni_df, mediany)
        # Očekáváme: 11000 - 8000 = 3000 (Digital medián, NE Disk)
        self.assertEqual(df_s_profitem.iloc[0]["profit_czk"], 3000)

    def test_profit_unknown_bez_digital_je_none(self):
        """Pokud Digital medián neexistuje, profit pro Unknown = None."""
        aktivni_df = pd.DataFrame({
            "edition": ["Unknown"],
            "price": [10000],
            "status": ["active"],
        })
        mediany = {"Disk": 13000.0, "Digital": None, "Unknown": None}

        df_s_profitem = vypocti_profit_aktivnich(aktivni_df, mediany)
        self.assertIsNone(df_s_profitem.iloc[0]["profit_czk"])

    def test_profit_prazdny_dataframe(self):
        """Prázdný DF vrátí prázdný DF s profit_czk sloupcem."""
        df = pd.DataFrame(columns=["edition", "price", "status"])
        mediany = {"Disk": 13000.0, "Digital": 11000.0, "Unknown": None}
        df_vysledek = vypocti_profit_aktivnich(df, mediany)
        self.assertIn("profit_czk", df_vysledek.columns)
        self.assertTrue(df_vysledek.empty)

    def test_profit_negativni(self):
        """Negativní profit (cena nad mediánem) je platný záporný výsledek."""
        aktivni_df = pd.DataFrame({
            "edition": ["Disk"],
            "price": [15000],  # nad mediánem 13000
            "status": ["active"],
        })
        mediany = {"Disk": 13000.0, "Digital": 11000.0, "Unknown": None}
        df_s_profitem = vypocti_profit_aktivnich(aktivni_df, mediany)
        self.assertEqual(df_s_profitem.iloc[0]["profit_czk"], -2000)  # 13000 - 15000


class TestAgregaceEdice(unittest.TestCase):
    """Testy agregace cen a likvidity podle edice PS5."""

    def test_spocti_agregace_edice_prazdny(self):
        df = pd.DataFrame(columns=["status", "edition", "price", "doba_prodeje_hodin"])
        agregovany = spocti_agregace_edice(df)
        self.assertTrue(agregovany.empty)
        self.assertIn("edition", agregovany.columns)

    def test_spocti_agregace_edice_spravne_vypocty(self):
        data = {
            "status": ["sold", "sold", "sold", "active"],
            "edition": ["Disk", "Disk", "Digital", "Disk"],
            "price": [12000, 14000, 10000, 13000],  # active nesmí ovlivnit průměr sold!
            "doba_prodeje_hodin": [24.0, 48.0, 12.0, None],
        }
        df = pd.DataFrame(data)
        agregovany = spocti_agregace_edice(df)

        self.assertEqual(len(agregovany), 2)

        # Disk má 2 prodané
        disk_row = agregovany[agregovany["edition"] == "Disk"].iloc[0]
        self.assertEqual(disk_row["pocet_prodano"], 2)
        self.assertEqual(disk_row["prumerna_cena"], 13000)  # (12000 + 14000) / 2
        self.assertEqual(disk_row["median_cena"], 13000)    # medián z 12000, 14000 = 13000
        self.assertEqual(disk_row["prumerna_doba_hodin"], 36.0)  # (24 + 48) / 2

        # Digital má 1 prodanou
        digital_row = agregovany[agregovany["edition"] == "Digital"].iloc[0]
        self.assertEqual(digital_row["pocet_prodano"], 1)
        self.assertEqual(digital_row["prumerna_cena"], 10000)

    def test_top_edice_ceny(self):
        data = {
            "edition": ["Disk", "Digital", "Unknown"],
            "pocet_prodano": [50, 30, 5],
            "prumerna_cena": [13000, 11000, 9000],
            "median_cena": [13000, 11000, 9000],
            "prumerna_doba_hodin": [24.0, 18.0, 48.0],
        }
        df = pd.DataFrame(data)
        top2 = top_edice_ceny(df, n=2)
        self.assertEqual(len(top2), 2)
        self.assertEqual(top2.iloc[0]["edition"], "Disk")


class TestNactiDataDf(unittest.TestCase):
    """Testy načítání dat z SQLite databáze do DataFrame."""

    def setUp(self):
        self.conn = ziskej_pripojeni(":memory:")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_nacti_data_df_vytvori_pozadovane_sloupce(self):
        inz = Inzerat(
            id="9911",
            nazev="PS5 Disk Edition Sony",
            url="https://bazos.cz/9911",
            cena="13 500 Kč",
            lokalita="Praha",
            datum="6.9.",
        )
        uloz_inzerat(
            inz,
            db_conn=self.conn,
            status="sold",
            found_date=datetime.datetime(2026, 9, 6, 10, 0, 0),
            sold_date=datetime.datetime(2026, 9, 6, 22, 0, 0),
        )

        df = nacti_data_df(db_conn=self.conn)
        self.assertFalse(df.empty)
        self.assertEqual(len(df), 1)
        self.assertIn("edition", df.columns)
        self.assertIn("is_slim", df.columns)
        self.assertIn("doba_prodeje_hodin", df.columns)
        # Ověří automatickou detekci edice
        self.assertEqual(df.iloc[0]["edition"], "Disk")
        self.assertAlmostEqual(df.iloc[0]["doba_prodeje_hodin"], 12.0)

    def test_nacti_data_df_slim_digital(self):
        """Ověří, že is_slim je správně načteno z DB."""
        inz = Inzerat(
            id="9922",
            nazev="PS5 Slim Digital Edition",
            url="https://bazos.cz/9922",
            cena="11 900 Kč",
            lokalita="Brno",
            datum="6.9.",
        )
        uloz_inzerat(
            inz,
            db_conn=self.conn,
            status="active",
        )

        df = nacti_data_df(db_conn=self.conn)
        self.assertFalse(df.empty)
        self.assertEqual(df.iloc[0]["edition"], "Digital")
        self.assertTrue(df.iloc[0]["is_slim"])

    def test_nacti_data_df_prazdna_db(self):
        """Prázdná DB vrátí prázdný DF se všemi sloupci."""
        df = nacti_data_df(db_conn=self.conn)
        self.assertTrue(df.empty)


class TestNactiProdanaDataDf(unittest.TestCase):
    """Testy načítání výhradně prodaných inzerátů PS5 (status = 'sold')."""

    def setUp(self):
        self.conn = ziskej_pripojeni(":memory:")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_nacti_pouze_prodane_inzeraty(self):
        # 1. PS5 Disk prodaná
        inz_sold = Inzerat(
            id="1001",
            nazev="PS5 Disk Edition",
            url="https://bazos.cz/1001",
            cena="13 000 Kč",
            lokalita="Brno",
            datum="5.9.",
        )
        uloz_inzerat(
            inz_sold,
            db_conn=self.conn,
            status="sold",
            found_date=datetime.datetime(2026, 9, 5, 10, 0, 0),
            sold_date=datetime.datetime(2026, 9, 6, 12, 0, 0),
        )

        # 2. PS5 Digital aktivní (nesmí být načtena)
        inz_active = Inzerat(
            id="1002",
            nazev="PS5 Digital Edition",
            url="https://bazos.cz/1002",
            cena="10 500 Kč",
            lokalita="Praha",
            datum="6.9.",
        )
        uloz_inzerat(
            inz_active,
            db_conn=self.conn,
            status="active",
            found_date=datetime.datetime(2026, 9, 6, 15, 0, 0),
        )

        # Načtení pouze prodaných
        df = nacti_prodana_data_df(db_conn=self.conn)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["item_id"], "1001")
        self.assertEqual(df.iloc[0]["status"], "sold")
        self.assertEqual(df.iloc[0]["title"], "PS5 Disk Edition")
        self.assertEqual(df.iloc[0]["price"], 13000)
        self.assertEqual(df.iloc[0]["edition"], "Disk")

    def test_nacti_prodana_data_prazdna_db(self):
        df = nacti_prodana_data_df(db_conn=self.conn)
        self.assertTrue(df.empty)


class TestExportujDoCsvExcel(unittest.TestCase):
    """Testy generování CSV souboru pro Microsoft Excel s kódováním UTF-8-SIG."""

    def test_csv_ma_utf8_bom_a_oddelovac(self):
        df = pd.DataFrame({
            "edition": ["Disk", "Digital"],
            "title": ["PS5 Disk Edition v zárukou", "PS5 Digital bez mechaniky"],
            "price": [13500, 10500],
        })

        csv_bytes = exportuj_do_csv_excel(df, sep=";", encoding="utf-8-sig")

        # Musí začínat UTF-8 BOM bajty (\xef\xbb\xbf)
        self.assertTrue(csv_bytes.startswith(b"\xef\xbb\xbf"))

        # Dekódování textu pomocí utf-8-sig
        text = csv_bytes.decode("utf-8-sig")
        self.assertIn("PS5 Disk Edition v zárukou", text)
        self.assertIn("PS5 Digital bez mechaniky", text)

        # Ověření oddělovače středník
        radky = text.strip().splitlines()
        self.assertIn(";", radky[0])
        self.assertEqual(radky[0], "edition;title;price")

    def test_csv_prazdny_dataframe(self):
        df = pd.DataFrame(columns=["edition", "price"])
        csv_bytes = exportuj_do_csv_excel(df, sep=";")
        self.assertTrue(csv_bytes.startswith(b"\xef\xbb\xbf"))
        text = csv_bytes.decode("utf-8-sig")
        self.assertEqual(text.strip(), "edition;price")


class TestDashboardAppStructure(unittest.TestCase):
    """Ověření, že v app.py existují požadované komponenty pro PS5 dashboard."""

    def test_app_py_obsahuje_pozadovane_elementy(self):
        app_path = Path(__file__).resolve().parent / "app.py"
        self.assertTrue(app_path.exists())
        content = app_path.read_text(encoding="utf-8")

        # 1. Podnadpis sekce Prodáno
        self.assertIn('st.subheader("Prodáno — Tržní data PS5")', content)

        # 2. Načtení pouze status = 'sold' přes pd.read_sql_query
        self.assertIn("status = 'sold'", content)
        self.assertIn("pd.read_sql_query", content)

        # 3. Zobrazení tabulky pomocí st.dataframe
        self.assertIn("st.dataframe", content)

        # 4. Tlačítko pro stažení prodane_ps5.csv
        self.assertIn("st.download_button", content)
        self.assertIn("prodane_ps5.csv", content)

        # 5. Mediánové ceny dle edice
        self.assertIn("spocti_median_ceny_dle_edice", content)

        # 6. Kalkulačka profitu
        self.assertIn("vypocti_profit_aktivnich", content)

        # 7. Super kauf tab
        self.assertIn("Super kauf", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
