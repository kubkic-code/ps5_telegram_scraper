"""
test_filter.py — Unit testy pro filter.py — Garmin chytré hodinky
DevOps Agent | TDD smyčka — žádný HTTP, žádný filesystem side-effect
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
    detekuj_model,
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
)


# ---------------------------------------------------------------------------
# Pomocné tovární funkce
# ---------------------------------------------------------------------------

def inzerat(
    id: str = "100",
    nazev: str = "Garmin Fenix 7 Sapphire",
    url: str = "https://www.bazos.cz/inzerat/100/garmin-fenix-7.php",
    cena: str = "8 500 Kč",
    lokalita: str = "Praha",
    datum: str = "5.9. 2026",
    popis: str = "Garmin Fenix 7 Sapphire Solar, málo mth, zánovní.",
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
        url=f"https://www.vinted.cz/items/{id[3:]}-garmin",
        cena=cena,
        lokalita="Brno",
        datum="VT",
        popis="Perfektní stav, kompletní balení.",
    )


def scam_inzerat() -> Inzerat:
    return inzerat(
        id="999",
        nazev="Garmin Fenix 7 prodám levně",
        popis="Kontaktujte přes WhatsApp +1234, záloha do zahraničí.",
    )


def google_translate_inzerat() -> Inzerat:
    return inzerat(
        id="888",
        nazev="Garmin Fenix výprodej",
        url="https://translate.google.com/translate?hl=cs&u=https://bazos.cz/inzerat/888/test.php",
    )


def irelevantni_inzerat() -> Inzerat:
    return inzerat(
        id="777",
        nazev="Polar Vantage M2",
        url="https://www.bazos.cz/inzerat/777/polar-vantage.php",
        popis="Prodám Polar Vantage M2, zánovní stav.",
    )


# ---------------------------------------------------------------------------
# Testy klíčových slov (Garmin whitelist)
# ---------------------------------------------------------------------------

class TestKlicovaSlova(unittest.TestCase):

    def test_garmin_v_nazvu(self):
        i = inzerat(nazev="Garmin Fenix 7 Sapphire")
        self.assertTrue(_obsahuje_klicove_slovo(i))

    def test_fenix_v_nazvu(self):
        i = inzerat(nazev="Fenix 7 Pro Solar", popis="")
        self.assertTrue(_obsahuje_klicove_slovo(i))

    def test_forerunner_v_nazvu(self):
        i = inzerat(nazev="Forerunner 265 Music")
        self.assertTrue(_obsahuje_klicove_slovo(i))

    def test_venu_v_popisu(self):
        i = inzerat(popis="Prodám Garmin Venu 2 Plus, záruka.")
        self.assertTrue(_obsahuje_klicove_slovo(i))

    def test_epix_v_nazvu(self):
        i = inzerat(nazev="Garmin Epix Gen 2")
        self.assertTrue(_obsahuje_klicove_slovo(i))

    def test_instinct_v_nazvu(self):
        i = inzerat(nazev="Garmin Instinct 2 Solar")
        self.assertTrue(_obsahuje_klicove_slovo(i))

    def test_tactix_v_nazvu(self):
        i = inzerat(nazev="Garmin Tactix Delta Solar")
        self.assertTrue(_obsahuje_klicove_slovo(i))

    def test_vivoactive_v_nazvu(self):
        i = inzerat(nazev="Garmin Vivoactive 4")
        self.assertTrue(_obsahuje_klicove_slovo(i))

    def test_irelevantni_inzerat(self):
        i = irelevantni_inzerat()
        self.assertFalse(_obsahuje_klicove_slovo(i))

    def test_case_insensitive(self):
        i = inzerat(nazev="GARMIN FENIX 7 PRO")
        self.assertTrue(_obsahuje_klicove_slovo(i))

    def test_prazdny_popis(self):
        i = inzerat(nazev="Garmin Fenix 7", popis=None)
        self.assertTrue(_obsahuje_klicove_slovo(i))

    def test_smartwatch_v_nazvu(self):
        i = inzerat(nazev="Smartwatch GPS sportovní")
        self.assertTrue(_obsahuje_klicove_slovo(i))

    # --- Uvolněná pravidla: generický Garmin a Vinted ---

    def test_genericky_garmin_v_nazvu_bez_modelu_projde(self):
        """Inzerát s pouze generickým slovem 'Garmin' bez modelu v názvu nesmí být zahozen."""
        i = inzerat(nazev="Garmin", popis="Používané hodinky, plně funkční.")
        self.assertTrue(_obsahuje_klicove_slovo(i))

    def test_genericky_hodinky_garmin_v_nazvu_projde(self):
        """Inzerát 'Hodinky Garmin' bez konkrétního modelu v názvu musí projít."""
        i = inzerat(nazev="Hodinky Garmin", popis="Běžné opotřebení, sklíčko čisté.")
        self.assertTrue(_obsahuje_klicove_slovo(i))

    def test_vinted_bez_modelu_v_nazvu_projde(self):
        """Vinted inzerát i bez specifického modelu v názvu musí projít (pochází z Garmin hledání)."""
        i = vinted_inzerat(nazev="Chytré hodinky")
        self.assertTrue(_obsahuje_klicove_slovo(i))
        self.assertTrue(je_vinted_inzerat(i))

    def test_model_skryty_v_popisu_forerunner(self):
        """Název je pouze 'Garmin', ale v popisu je 'Forerunner 245' → musí projít."""
        i = inzerat(nazev="Garmin", popis="Prodám spolehlivé Forerunner 245 Music.")
        self.assertTrue(_obsahuje_klicove_slovo(i))
        self.assertEqual(detekuj_model(i), "Forerunner 245")

    def test_model_skryty_v_popisu_fenix(self):
        """Název je obecný 'Sportovní hodinky', v popisu 'Garmin Fenix 6 Pro' → musí projít."""
        i = inzerat(nazev="Sportovní hodinky", popis="Prodám Garmin Fenix 6 Pro Sapphire.")
        self.assertTrue(_obsahuje_klicove_slovo(i))
        self.assertEqual(detekuj_model(i), "Fenix 6 Pro")

    def test_model_skryty_v_popisu_venu(self):
        """Název 'Dámské hodinky', v popisu 'Garmin Venu 2 Plus' → musí projít."""
        i = inzerat(nazev="Dámské hodinky", popis="Krásné Garmin Venu 2 Plus rose gold.")
        self.assertTrue(_obsahuje_klicove_slovo(i))
        self.assertEqual(detekuj_model(i), "Venu 2 Plus")


# ---------------------------------------------------------------------------
# Testy detekce modelů (prohledávání názvu i popisu)
# ---------------------------------------------------------------------------

class TestDetekceModelu(unittest.TestCase):
    """Ověření detekce modelů Garmin z názvu a z těla inzerátu (popis)."""

    def test_model_primo_v_nazvu(self):
        i = inzerat(nazev="Garmin Fenix 7 Sapphire", popis="")
        self.assertEqual(detekuj_model(i), "Fenix 7")

    def test_model_pouze_v_popisu(self):
        i = inzerat(nazev="Hodinky Garmin", popis="Prodám Garmin Forerunner 955 Solar.")
        self.assertEqual(detekuj_model(i), "Forerunner 955")

    def test_prednost_ma_nazev_pred_popisem(self):
        i = inzerat(
            nazev="Garmin Epix Gen 2",
            popis="Přecházím z Forerunner 245 na tyto Epixy.",
        )
        self.assertEqual(detekuj_model(i), "Epix Gen 2")

    def test_zadny_model_nenalezen_vraci_none(self):
        i = inzerat(nazev="Garmin", popis="Starší hodinky, stav viz foto.")
        self.assertIsNone(detekuj_model(i))


# ---------------------------------------------------------------------------
# Testy scam detekce
# ---------------------------------------------------------------------------

class TestScamDetekce(unittest.TestCase):

    def test_whatsapp_je_scam(self):
        i = inzerat(popis="Pište na WhatsApp +420123456789")
        je, duvod = _je_scam(i)
        self.assertTrue(je)
        self.assertIn("whatsapp", duvod.lower())

    def test_western_union_je_scam(self):
        i = inzerat(popis="Platba přes Western Union prosím.")
        je, _ = _je_scam(i)
        self.assertTrue(je)

    def test_normalni_inzerat_neni_scam(self):
        i = inzerat()
        je, _ = _je_scam(i)
        self.assertFalse(je)

    def test_scam_v_nazvu(self):
        i = inzerat(nazev="Garmin Fenix prodám, platba escrow")
        je, _ = _je_scam(i)
        self.assertTrue(je)


# ---------------------------------------------------------------------------
# Testy Google Translate
# ---------------------------------------------------------------------------

class TestGoogleTranslate(unittest.TestCase):

    def test_google_translate_url(self):
        i = google_translate_inzerat()
        self.assertTrue(_je_google_translate(i))

    def test_normalni_url(self):
        i = inzerat()
        self.assertFalse(_je_google_translate(i))

    def test_googleusercontent_url(self):
        i = inzerat(url="https://translate.googleusercontent.com/translate_c?id=123")
        self.assertTrue(_je_google_translate(i))


# ---------------------------------------------------------------------------
# Testy negativních klíčových slov (příslušenství a balast)
# ---------------------------------------------------------------------------

class TestNegativniSlova(unittest.TestCase):

    def test_kryt_zamitnut(self):
        i = inzerat(nazev="Silikonový kryt Garmin Instinct", popis="")
        je, slovo = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)
        self.assertIn("kryt", slovo)

    def test_case_zamitnut(self):
        i = inzerat(nazev="Garmin Fenix case protector", popis="")
        je, slovo = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)
        self.assertIn("case", slovo)

    def test_pouzdro_zamitnut(self):
        i = inzerat(nazev="Pouzdro na hodinky Garmin", popis="")
        je, slovo = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)
        self.assertIn("pouzdro", slovo)

    def test_nabijeci_dok_zamitnut(self):
        i = inzerat(nazev="Nabíjecí dok Garmin Forerunner", popis="")
        je, slovo = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)
        self.assertIn("nabíjecí dok", slovo)

    def test_charging_cable_zamitnut(self):
        i = inzerat(nazev="Charging cable Garmin USB", popis="")
        je, slovo = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)
        self.assertIn("charging cable", slovo)

    def test_dobijecka_zamitnut(self):
        i = inzerat(nazev="Dobíječka pro Garmin Fenix 7", popis="")
        je, slovo = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)
        self.assertIn("dobíječka", slovo)

    def test_rozbite_zamitnut(self):
        i = inzerat(nazev="Garmin Fenix 7 rozbité tělo", popis="")
        je, _ = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)

    def test_na_dily_zamitnut(self):
        i = inzerat(nazev="Garmin Vivoactive — na díly", popis="")
        je, _ = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)

    def test_hledam_zamitnut(self):
        i = inzerat(nazev="Hledám Garmin Fenix 7 levně", popis="")
        je, _ = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)

    def test_koupim_zamitnut(self):
        i = inzerat(nazev="Koupím Garmin Forerunner 255", popis="")
        je, _ = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)

    def test_dobry_inzerat_neprojde_negativnim(self):
        """Prodej funkčních hodinek nesmí selhat na negativním filtru."""
        i = inzerat()  # 'Garmin Fenix 7 Sapphire' — žádné negativní slovo
        je, _ = _obsahuje_negativni_slovo(i)
        self.assertFalse(je)

    def test_pronájem_zamitnut(self):
        i = inzerat(nazev="Pronájem Garmin hodinek na víkend")
        je, _ = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)

    # --- Testy pro konkurenční značky, výměny, poškození ---

    def test_apple_watch_zamitnut(self):
        i = inzerat(nazev="Apple Watch Ultra 2", popis="")
        je, slovo = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)
        self.assertIn("apple watch", slovo)

    def test_samsung_zamitnut(self):
        i = inzerat(nazev="Samsung hodinky černé", popis="")
        je, slovo = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)
        self.assertIn("samsung", slovo)

    def test_galaxy_watch_zamitnut(self):
        i = inzerat(nazev="Galaxy Watch 5 Pro", popis="")
        je, slovo = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)
        self.assertIn("galaxy watch", slovo)

    def test_huawei_zamitnut(self):
        i = inzerat(nazev="Huawei Watch GT 4", popis="")
        je, slovo = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)
        self.assertIn("huawei", slovo)

    def test_vymenim_zamitnut(self):
        i = inzerat(nazev="Garmin Fenix 7", popis="Vyměním za Apple Watch nebo mobil.")
        je, slovo = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)
        self.assertIn("vyměním", slovo)

    def test_vymena_zamitnut(self):
        i = inzerat(nazev="Garmin Forerunner 965", popis="Možná výměna za jiný model.")
        je, slovo = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)
        self.assertIn("výměna", slovo)

    def test_vryp_zamitnut(self):
        i = inzerat(nazev="Garmin Epix Gen 2", popis="Tělo v pořádku, pouze malý vryp na lunetě.")
        je, slovo = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)
        self.assertIn("vryp", slovo)

    def test_ryha_zamitnut(self):
        i = inzerat(nazev="Garmin Venu 3", popis="Vlásečnicová rýha na displeji, jinak top.")
        je, slovo = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)
        self.assertIn("rýha", slovo)

    def test_praskly_zamitnut(self):
        i = inzerat(nazev="Garmin Instinct 2", popis="Prasklý displej, hodinky fungují.")
        je, slovo = _obsahuje_negativni_slovo(i)
        self.assertTrue(je)
        self.assertIn("prasklý", slovo)


# ---------------------------------------------------------------------------
# Testy cenového filtru (rozsah 800–20000 Kč / 30–900 EUR)
# ---------------------------------------------------------------------------

class TestCenovyFiltr(unittest.TestCase):
    """Striktní cenový rozsah — příliš levné i příliš drahé = ZAHODIT."""

    # --- Ceny pod minimem → ZAHODIT ---

    def test_cena_pod_minimum_czk_zamitnut(self):
        """500 Kč — pod minimem → zahodit."""
        i = inzerat(cena="500 Kč")
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)
        self.assertIn("Kč", duvod)

    def test_cena_799_kc_zamitnut(self):
        """799 Kč je těsně pod minimem 800 Kč → zahodit."""
        i = inzerat(cena="799 Kč")
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)
        self.assertIn("Kč", duvod)

    def test_cena_pod_minimum_eur_zamitnut(self):
        """20 EUR → zahodit (minimum je 30 EUR)."""
        i = inzerat(cena="20 €")
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)
        self.assertIn("EUR", duvod)

    def test_cena_150_kc_zamitnut(self):
        """150 Kč → zahodit."""
        i = inzerat(cena="150 Kč")
        zahodit, _ = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)

    # --- Ceny nad maximem → ZAHODIT ---

    def test_cena_nad_maximum_czk_zamitnut(self):
        """30 000 Kč — nad limitem 20 000 Kč → zahodit."""
        i = inzerat(cena="30 000 Kč")
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)
        self.assertIn("Kč", duvod)

    def test_cena_nad_maximum_eur_zamitnut(self):
        """1 500 € → zahodit (nad limitem 900 EUR)."""
        i = inzerat(cena="1.500 €")
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)
        self.assertIn("EUR", duvod)

    # --- Ceny v rozsahu → PROJÍT ---

    def test_cena_800_kc_projde(self):
        """800 Kč — na hranici minima → projít."""
        i = inzerat(cena="800 Kč")
        zahodit, _ = _zkontroluj_cenu(i)
        self.assertFalse(zahodit)

    def test_cena_1000_kc_projde(self):
        """1 000 Kč — v rozsahu → projít."""
        i = inzerat(cena="1 000 Kč")
        zahodit, _ = _zkontroluj_cenu(i)
        self.assertFalse(zahodit)

    def test_cena_8500_kc_projde(self):
        """8 500 Kč — běžná cena Fenix → projít."""
        i = inzerat(cena="8 500 Kč")
        zahodit, _ = _zkontroluj_cenu(i)
        self.assertFalse(zahodit)

    def test_cena_20000_kc_projde(self):
        """20 000 Kč — na hranici maxima → projít."""
        i = inzerat(cena="20 000 Kč")
        zahodit, _ = _zkontroluj_cenu(i)
        self.assertFalse(zahodit)

    def test_cena_25000_kc_zamitnuta(self):
        """25 000 Kč — nad novým maximem 20 000 Kč → zahodit."""
        i = inzerat(cena="25 000 Kč")
        zahodit, _ = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)

    def test_cena_30_eur_projde(self):
        """30 € — na hranici minima EUR → projít."""
        i = inzerat(cena="30 €")
        zahodit, _ = _zkontroluj_cenu(i)
        self.assertFalse(zahodit)

    def test_cena_200_eur_projde(self):
        """200 € → projít."""
        i = inzerat(cena="200 €")
        zahodit, _ = _zkontroluj_cenu(i)
        self.assertFalse(zahodit)

    def test_cena_900_eur_projde(self):
        """900 € — na hranici maxima → projít."""
        i = inzerat(cena="900 €")
        zahodit, _ = _zkontroluj_cenu(i)
        self.assertFalse(zahodit)

    def test_cena_1000_eur_zamitnuta(self):
        """1 000 € — nad novým maximem 900 EUR → zahodit."""
        i = inzerat(cena="1.000 €")
        zahodit, _ = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)

    def test_cena_nemecky_format_tecky_tisice(self):
        """'10.000 €' = 10000 EUR > 900 EUR → zahodit."""
        i = inzerat(cena="10.000 €")
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)
        self.assertIn("maximum", duvod)

    def test_cena_cesky_format_200_kc(self):
        """'200 Kč' < 800 Kč → zahodit."""
        i = inzerat(cena="200 Kč")
        zahodit, _ = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)

    # --- VB / Dohodou / Neuvedena → ZAHODIT ---

    def test_cena_vb_zahazena(self):
        i = inzerat(cena="VB")
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)
        self.assertIn("VB", duvod)

    def test_cena_dohodou_zahazena(self):
        i = inzerat(cena="Dohodou")
        zahodit, _ = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)

    def test_cena_neuvedena_zahazena(self):
        i = inzerat(cena="Neuvedena")
        zahodit, _ = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)

    def test_cena_v_textu_zahazena(self):
        i = inzerat(cena="V textu")
        zahodit, _ = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)

    def test_cena_prazdna_zahazena(self):
        i = inzerat(cena="")
        zahodit, _ = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)

    # --- Neznámá měna → ZAHODIT ---

    def test_cena_bez_meny_zahazena(self):
        i = inzerat(cena="8500")
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)
        self.assertIn("měna", duvod)

    # --- Vinted formát se dvěma cenami ---

    def test_vinted_dve_ceny_5108_kc(self):
        """'5108.24 Kč, 5381.65 Kč' -> použije se pouze 5108.24 Kč -> projít."""
        i = inzerat(cena="5108.24 Kč, 5381.65 Kč")
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertFalse(zahodit, f"Inzerát neměl být zahozen: {duvod}")
        self.assertEqual(i.cena, "5108.24 Kč")

    def test_vinted_dve_ceny_czk_prvni_pouzita(self):
        """'4000.00 Kč, 4218.00 Kč' -> použije se pouze 4000.00 Kč -> projít."""
        i = inzerat(cena="4000.00 Kč, 4218.00 Kč")
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertFalse(zahodit, f"Inzerát neměl být zahozen: {duvod}")
        self.assertEqual(i.cena, "4000.00 Kč")

    def test_vinted_dve_ceny_czk_vysoka_cena_projde(self):
        """'10227.85 Kč, 10757.24 Kč' -> použije se pouze 10227.85 Kč (<= 20000) -> projít."""
        i = inzerat(cena="10227.85 Kč, 10757.24 Kč")
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertFalse(zahodit, f"Inzerát neměl být zahozen: {duvod}")
        self.assertEqual(i.cena, "10227.85 Kč")

    def test_vinted_dve_ceny_eur_prvni_pouzita(self):
        """'150.00 €, 170.00 €' -> použije se pouze 150.00 € -> projít."""
        i = inzerat(cena="150.00 €, 170.00 €")
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertFalse(zahodit, f"Inzerát neměl být zahozen: {duvod}")
        self.assertEqual(i.cena, "150.00 €")

    def test_vinted_dve_ceny_prvni_pod_minimem_czk(self):
        """'500.00 Kč, 600.00 Kč' -> první cena 500 Kč je pod minimem -> zahodit."""
        i = inzerat(cena="500.00 Kč, 600.00 Kč")
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)
        self.assertIn("minimum", duvod)

    def test_desetinna_carka_eur_nerozbita_nad_maximem(self):
        """'1.500,50 €' nesmí být rozbito čárkou: hodnota 1500.50 EUR > 900 EUR -> zahodit."""
        i = inzerat(cena="1.500,50 €")
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertTrue(zahodit)
        self.assertIn("maximum", duvod)
        self.assertEqual(i.cena, "1.500,50 €")

    def test_desetinna_carka_eur_nerozbita_v_rozsahu(self):
        """'250,50 €' nesmí být rozbito čárkou: hodnota 250.50 EUR v rozsahu [30, 900] -> projít."""
        i = inzerat(cena="250,50 €")
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertFalse(zahodit, f"Inzerát neměl být zahozen: {duvod}")
        self.assertEqual(i.cena, "250,50 €")

    # --- Vinted kompozitní texty (data v názvu, cena='Neuvedena') ---

    def test_vinted_kompozitni_nazev_cena_neuvedena_uspesne_rozbalena(self):
        """Reálný server log: Vinted nacpe všechna data do názvu a cena='Neuvedena'."""
        i = inzerat(
            nazev="Garmin Forerunner 570, Značka: Garmin, Stav: Velmi dobrý, Velikost: 47 mm a více, 9299.00 Kč, 9781.95 Kč",
            cena="Neuvedena",
        )
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertFalse(zahodit, f"Inzerát neměl být zahozen: {duvod}")
        self.assertEqual(i.cena, "9299.00 Kč")
        self.assertEqual(i.nazev, "Garmin Forerunner 570")
        self.assertIn("Stav: Velmi dobrý", i.popis or "")

    def test_vinted_kompozitni_nazev_forerunner_55(self):
        """'Garmin Forerunner 55, Značka: Garmin, Stav: Velmi dobrý, Velikost: 39–42 mm, 1800.00 Kč, 1908.00 Kč'."""
        i = inzerat(
            nazev="Garmin Forerunner 55, Značka: Garmin, Stav: Velmi dobrý, Velikost: 39–42 mm, 1800.00 Kč, 1908.00 Kč",
            cena="Neuvedena",
        )
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertFalse(zahodit, f"Inzerát neměl být zahozen: {duvod}")
        self.assertEqual(i.cena, "1800.00 Kč")
        self.assertEqual(i.nazev, "Garmin Forerunner 55")

    def test_vinted_kompozitni_nazev_fenix_8(self):
        """Fenix 8 z reálného logu serveru — cena je v názvu, cena=''."""
        i = inzerat(
            nazev="Garmin Fenix 8 Amoled Saphhire Bransoleta 51mm Gwarancja, Značka: Garmin, Stav: Velmi dobrý, Velikost: 47 mm a více, 18177.16 Kč, 19104.02 Kč",
            cena="",
        )
        zahodit, duvod = _zkontroluj_cenu(i)
        self.assertFalse(zahodit, f"Inzerát neměl být zahozen: {duvod}")
        self.assertEqual(i.cena, "18177.16 Kč")
        self.assertEqual(i.nazev, "Garmin Fenix 8 Amoled Saphhire Bransoleta 51mm Gwarancja")

    def test_vinted_kompozitni_nazev_filtruj_inzerat_cely_pruchod(self):
        """Celý průchod filtrem filtruj_inzerat s kompozitním názvem."""
        i = inzerat(
            id="vt_9921837573",
            nazev="Garmin Forerunner 570, Značka: Garmin, Stav: Velmi dobrý, Velikost: 47 mm a více, 9299.00 Kč, 9781.95 Kč",
            cena="Neuvedena",
            datum="VT",
        )
        res = filtruj_inzerat(i)
        self.assertTrue(res.prijat, f"Inzerát měl být přijat, zamítnut pro: {res.duvod_zamitnuti}")
        self.assertEqual(i.cena, "9299.00 Kč")
        self.assertEqual(i.nazev, "Garmin Forerunner 570")

    def test_vsech_15_inzeratu_ze_server_logu_extrahuje_cenu(self):
        """Ověří, že ani jeden z 15 inzerátů ze server logu nezamítne inzerát kvůli 'cena není uvedena'."""
        server_log_nazvy = [
            ("vt_9921837573", "Garmin Forerunner 570, Značka: Garmin, Stav: Velmi dobrý, Velikost: 47 mm a více, 9299.00 Kč, 9781.95 Kč", "9299.00 Kč"),
            ("vt_9919839946", "Garmin forerunner 265s, Značka: Garmin, Stav: Velmi dobrý, Velikost: 39–42 mm, 5966.24 Kč, 6282.55 Kč", "5966.24 Kč"),
            ("vt_9920212565", "Zegarek sportowy Garmin Vivoactive 4S - Czarny, Značka: Garmin, Stav: Velmi dobrý, Velikost: 39–42 mm, 1869.42 Kč, 1980.89 Kč", "1869.42 Kč"),
            ("vt_9920732828", "Garmin Fenix 8 Amoled Saphhire Bransoleta 51mm Gwarancja, Značka: Garmin, Stav: Velmi dobrý, Velikost: 47 mm a více, 18177.16 Kč, 19104.02 Kč", "18177.16 Kč"),
            ("vt_9920679319", "Chytré hodinky Garmin Vívoactive 4, Značka: Garmin, Stav: Dobrý, Velikost: 39–42 mm, 2700.00 Kč, 2853.00 Kč", "2700.00 Kč"),
            ("vt_9920665928", "Garmin Fenix 7X Pro Solar, Značka: Garmin, Stav: Velmi dobrý, Velikost: 47 mm a více, 10000.00 Kč, 10518.00 Kč", "10000.00 Kč"),
            ("vt_9920284492", "Garmin vivofit 4, Značka: Garmin, Stav: Velmi dobrý, 765.00 Kč, 821.25 Kč", "765.00 Kč"),
            ("vt_9920530156", "Garmin Fenix 7X Solar – NOWY, kompletny, Značka: Garmin, Stav: Nový s visačkou, Velikost: 47 mm a více, 11364.27 Kč, 11950.48 Kč", "11364.27 Kč"),
            ("vt_9925322581", "Garmin Edge 530, Značka: Garmin, Stav: Velmi dobrý, 3693.39 Kč, 3896.06 Kč", "3693.39 Kč"),
            ("vt_9919872116", "Zegarek garmin Vivoactive 5, Značka: Garmin, Stav: Nový s visačkou, Velikost: 39–42 mm, 4829.82 Kč, 5089.31 Kč", "4829.82 Kč"),
            ("vt_9918547815", "Garmin Venu 2S, Značka: Garmin, Stav: Velmi dobrý, Velikost: 43–46 mm, 1224.22 Kč, 1303.43 Kč", "1224.22 Kč"),
            ("vt_9924230796", "Garmin edge Uchwyt - wersja krótka lewa, Značka: Garmin, Stav: Nový bez visačky, 255.70 Kč, 286.49 Kč", "255.70 Kč"),
            ("vt_9918203831", "Garmin Venu SQ, Značka: Garmin, Stav: Velmi dobrý, Velikost: Univerzální, 789.82 Kč, 847.31 Kč", "789.82 Kč"),
            ("vt_9918719043", "Garmin vivomove style, Značka: Garmin, Stav: Dobrý, Velikost: 39–42 mm, 979.37 Kč, 1046.34 Kč", "979.37 Kč"),
            ("vt_9919343605", "Garmin venu sq 2, Značka: Garmin, Stav: Dobrý, Velikost: 39–42 mm, 1713.90 Kč, 1817.60 Kč", "1713.90 Kč"),
        ]
        for item_id, raw_title, expected_price in server_log_nazvy:
            i = inzerat(id=item_id, nazev=raw_title, cena="Neuvedena")
            zahodit, duvod = _zkontroluj_cenu(i)
            self.assertNotIn("cena není uvedena", duvod, f"Pro {item_id} bylo vráceno 'cena není uvedena'")
            self.assertEqual(i.cena, expected_price, f"Chybná extrahovaná cena pro {item_id}")

    # --- Ověření konstant ---

    def test_min_cena_czk_je_800(self):
        self.assertEqual(MIN_CENA_CZK, 800)

    def test_max_cena_czk_je_20000(self):
        self.assertEqual(MAX_CENA_CZK, 20_000)

    def test_min_cena_eur_je_30(self):
        self.assertEqual(MIN_CENA_EUR, 30)

    def test_max_cena_eur_je_900(self):
        self.assertEqual(MAX_CENA_EUR, 900)


# ---------------------------------------------------------------------------
# Testy celkového filtru
# ---------------------------------------------------------------------------

class TestFiltrujInzerat(unittest.TestCase):

    def test_dobry_garmin_inzerat_prijat(self):
        vysledek = filtruj_inzerat(inzerat())
        self.assertTrue(vysledek.prijat)
        self.assertEqual(vysledek.duvod_zamitnuti, "")

    def test_vinted_garmin_inzerat_prijat(self):
        """Inzerát z Vinted s vt_ prefixem a správnou cenou musí projít."""
        vysledek = filtruj_inzerat(vinted_inzerat())
        self.assertTrue(vysledek.prijat)

    def test_scam_zamitnut(self):
        vysledek = filtruj_inzerat(scam_inzerat())
        self.assertFalse(vysledek.prijat)
        self.assertIn("scam", vysledek.duvod_zamitnuti.lower())

    def test_google_translate_zamitnut(self):
        vysledek = filtruj_inzerat(google_translate_inzerat())
        self.assertFalse(vysledek.prijat)
        self.assertIn("Google Translate", vysledek.duvod_zamitnuti)

    def test_irelevantni_zamitnut(self):
        vysledek = filtruj_inzerat(irelevantni_inzerat())
        self.assertFalse(vysledek.prijat)
        self.assertIn("klíčové slovo", vysledek.duvod_zamitnuti)

    def test_prilis_levny_zamitnut(self):
        """Nabíjecí kabel za 150 Kč musí být zamítnut."""
        i = inzerat(cena="150 Kč", nazev="Garmin nabíjecí kabel")
        vysledek = filtruj_inzerat(i)
        self.assertFalse(vysledek.prijat)

    def test_prilis_drahy_zamitnut(self):
        """Cena 30 000 Kč je nad maximem → zamítnut."""
        i = inzerat(cena="30 000 Kč")
        vysledek = filtruj_inzerat(i)
        self.assertFalse(vysledek.prijat)

    def test_kryt_zamitnut_i_kdyz_cena_ok(self):
        """Kryt s cenou v rozsahu musí být zamítnut kvůli negativnímu slovu."""
        i = inzerat(nazev="Garmin silikonový kryt 47mm", cena="2 000 Kč")
        vysledek = filtruj_inzerat(i)
        self.assertFalse(vysledek.prijat)
        self.assertIn("negativní slovo", vysledek.duvod_zamitnuti)

    def test_apple_watch_vymena_za_garmin_zamitnut(self):
        """Inzerát na Apple Watch s popisem 'vyměním za Garmin' musí být zamítnut."""
        i = inzerat(
            nazev="Apple Watch Series 9 45mm",
            cena="7 500 Kč",
            popis="Prodám Apple Watch, případně vyměním za Garmin Fenix 7.",
        )
        vysledek = filtruj_inzerat(i)
        self.assertFalse(vysledek.prijat)
        self.assertIn("negativní slovo", vysledek.duvod_zamitnuti)

    def test_vinted_inzerat_s_obecnym_nazvem_prijat(self):
        """Vinted inzerát s obecným názvem (např. jen 'Hodinky Garmin') musí projít."""
        i = Inzerat(
            id="vt_998877",
            nazev="Hodinky Garmin",
            url="https://www.vinted.cz/items/998877-hodinky-garmin",
            cena="1 200 Kč",
            lokalita="Praha",
            datum="VT",
            popis="Krásný stav, plně funkční.",
        )
        vysledek = filtruj_inzerat(i)
        self.assertTrue(vysledek.prijat, f"Očekáván průchod, zamítnuto: {vysledek.duvod_zamitnuti}")

    def test_vinted_levny_forerunner_800_kc_prijat(self):
        """Levný Forerunner za 800 Kč z Vinted musí projít filtrem."""
        i = vinted_inzerat(nazev="Garmin Forerunner 45", cena="800 Kč")
        vysledek = filtruj_inzerat(i)
        self.assertTrue(vysledek.prijat)
        self.assertEqual(vysledek.model, "Forerunner 45")

    def test_inzerat_s_modelem_v_popisu_detekuje_model(self):
        """Inzerát s generickým názvem 'Garmin' a modelem v popisu má správně detekovaný model."""
        i = Inzerat(
            id="123456",
            nazev="Garmin",
            url="https://www.bazos.cz/inzerat/123456/garmin.php",
            cena="3 500 Kč",
            lokalita="Brno",
            datum="7.9. 2026",
            popis="Prodám Garmin Forerunner 55, nošené měsíc.",
        )
        vysledek = filtruj_inzerat(i)
        self.assertTrue(vysledek.prijat)
        self.assertEqual(vysledek.model, "Forerunner 55")

    def test_vinted_kryt_zamitnut(self):
        """Kryt na Vinted s cenou v rozsahu musí být zamítnut."""
        i = vinted_inzerat(nazev="Silikonový kryt Garmin Instinct", cena="850 Kč")
        vysledek = filtruj_inzerat(i)
        self.assertFalse(vysledek.prijat)
        self.assertIn("negativní slovo", vysledek.duvod_zamitnuti)

    def test_vraci_instance_vysledku(self):
        vysledek = filtruj_inzerat(inzerat())
        self.assertIsInstance(vysledek, VysledekFiltrace)


class TestFiltrujSeznam(unittest.TestCase):

    def test_mix_inzeratu(self):
        seznam = [inzerat("1"), scam_inzerat(), irelevantni_inzerat()]
        vysledky = filtruj_seznam(seznam)
        self.assertEqual(len(vysledky), 3)
        self.assertTrue(vysledky[0].prijat)
        self.assertFalse(vysledky[1].prijat)
        self.assertFalse(vysledky[2].prijat)

    def test_prazdny_seznam(self):
        self.assertEqual(filtruj_seznam([]), [])


# ---------------------------------------------------------------------------
# Testy deduplikace (seen_ids)
# ---------------------------------------------------------------------------

class TestSeenIds(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.cesta = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.cesta.unlink(missing_ok=True)

    def test_nacti_seen_ids_prazdny_soubor(self):
        self.cesta.unlink()
        ids = nacti_seen_ids(self.cesta)
        self.assertIsInstance(ids, set)
        self.assertEqual(len(ids), 0)

    def test_uloz_a_nacti_roundtrip(self):
        ids = {"100", "vt_4567890001", "300"}
        uloz_seen_ids(ids, self.cesta)
        nacte = nacti_seen_ids(self.cesta)
        self.assertEqual(ids, nacte)

    def test_uloz_json_format(self):
        uloz_seen_ids({"42", "vt_99"}, self.cesta)
        data = json.loads(self.cesta.read_text(encoding="utf-8"))
        self.assertIn("ids", data)
        self.assertIn("42", data["ids"])

    def test_nacti_pokuseny_json(self):
        self.cesta.write_text("INVALID JSON", encoding="utf-8")
        ids = nacti_seen_ids(self.cesta)
        self.assertEqual(ids, set())


class TestOdfiltrujNove(unittest.TestCase):

    def test_odfiltruje_videne(self):
        seznam = [inzerat("1"), inzerat("2"), inzerat("3")]
        seen = {"1", "3"}
        nove = odfiltruj_nove(seznam, seen)
        self.assertEqual(len(nove), 1)
        self.assertEqual(nove[0].id, "2")

    def test_vsechny_nove(self):
        seznam = [inzerat("1"), inzerat("2")]
        nove = odfiltruj_nove(seznam, set())
        self.assertEqual(len(nove), 2)

    def test_vsechny_videne(self):
        seznam = [inzerat("1"), inzerat("2")]
        nove = odfiltruj_nove(seznam, {"1", "2"})
        self.assertEqual(len(nove), 0)


class TestZpracujDavku(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.cesta = pathlib.Path(self.tmp.name)
        self.cesta.unlink()  # neexistující soubor = prázdné seen_ids

    def tearDown(self):
        self.cesta.unlink(missing_ok=True)

    def test_vrati_relevantni_nove(self):
        seznam = [inzerat("1"), scam_inzerat(), irelevantni_inzerat()]
        prijate = zpracuj_davku(seznam, self.cesta)
        self.assertEqual(len(prijate), 1)
        self.assertEqual(prijate[0].id, "1")

    def test_vynecha_videne(self):
        uloz_seen_ids({"1"}, self.cesta)
        seznam = [inzerat("1"), inzerat("2")]
        prijate = zpracuj_davku(seznam, self.cesta)
        self.assertEqual(len(prijate), 1)
        self.assertEqual(prijate[0].id, "2")

    def test_prazdny_vstup(self):
        self.assertEqual(zpracuj_davku([], self.cesta), [])

    def test_vinted_inzerat_projde_davkou(self):
        """Vinted inzeráty s vt_ prefixem musí projít celou pipeline."""
        i = vinted_inzerat()
        prijate = zpracuj_davku([i], self.cesta)
        self.assertEqual(len(prijate), 1)
        self.assertEqual(prijate[0].id, i.id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
