"""Chaque préréglage de tarifs/ (issue #7) : schéma, dates, sources, factures types."""

from datetime import date
from decimal import Decimal

import pytest

from custom_components.tarifeau.calcul import facture_sur_un_an
from custom_components.tarifeau.modele import charger_tarif, prereglages

PREREGLAGES = prereglages()


def test_au_moins_les_deux_collectivites_de_depart() -> None:
    assert {"grand_besancon_regie", "grand_belfort"} <= set(PREREGLAGES)


@pytest.mark.parametrize("identifiant", PREREGLAGES)
def test_prereglage_valide(identifiant: str) -> None:
    tarif = charger_tarif(identifiant)  # schéma, tranches, périodes sans trou ni chevauchement
    assert tarif.id == identifiant, "l'id doit être le nom du fichier"
    for periode in tarif.periodes:
        assert periode.source.startswith("https://"), "source officielle en https"
        assert periode.debut >= date(2020, 1, 1)
        for facture_type in periode.factures_types:
            facture = facture_sur_un_an(periode, facture_type.volume_m3)
            assert facture.total_ttc == facture_type.total_ttc, (
                f"{identifiant} au {periode.debut} : {facture.total_ttc} € calculés pour "
                f"{facture_type.volume_m3} m³, {facture_type.total_ttc} € publiés"
            )


def test_belfort_120_m3() -> None:
    periode = charger_tarif("grand_belfort").periode_au(date(2026, 6, 1))
    facture = facture_sur_un_an(periode, 120)
    par_service = {s.service: s for s in facture.services}
    assert round(par_service["eau_potable"].ttc, 2) == Decimal("305.44")
    assert par_service["assainissement"].tva == 0  # assainissement non assujetti
    assert facture.total_ttc == Decimal("624.32")
