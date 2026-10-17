"""Moteur de calcul, sans Home Assistant (issue #1, socle de #3)."""

from decimal import Decimal

import pytest

from custom_components.tarifeau.calcul import arrondi_euros


@pytest.mark.parametrize(
    ("montant", "attendu"),
    [
        ("484.225", "484.23"),
        ("484.2249", "484.22"),
        (12, "12.00"),
        (Decimal("0.005"), "0.01"),
        ("-1.005", "-1.01"),
    ],
)
def test_arrondi_au_centime(montant, attendu) -> None:
    assert arrondi_euros(montant) == Decimal(attendu)
