"""Moteur de calcul : prorata, tranches, changement de tarif, prix marginal (issue #3)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from custom_components.tarifeau.calcul import (
    consommation,
    decouper,
    facture_periode,
    facture_sur_un_an,
    jours_annee,
    prix_marginal,
)
from custom_components.tarifeau.modele import charger_tarif, tarif_depuis_dict

URL = "https://exemple.fr/deliberation.pdf"
BESANCON = charger_tarif("grand_besancon_regie")


def _periode(debut, fin, prix_tranche_2, abonnement=12):
    return {
        "debut": debut,
        "fin": fin,
        "source": URL,
        "services": {
            "eau_potable": {
                "tva": 10,
                "abonnements": [{"nom": "Abonnement", "montant_ht_an": abonnement}],
                "composantes": [
                    {"nom": "Part", "tranches": [{"jusqua": 10, "prix_ht": 0}, {"prix_ht": prix_tranche_2}]}
                ],
            }
        },
    }


def _tarif(tranches="cumul_annuel"):
    return tarif_depuis_dict(
        {
            "id": "t",
            "nom": "T",
            "tranches": tranches,
            "periodes": [_periode("2025-01-01", "2025-12-31", 1), _periode("2026-01-01", None, 2, 24)],
        }
    )


def _ht(facture):
    return sum((s.ht for s in facture.services), Decimal(0))


# ── Référence Grand Besançon ──


def test_annee_2026_en_une_facture_retombe_sur_484_23() -> None:
    facture = facture_periode(BESANCON, date(2026, 1, 1), date(2027, 1, 1), 120)
    assert facture.total_ttc == Decimal("484.23")
    assert facture.prix_moyen_ttc == Decimal("4.0353")


def test_deux_semestres_valent_l_annee() -> None:
    """Règle ``cumul_annuel`` : deux semestres valent exactement l'année."""
    cumul = replace(BESANCON, tranches="cumul_annuel")
    s1 = facture_periode(cumul, date(2026, 1, 1), date(2026, 7, 1), 60)
    s2 = facture_periode(cumul, date(2026, 7, 1), date(2027, 1, 1), 60, cumul_annee=60)
    annee = facture_sur_un_an(cumul.periode_au(date(2026, 1, 1)), 120)
    assert _ht(s1) + _ht(s2) == _ht(annee)
    # Arrondi par facture : au plus un centime d'écart avec la facture annuelle.
    assert abs(s1.total_ttc + s2.total_ttc - Decimal("484.23")) <= Decimal("0.01")
    # 1er semestre : 3 m³ gratuits, puis 57 m³ dans la 2e tranche.
    part = [
        ligne
        for ligne in s1.lignes
        if ligne.libelle == "Part de la collectivité" and ligne.service == "eau_potable"
    ]
    assert [(ligne.quantite, ligne.prix_unitaire_ht) for ligne in part] == [
        (3, Decimal("0")),
        (57, Decimal("1.38")),
    ]
    # 2e semestre : 40 m³ jusqu'à 100, puis 20 m³ au-delà.
    part = [
        ligne
        for ligne in s2.lignes
        if ligne.libelle == "Part de la collectivité" and ligne.service == "eau_potable"
    ]
    assert [ligne.quantite for ligne in part] == [40, 20]


def test_besancon_tranches_proratisees() -> None:
    """Préréglage Grand Besançon : seuils x jours / 365 (issue #15, facture réelle)."""
    assert BESANCON.tranches == "prorata"
    s1 = facture_periode(BESANCON, date(2026, 1, 1), date(2026, 7, 1), 60)
    part = [
        ligne
        for ligne in s1.lignes
        if ligne.libelle == "Part de la collectivité" and ligne.service == "eau_potable"
    ]
    gratuit, usuel = Decimal(3) * 181 / 365, Decimal(100) * 181 / 365
    assert part[0].quantite == gratuit
    assert part[1].quantite == usuel - gratuit
    assert part[2].quantite == 60 - usuel


def test_abonnement_au_prorata_des_jours() -> None:
    facture = facture_periode(BESANCON, date(2026, 1, 1), date(2026, 7, 1), 0)
    abonnement = next(ligne for ligne in facture.lignes if ligne.libelle == "Abonnement eau potable")
    assert abonnement.quantite == Decimal(181) / 365
    assert abonnement.montant_ht == Decimal(15) * 181 / 365


# ── Bords ──


def test_volume_nul() -> None:
    facture = facture_periode(BESANCON, date(2026, 1, 1), date(2027, 1, 1), 0)
    assert facture.total_ttc == Decimal("26.83")  # abonnements seuls : 15 x 1,055 + 10 x 1,10
    assert facture.prix_moyen_ttc is None


def test_volume_exactement_sur_un_seuil() -> None:
    facture = facture_periode(_tarif(), date(2025, 1, 1), date(2026, 1, 1), 10)
    assert _ht(facture) == 12  # 10 m³ gratuits + abonnement
    assert prix_marginal(_tarif(), date(2025, 6, 1), 10).tranche == 2


