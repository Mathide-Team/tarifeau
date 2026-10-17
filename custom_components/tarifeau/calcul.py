"""Moteur de calcul de la facture, en Python pur (aucune dépendance à Home Assistant).

Squelette (issue #1) : seul l'arrondi monétaire est posé ici. Le modèle de tarif
(issue #2) et le moteur complet (issue #3 : prorata, tranches, gratuité,
changement de tarif) s'appuient sur ce module, testable seul par pytest.

Le moteur vit dans ``custom_components/tarifeau/`` et non dans un paquet
``tarifeau/`` à la racine : HACS n'installe que ``custom_components/<domaine>``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENTIME = Decimal("0.01")


def arrondi_euros(montant: Decimal | int | str) -> Decimal:
    """Arrondit un montant au centime, au plus proche (0,005 € → 0,01 €), comme une facture."""
    return Decimal(str(montant)).quantize(CENTIME, rounding=ROUND_HALF_UP)
