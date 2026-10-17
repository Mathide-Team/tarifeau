"""Moteur de calcul de la facture, en Python pur (aucune dépendance à Home Assistant).

Contient l'arrondi monétaire et la facture d'une année complète (issue #2). Le moteur
complet (issue #3 : prorata, tranches, gratuité, changement de tarif) s'appuiera sur ce
module, testable seul par pytest.

Le moteur vit dans ``custom_components/tarifeau/`` et non dans un paquet
``tarifeau/`` à la racine : HACS n'installe que ``custom_components/<domaine>``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .modele import Periode

CENTIME = Decimal("0.01")


def arrondi_euros(montant: Decimal | int | str) -> Decimal:
    """Arrondit un montant au centime, au plus proche (0,005 € → 0,01 €), comme une facture."""
    return Decimal(str(montant)).quantize(CENTIME, rounding=ROUND_HALF_UP)


# ── Facture sur une année complète (issue #2) ───────────────────────────────
# Sert à vérifier un tarif contre la facture type de la collectivité (120 m³/an).
# Le moteur complet (prorata des jours, factures semestrielles, changement de
# tarif) arrive avec l'issue #3.

CENT = Decimal(100)


@dataclass(frozen=True)
class Ligne:
    """Une ligne de facture : abonnement, ou une tranche d'une composante."""

    service: str
    libelle: str
    quantite: Decimal  # m³, ou fraction d'année pour un abonnement
    prix_unitaire_ht: Decimal
    montant_ht: Decimal
    redevance: bool = False


@dataclass(frozen=True)
class TotalService:
    """Totaux exacts d'un service (non arrondis : l'arrondi se fait sur la facture)."""

    service: str
    ht: Decimal
    tva: Decimal
    taux_tva: Decimal

    @property
    def ttc(self) -> Decimal:
        return self.ht + self.tva


@dataclass(frozen=True)
class Facture:
    """Détail et totaux. ``total_ttc`` est arrondi au centime, une seule fois."""

    lignes: tuple[Ligne, ...]
    services: tuple[TotalService, ...]

    @property
    def total_ht(self) -> Decimal:
        return arrondi_euros(sum((s.ht for s in self.services), Decimal(0)))

    @property
    def total_ttc(self) -> Decimal:
        return arrondi_euros(sum((s.ttc for s in self.services), Decimal(0)))


def facture_sur_un_an(periode: Periode, volume_m3: Decimal | int | str) -> Facture:
    """Facture d'une année complète au tarif ``periode`` pour ``volume_m3`` m³ consommés."""
    volume = Decimal(str(volume_m3))
    if volume < 0:
        raise ValueError("volume négatif")
    lignes: list[Ligne] = []
    totaux: list[TotalService] = []
    for service in periode.services:
        lignes_service = [
            Ligne(service.code, a.nom, Decimal(1), a.montant_ht_an, a.montant_ht_an)
            for a in service.abonnements
        ]
        for composante in service.composantes:
            for tranche, quantite in composante.volumes_par_tranche(volume):
                if quantite or len(composante.tranches) == 1:
                    lignes_service.append(
                        Ligne(
                            service.code,
                            composante.nom,
                            quantite,
                            tranche.prix_ht,
                            quantite * tranche.prix_ht,
                            composante.redevance,
                        )
                    )
        ht = sum((ligne.montant_ht for ligne in lignes_service), Decimal(0))
        totaux.append(TotalService(service.code, ht, ht * service.tva / CENT, service.tva))
        lignes += lignes_service
    return Facture(tuple(lignes), tuple(totaux))