def test_periode_a_cheval_sur_deux_tarifs() -> None:
    # 1/10/2025 → 1/4/2026 : 92 jours en 2025, 90 en 2026 ; 182 m³, soit 1 m³ par jour.
    morceaux = decouper(_tarif(), date(2025, 10, 1), date(2026, 4, 1), Decimal(182), Decimal(50))
    assert [(m.du, m.au, m.volume) for m in morceaux] == [
        (date(2025, 10, 1), date(2026, 1, 1), 92),
        (date(2026, 1, 1), date(2026, 4, 1), 90),
    ]
    assert [m.depuis for m in morceaux] == [50, 0]  # cumul remis à zéro au 1er janvier
    facture = facture_periode(_tarif(), date(2025, 10, 1), date(2026, 4, 1), 182, cumul_annee=50)
    attendu = (
        Decimal(12) * 92 / 365
        + 92 * 1  # 2025 : déjà au-delà des 10 m³ gratuits
        + Decimal(24) * 90 / 365
        + 80 * 2  # 2026 : 10 m³ gratuits, puis 80 m³ à 2 €
    )
    assert _ht(facture) == attendu
    assert facture.services[0].tva == attendu / 10


def test_changement_de_tarif_en_milieu_d_annee() -> None:
    tarif = tarif_depuis_dict(
        {
            "id": "t",
            "nom": "T",
            "periodes": [_periode("2026-01-01", "2026-06-30", 1), _periode("2026-07-01", None, 3)],
        }
    )
    morceaux = decouper(tarif, date(2026, 6, 1), date(2026, 8, 1), Decimal(61), Decimal(100))
    assert [(m.volume, m.depuis, m.periode.debut.month) for m in morceaux] == [(30, 100, 1), (31, 130, 7)]


def test_annee_bissextile() -> None:
    assert (jours_annee(2028), jours_annee(2026)) == (366, 365)
    tarif = tarif_depuis_dict({"id": "t", "nom": "T", "periodes": [_periode("2028-01-01", None, 1)]})
    assert _ht(facture_periode(tarif, date(2028, 1, 1), date(2029, 1, 1), 0)) == 12
    assert _ht(facture_periode(tarif, date(2028, 2, 1), date(2028, 3, 1), 0)) == Decimal(12) * 29 / 366


def test_tranches_proratisees() -> None:
    tarif = _tarif("prorata")
    # 73 jours = 1/5 de 2025 : le seuil de 10 m³ devient 2 m³.
    facture = facture_periode(tarif, date(2025, 1, 1), date(2025, 3, 15), 5, cumul_annee=999)
    part = [ligne for ligne in facture.lignes if ligne.libelle == "Part"]
    assert [ligne.quantite for ligne in part] == [2, 3]
    assert prix_marginal(tarif, date(2025, 1, 1), 1, Decimal(73) / 365).volume_restant == 1


def test_periode_invalide() -> None:
    with pytest.raises(ValueError, match="après son début"):
        facture_periode(BESANCON, date(2026, 7, 1), date(2026, 7, 1), 1)
    with pytest.raises(ValueError, match="négatif"):
        facture_periode(BESANCON, date(2026, 1, 1), date(2026, 7, 1), -1)


# ── Index ──


@pytest.mark.parametrize(
    ("ancien", "nouveau", "volume"),
    [(100, "112.5", "12.5"), (100, 100, 0), ("1234.567", 3, 3), (50, -1, 0)],
)
def test_consommation_et_remplacement_du_compteur(ancien, nouveau, volume) -> None:
    assert consommation(ancien, nouveau) == Decimal(volume)


# ── Prix marginal ──


def test_prix_marginal_besancon() -> None:
    jour = date(2026, 3, 1)
    gratuit = prix_marginal(BESANCON, jour, 0)
    # Redevances eau 0,485 x 1,055 + assainissement 1,70 x 1,10.
    assert gratuit.prix_ttc == Decimal("0.485") * Decimal("1.055") + Decimal("1.70") * Decimal("1.10")
    assert (gratuit.tranche, gratuit.volume_restant) == (1, 3)
    milieu = prix_marginal(BESANCON, jour, Decimal("42.5"))
    assert (milieu.tranche, milieu.volume_restant) == (2, Decimal("57.5"))
    assert milieu.prix_ttc - gratuit.prix_ttc == Decimal("1.38") * Decimal("1.055")
    haut = prix_marginal(BESANCON, jour, 100)
    assert (haut.tranche, haut.volume_restant) == (3, None)


def test_moteur_sans_home_assistant() -> None:
    """calcul.py et modele.py se chargent alors que Home Assistant est interdit d'import."""
    import subprocess
    import sys
    from pathlib import Path

    dossier = Path(__file__).parent.parent / "custom_components" / "tarifeau"
    script = f"""
import importlib.util, sys
sys.modules["homeassistant"] = None  # tout import de homeassistant échoue
for nom in ("modele", "calcul"):
    spec = importlib.util.spec_from_file_location(nom, r"{dossier}" + f"/{{nom}}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
print("ok")
"""
    sortie = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    assert sortie.stdout.strip() == "ok"
