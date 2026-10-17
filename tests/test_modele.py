"""Modèle de tarif : lecture, validation, préréglages (issue #2)."""

from datetime import date
from decimal import Decimal

import pytest

from custom_components.tarifeau.calcul import facture_sur_un_an
from custom_components.tarifeau.modele import (
    DOSSIER_TARIFS,
    TarifInvalide,
    charger_tarif,
    prereglages,
    tarif_depuis_dict,
)

URL = "https://exemple.fr/deliberation.pdf"


def _tarif(**surcharges):
    donnees = {
        "id": "test",
        "nom": "Test",
        "periodes": [
            {
                "debut": "2026-01-01",
                "source": URL,
                "services": {
                    "eau_potable": {"tva": 5.5, "composantes": [{"nom": "Part", "prix_ht": "1,50"}]}
                },
            }
        ],
    }
    donnees.update(surcharges)
    return donnees


# ── Cas de référence : Grand Besançon 2026 ──


def test_besancon_2026_120_m3_donne_484_23() -> None:
    tarif = charger_tarif("grand_besancon_regie")
    facture = facture_sur_un_an(tarif.periode_au(date(2026, 6, 1)), 120)
    par_service = {s.service: s for s in facture.services}
    # Factures types du RPQS 2025 : 248,83 € (eau) + 235,40 € (assainissement).
    assert round(par_service["eau_potable"].ttc, 2) == Decimal("248.83")
    assert round(par_service["assainissement"].ttc, 2) == Decimal("235.40")
    assert facture.total_ttc == Decimal("484.23")
    assert facture.total_ht == Decimal("449.86")


def test_besancon_3_premiers_m3_gratuits_mais_pas_les_redevances() -> None:
    periode = charger_tarif("grand_besancon_regie").periode_au(date(2026, 1, 1))
    eau = facture_sur_un_an(periode, 3).services[0]
    # 15 € d'abonnement + 3 m³ fois 0,485 € de redevances ; part de la collectivité gratuite.
    assert eau.ht == Decimal("15") + 3 * Decimal("0.485")


def test_tous_les_prereglages_sont_valides() -> None:
    assert "grand_besancon_regie" in prereglages()
    for identifiant in prereglages():
        tarif = charger_tarif(identifiant)
        assert tarif.id == identifiant
        assert all(p.source.startswith("https://") for p in tarif.periodes)


def test_chargement_par_chemin(tmp_path) -> None:
    fichier = tmp_path / "t.yaml"
    fichier.write_text((DOSSIER_TARIFS / "grand_besancon_regie.yaml").read_text(encoding="utf-8"))
    assert charger_tarif(fichier).nom == "Grand Besançon Métropole (régie)"


def test_yaml_invalide(tmp_path) -> None:
    fichier = tmp_path / "t.yaml"
    fichier.write_text("id: [", encoding="utf-8")
    with pytest.raises(TarifInvalide, match="YAML invalide"):
        charger_tarif(fichier)


# ── Schéma ──


def test_valeurs_par_defaut_et_virgule_decimale() -> None:
    tarif = tarif_depuis_dict(_tarif())
    assert (tarif.facturation, tarif.tranches) == ("semestrielle", "cumul_annuel")
    composante = tarif.periodes[0].services[0].composantes[0]
    assert composante.tranches[0].prix_ht == Decimal("1.50")
    assert tarif.periodes[0].date_source == date(2026, 1, 1)


def test_periodes_triees_et_recherche() -> None:
    p2025 = {**_tarif()["periodes"][0], "debut": "2025-01-01", "fin": date(2025, 12, 31)}
    tarif = tarif_depuis_dict(_tarif(periodes=[_tarif()["periodes"][0], p2025]))
    assert [p.debut.year for p in tarif.periodes] == [2025, 2026]
    assert tarif.periode_au(date(2025, 12, 31)).debut.year == 2025
    assert tarif.periode_au(date(2030, 1, 1)).debut.year == 2026
    with pytest.raises(LookupError, match="aucun tarif"):
        tarif.periode_au(date(2024, 12, 31))


def test_tranches_reparties() -> None:
    composante = (
        tarif_depuis_dict(
            _tarif(
                periodes=[
                    {
                        "debut": "2026-01-01",
                        "source": URL,
                        "services": {
                            "eau_potable": {
                                "tva": 5.5,
                                "composantes": [
                                    {
                                        "nom": "Part",
                                        "tranches": [
                                            {"jusqua": 3, "prix_ht": 0},
                                            {"jusqua": 100, "prix_ht": 1},
                                            {"prix_ht": 2},
                                        ],
                                    }
                                ],
                            }
                        },
                    }
                ]
            )
        )
        .periodes[0]
        .services[0]
        .composantes[0]
    )
    volumes = lambda v: [q for _, q in composante.volumes_par_tranche(Decimal(v))]  # noqa: E731
    assert volumes(0) == [0, 0, 0]
    assert volumes(3) == [3, 0, 0]
    assert volumes(100) == [3, 97, 0]
    assert volumes("120.5") == [3, 97, Decimal("20.5")]


