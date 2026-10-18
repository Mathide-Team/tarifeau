"""Recalage sur une facture réelle anonymisée du Grand Besançon (issues #9, #15 et #26)."""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import yaml

from custom_components.tarifeau.calcul import facture_periode
from custom_components.tarifeau.modele import chemin_tarif, prolonger, tarif_depuis_dict

FACTURE = yaml.safe_load(
    (Path(__file__).parent / "donnees" / "facture_reelle_besancon_2025_2026.yaml").read_text()
)
DEBUT, FIN = FACTURE["debut"], FACTURE["fin"] + timedelta(days=1)  # fin incluse sur la facture
VOLUME = Decimal(FACTURE["volume_m3"])
TTC = Decimal(str(FACTURE["totaux"]["facture"]["ttc"]))


def _prereglage() -> dict:
    return yaml.safe_load(chemin_tarif("grand_besancon_regie").read_text())


def _avec_2025() -> dict:
    """Préréglage 2026, plus les tarifs 2025 de la commune repris de la facture."""
    donnees = _prereglage()
    t = FACTURE["tarif_2025"]
    p = deepcopy(donnees["periodes"][0])
    p.pop("factures_types")
    p.update(debut=date(2025, 1, 1), fin=date(2025, 12, 31), date_source=date(2024, 12, 19))
    eau, asst = p["services"]["eau_potable"], p["services"]["assainissement"]
    eau["abonnements"][0]["montant_ht_an"] = t["abonnement_eau_an"]
    eau["composantes"][0]["tranches"] = [
        {"jusqua": 3, "prix_ht": 0},
        {"jusqua": 100, "prix_ht": t["eau_tranche_2"]},
        {"prix_ht": t["eau_tranche_3"]},
    ]
    asst["abonnements"][0]["montant_ht_an"] = t["abonnement_assainissement_an"]
    asst["composantes"][0]["prix_ht"] = t["assainissement_m3"]
    donnees["periodes"].insert(0, p)
    return donnees


def test_transcription_coherente() -> None:
    lignes = FACTURE["lignes"]
    assert sum(Decimal(str(ligne[3])) for ligne in lignes) == Decimal(str(FACTURE["totaux"]["facture"]["ht"]))
    assert sum(Decimal(str(ligne[5])) for ligne in lignes) == TTC
    assert (FIN - DEBUT).days == 348


def test_recalage_au_centime_pres() -> None:
    """Avec les tarifs 2025 de la commune : 360,70 € calculés pour 360,87 € facturés."""
    facture = facture_periode(tarif_depuis_dict(_avec_2025()), DEBUT, FIN, VOLUME)
    assert facture.total_ttc == Decimal("360.70")
    assert abs(facture.total_ttc - TTC) / TTC < Decimal("0.001")  # moins de 0,1 %
    abonnements = [
        round(ligne.montant_ht, 2) for ligne in facture.lignes if ligne.libelle.startswith("Abonnement")
    ]
    assert abonnements == [
        Decimal("6.03"),
        Decimal("2.80"),
        Decimal("9.45"),
        Decimal("6.30"),
    ]  # comme la facture
    # Tranche gratuite proratisée : 3 m³ x 348 / 365 = 2,86 m³ (1,42 + 1,44 sur la facture).
    gratuit = sum(
        ligne.quantite for ligne in facture.lignes if ligne.prix_unitaire_ht == 0 and ligne.unite == "m³"
    )
    assert round(gratuit, 2) == Decimal("2.86")


def test_prorata_plutot_que_cumul_annuel() -> None:
    """La règle ``cumul_annuel`` s'écarte de 4,89 € : la facture confirme ``prorata`` (issue #15)."""
    donnees = _avec_2025()
    donnees["tranches"] = "cumul_annuel"
    cumul = facture_periode(tarif_depuis_dict(donnees), DEBUT, FIN, VOLUME)
    assert cumul.total_ttc == Decimal("355.98")


def test_prereglage_seul_sous_le_seuil_d_alerte() -> None:
    """Sans les tarifs 2025, le tarif 2026 est prolongé : l'écart reste sous les 10 % (issue #26)."""
    tarif, prolonge = prolonger(tarif_depuis_dict(_prereglage()), DEBUT, FIN)
    assert prolonge
    total = facture_periode(tarif, DEBUT, FIN, VOLUME).total_ttc
    ecart = (total - TTC) / TTC * 100
    assert -1 < ecart < 0  # 359,12 € (-0,48 %) : tarif 2026 un peu moins cher que celui de 2025
