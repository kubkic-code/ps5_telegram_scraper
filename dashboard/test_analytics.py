"""
test_analytics.py — Unit testy pro analytické funkce dashboardu (Fáze 3)
Python Agent | Role: TDD přístup pro extrakci modelů, KPI a agregace
"""

from __future__ import annotations

import datetime
import sqlite3
import unittest
from pathlib import Path

import pandas as pd

from dashboard.analytics import (
    extrahuj_model,
    nacti_data_df,
    spocti_agregace_modelu,
    spocti_kpi,
    top_modely_ceny,
)
from db import init_db, uloz_inzerat, ziskej_pripojeni
from scraper import Inzerat


class TestExtrahujModel(unittest.TestCase):
    """Testy regex extrakce Garmin modelů z názvu inzerátu."""

    def test_fenix_modely(self):
        self.assertEqual(extrahuj_model("Garmin Fenix 7 Sapphire Solar"), "Fenix 7")
        self.assertEqual(extrahuj_model("Hodinky Garmin Fenix 7 Pro Solar"), "Fenix 7 Pro")
        self.assertEqual(extrahuj_model("Garmin Fenix 7X Sapphire"), "Fenix 7")
        self.assertEqual(extrahuj_model("Prodám Garmin Fenix 6 Pro"), "Fenix 6 Pro")
        self.assertEqual(extrahuj_model("Garmin Fenix 6X Pro Solar"), "Fenix 6")
        self.assertEqual(extrahuj_model("Garmin Fenix 5 Plus"), "Fenix 5 Plus")

    def test_forerunner_modely(self):
        self.assertEqual(extrahuj_model("Garmin Forerunner 965 AMOLED"), "Forerunner 965")
        self.assertEqual(extrahuj_model("Garmin Forerunner 945 Black"), "Forerunner 945")
        self.assertEqual(extrahuj_model("Garmin Forerunner 245 Music"), "Forerunner 245")
        self.assertEqual(extrahuj_model("Garmin Forerunner 55"), "Forerunner 55")

    def test_epix_a_venu(self):
        self.assertEqual(extrahuj_model("Garmin Epix Gen 2 Sapphire"), "Epix Gen 2")
        self.assertEqual(extrahuj_model("Garmin Epix 2"), "Epix Gen 2")
        self.assertEqual(extrahuj_model("Garmin Venu 3 Black"), "Venu 3")
        self.assertEqual(extrahuj_model("Garmin Venu 2 Plus"), "Venu 2 Plus")
        self.assertEqual(extrahuj_model("Garmin Venu Sq 2"), "Venu Sq 2")

    def test_instinct_a_tactix(self):
        self.assertEqual(extrahuj_model("Garmin Instinct 2 Solar"), "Instinct 2")
        self.assertEqual(extrahuj_model("Garmin Tactix 7 Pro"), "Tactix 7")

    def test_neznamy_nebo_obecny_nazev(self):
        self.assertEqual(extrahuj_model("Chytré hodinky Garmin"), "Ostatní")
        self.assertEqual(extrahuj_model(""), "Ostatní")
        self.assertEqual(extrahuj_model(None), "Ostatní")


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


class TestAgregaceModelu(unittest.TestCase):
    """Testy agregace cen a likvidity podle modelů."""

    def test_spocti_agregace_modelu_prazdny(self):
        df = pd.DataFrame(columns=["status", "model", "price", "doba_prodeje_hodin"])
        agregovany = spocti_agregace_modelu(df)
        self.assertTrue(agregovany.empty)
        self.assertIn("model", agregovany.columns)

    def test_spocti_agregace_modelu_spravne_vypocty(self):
        data = {
            "status": ["sold", "sold", "sold", "active"],
            "model": ["Fenix 7", "Fenix 7", "Forerunner 245", "Fenix 7"],
            "price": [10000, 12000, 4000, 11000],  # active nesmí ovlivnit průměr sold!
            "doba_prodeje_hodin": [24.0, 48.0, 12.0, None],
        }
        df = pd.DataFrame(data)
        agregovany = spocti_agregace_modelu(df)

        self.assertEqual(len(agregovany), 2)
        # Fenix 7 má 2 prodané, Forerunner 245 má 1
        fenix_row = agregovany[agregovany["model"] == "Fenix 7"].iloc[0]
        self.assertEqual(fenix_row["pocet_prodano"], 2)
        self.assertEqual(fenix_row["prumerna_cena"], 11000)  # (10000 + 12000) / 2
        self.assertEqual(fenix_row["prumerna_doba_hodin"], 36.0)  # (24 + 48) / 2

        fr_row = agregovany[agregovany["model"] == "Forerunner 245"].iloc[0]
        self.assertEqual(fr_row["pocet_prodano"], 1)
        self.assertEqual(fr_row["prumerna_cena"], 4000)
        self.assertEqual(fr_row["prumerna_doba_hodin"], 12.0)

    def test_top_modely_ceny(self):
        data = {
            "model": [f"Model {i}" for i in range(10)],
            "pocet_prodano": list(range(10, 0, -1)),
            "prumerna_cena": [5000 + i * 500 for i in range(10)],
            "prumerna_doba_hodin": [20.0] * 10,
        }
        df = pd.DataFrame(data)
        top5 = top_modely_ceny(df, n=5)
        self.assertEqual(len(top5), 5)
        self.assertEqual(top5.iloc[0]["model"], "Model 0")


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
            nazev="Garmin Fenix 7 Solar",
            url="https://bazos.cz/9911",
            cena="9 500 Kč",
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
        self.assertIn("model", df.columns)
        self.assertIn("doba_prodeje_hodin", df.columns)
        self.assertEqual(df.iloc[0]["model"], "Fenix 7")
        self.assertAlmostEqual(df.iloc[0]["doba_prodeje_hodin"], 12.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