def _service(**service):
    return _tarif(periodes=[{"debut": "2026-01-01", "source": URL, "services": {"eau_potable": service}}])


@pytest.mark.parametrize(
    ("donnees", "message"),
    [
        ([], "objet attendu"),
        ({"id": "x", "nom": "x"}, "manquante"),
        (_tarif(inconnu=1), "inconnue"),
        (_tarif(id=" "), "texte non vide"),
        (_tarif(facturation="hebdo"), "facturation"),
        (_tarif(tranches="autre"), "tarif.tranches"),
        (_tarif(periodes=[]), "au moins un élément"),
        (_tarif(periodes={}), "liste attendue"),
        (_tarif(periodes=[{**_tarif()["periodes"][0], "debut": "2026-13-01"}]), "date AAAA-MM-JJ"),
        (_tarif(periodes=[{**_tarif()["periodes"][0], "fin": "2025-01-01"}]), "antérieure"),
        (_tarif(periodes=[{**_tarif()["periodes"][0], "source": "ftp://x"}]), "URL"),
        (_tarif(periodes=[{**_tarif()["periodes"][0], "services": {}}]), "au moins un service"),
        (_tarif(periodes=[{**_tarif()["periodes"][0], "services": {"gaz": {"tva": 5}}}]), "service inconnu"),
        (_service(tva=120, composantes=[{"nom": "P", "prix_ht": 1}]), "entre 0 et 100"),
        (_service(tva=5.5), "ni abonnement ni composante"),
        (_service(tva="abc"), "nombre attendu"),
        (_service(tva="NaN"), "nombre fini"),
        (_service(tva=True), "nombre attendu"),
        (_service(tva=5.5, abonnements=[{"nom": "A", "montant_ht_an": -1}]), "positif"),
        (_service(tva=5.5, composantes=[{"nom": "P"}]), "« prix_ht » ou « tranches » attendu"),
        (_service(tva=5.5, composantes=[{"nom": "P", "prix_ht": 1, "tranches": []}]), "pas les deux"),
        (_service(tva=5.5, composantes=[{"nom": "P", "prix_ht": 1, "redevance": "oui"}]), "true ou false"),
        (_service(tva=5.5, composantes=[{"nom": "P", "tranches": []}]), "au moins un élément"),
        (
            _service(tva=5.5, composantes=[{"nom": "P", "tranches": [{"jusqua": 3, "prix_ht": 0}]}]),
            "dernière tranche",
        ),
        (
            _service(tva=5.5, composantes=[{"nom": "P", "tranches": [{"prix_ht": 0}, {"prix_ht": 1}]}]),
            "seuil",
        ),
        (
            _service(
                tva=5.5,
                composantes=[
                    {
                        "nom": "P",
                        "tranches": [
                            {"jusqua": 5, "prix_ht": 0},
                            {"jusqua": 5, "prix_ht": 1},
                            {"prix_ht": 2},
                        ],
                    }
                ],
            ),
            "croître",
        ),
    ],
)
def test_tarifs_refuses(donnees, message) -> None:
    with pytest.raises(TarifInvalide, match=message):
        tarif_depuis_dict(donnees)


@pytest.mark.parametrize(
    ("fin_2025", "debut_2026", "message"),
    [
        (None, "2026-01-01", "doit avoir une « fin »"),
        ("2026-01-05", "2026-01-01", "chevauche"),
        ("2025-12-30", "2026-01-01", "trou"),
    ],
)
def test_periodes_sans_trou_ni_chevauchement(fin_2025, debut_2026, message) -> None:
    base = _tarif()["periodes"][0]
    periodes = [{**base, "debut": "2025-01-01", "fin": fin_2025}, {**base, "debut": debut_2026}]
    with pytest.raises(TarifInvalide, match=message):
        tarif_depuis_dict(_tarif(periodes=periodes))


def test_sources_par_composante_et_abonnement() -> None:
    service = (
        tarif_depuis_dict(
            _service(
                tva=10,
                abonnements=[{"nom": "A", "montant_ht_an": 10, "source": URL}],
                composantes=[{"nom": "P", "prix_ht": 1, "source": URL}],
            )
        )
        .periodes[0]
        .services[0]
    )
    assert service.abonnements[0].source == service.composantes[0].source == URL


def test_prix_fixe_et_sans_assainissement() -> None:
    from custom_components.tarifeau.modele import sans_assainissement, tarif_prix_fixe

    fixe = tarif_prix_fixe("4,20")
    facture = facture_sur_un_an(fixe.periode_au(date(2026, 1, 1)), 10)
    assert facture.total_ttc == Decimal("42.00")
    eau_seule = sans_assainissement(charger_tarif("grand_besancon_regie"))
    assert [s.code for s in eau_seule.periodes[0].services] == ["eau_potable"]
    assert facture_sur_un_an(eau_seule.periodes[0], 120).total_ttc == Decimal("248.83")
