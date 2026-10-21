"""Moteur de calcul de la facture (issue #3), en Python pur (aucune dépendance à Home Assistant).

Règles, dans l'ordre où elles s'appliquent :

1. La période facturée ``[du, au[`` est découpée au 1er janvier et à chaque changement
   de tarif. Le volume est réparti entre les morceaux **au prorata des jours**, comme
   sur les factures.
2. **Abonnement** : montant annuel x jours du morceau / jours de l'année (365 ou 366).
3. **Tranches** (seuils annuels du tarif), selon ``Tarif.tranches`` :
   - ``cumul_annuel`` : appliquées au volume cumulé depuis le 1er janvier
     (``cumul_annee`` = volume déjà facturé cette année avant ``du``), remis à zéro
     au 1er janvier ;
   - ``prorata`` : seuils multipliés par jours / jours de l'année, et volume compté
     depuis le début de la facture.
   La gratuité des premiers m³ est une tranche à 0 €.
4. HT par ligne, TVA **par service** (5,5 % eau potable, 10 % assainissement…), puis TTC.
   Les montants restent exacts, et seul le total de la facture est arrondi au centime.

Le moteur vit dans ``custom_components/tarifeau/`` et non dans un paquet
``tarifeau/`` à la racine : HACS n'installe que ``custom_components/<domaine>``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise
from typing import TYPE_CHECKING

_LOGGER = logging.getLogger(__name__)

try:
    from .journal import resumer
except ImportError as err:  # module chargé seul, hors paquet (scripts, test sans Home Assistant)
    _LOGGER.debug("hors paquet, résumé du journal réduit au type : %s", err)

    def resumer(valeur: object) -> str:
        """Repli hors paquet : le type seul, jamais la valeur."""
        return f"<{type(valeur).__name__}>"


if TYPE_CHECKING:  # pragma: no cover
    from .modele import Periode, Service, Tarif

CENTIME = Decimal("0.01")


def arrondi_euros(montant: Decimal | int | str) -> Decimal:
    """Arrondit un montant au centime, au plus proche (0,005 € → 0,01 €), comme une facture."""
    return Decimal(str(montant)).quantize(CENTIME, rounding=ROUND_HALF_UP)


CENT = Decimal(100)
ZERO = Decimal(0)


def jours_annee(annee: int) -> int:
    """365, ou 366 pour une année bissextile."""
    return (date(annee + 1, 1, 1) - date(annee, 1, 1)).days


def consommation(ancien_index: Decimal | int | str, nouvel_index: Decimal | int | str) -> Decimal:
    """Volume entre deux index (m³).

    Si l'index revient en arrière, on considère que le compteur a été remplacé : le volume
    est alors celui du nouveau compteur, soit son index (il part de zéro).
    """
    _LOGGER.debug(
        "consommation: entrée | ancien_index=%s, nouvel_index=%s",
        resumer(ancien_index),
        resumer(nouvel_index),
    )
    ancien, nouveau = Decimal(str(ancien_index)), Decimal(str(nouvel_index))
    _LOGGER.debug("consommation: sortie")
    return nouveau - ancien if nouveau >= ancien else max(nouveau, ZERO)


@dataclass(frozen=True)
class Ligne:
    """Une ligne de facture : un abonnement, ou une tranche d'une composante."""

    service: str
    libelle: str
    quantite: Decimal  # m³, ou fraction d'année pour un abonnement
    prix_unitaire_ht: Decimal  # € HT/m³, ou € HT/an
    montant_ht: Decimal
    redevance: bool = False
    du: date | None = None
    au: date | None = None  # exclu
    unite: str = "m³"  # « an » pour un abonnement (quantité = fraction d'année)


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
    """Détail et totaux. ``total_ht`` et ``total_ttc`` sont arrondis au centime, une seule fois."""

    lignes: tuple[Ligne, ...]
    services: tuple[TotalService, ...]
    volume: Decimal = ZERO

    @property
    def total_ht(self) -> Decimal:
        return arrondi_euros(sum((s.ht for s in self.services), ZERO))

    @property
    def total_ttc(self) -> Decimal:
        return arrondi_euros(sum((s.ttc for s in self.services), ZERO))

    @property
    def prix_moyen_ttc(self) -> Decimal | None:
        """Total TTC / volume, en €/m³ à 4 décimales, abonnements compris. ``None`` si aucun volume."""
        _LOGGER.debug("Facture.prix_moyen_ttc: entrée")
        if not self.volume:
            _LOGGER.debug("Facture.prix_moyen_ttc: sortie | None")
            return None
        _LOGGER.debug("Facture.prix_moyen_ttc: sortie")
        return arrondi_euros(sum((s.ttc for s in self.services), ZERO) / self.volume * CENT) / CENT


@dataclass(frozen=True)
class Morceau:
    """Partie d'une facture sous un seul tarif et dans une seule année civile."""

    du: date
    au: date  # exclu
    periode: Periode
    volume: Decimal
    depuis: Decimal  # volume déjà compté dans les tranches
    facteur_seuils: Decimal
    fraction_annee: Decimal


def decouper(tarif: Tarif, du: date, au: date, volume: Decimal, cumul_annee: Decimal = ZERO) -> list[Morceau]:
    """Découpe ``[du, au[`` au 1er janvier et aux changements de tarif (voir l'en-tête du module)."""
    _LOGGER.debug(
        "decouper: entrée | tarif=%s, du=%s, au=%s, volume=%s, cumul_annee=%s",
        resumer(tarif),
        resumer(du),
        resumer(au),
        resumer(volume),
        resumer(cumul_annee),
    )
    if au <= du:
        _LOGGER.debug("decouper: sortie par ValueError")
        raise ValueError("la fin de la période doit être après son début")
    if volume < 0 or cumul_annee < 0:
        _LOGGER.debug("decouper: sortie par ValueError")
        raise ValueError("volume négatif")
    coupures = {du, au}
    coupures |= {date(a, 1, 1) for a in range(du.year + 1, au.year + 1)}
    for periode in tarif.periodes:
        coupures.add(periode.debut)
        if periode.fin is not None:
            coupures.add(periode.fin + timedelta(days=1))
    bornes = sorted(c for c in coupures if du <= c <= au)
    jours_total = Decimal((au - du).days)
    morceaux: list[Morceau] = []
    reparti, cumul = ZERO, cumul_annee
    for a, b in pairwise(bornes):
        dernier = b == au
        v = volume - reparti if dernier else volume * (b - a).days / jours_total
        reparti += v
        fraction = Decimal((b - a).days) / jours_annee(a.year)
        if a != du and a.month == 1 and a.day == 1:
            cumul = ZERO  # nouvelle année tarifaire
        if tarif.tranches == "prorata":
            depuis, facteur = ZERO, fraction
        else:
            depuis, facteur = cumul, Decimal(1)
        morceaux.append(Morceau(a, b, tarif.periode_au(a), v, depuis, facteur, fraction))
        cumul += v
    _LOGGER.debug("decouper: sortie | %s", resumer(morceaux))
    return morceaux


def _lignes(service: Service, morceau: Morceau) -> list[Ligne]:
    _LOGGER.debug("_lignes: entrée | service=%s, morceau=%s", resumer(service), resumer(morceau))
    lignes = [
        Ligne(
            service.code,
            a.nom,
            morceau.fraction_annee,
            a.montant_ht_an,
            a.montant_ht_an * morceau.fraction_annee,
            du=morceau.du,
            au=morceau.au,
            unite="an",
        )
        for a in service.abonnements
    ]
    for composante in service.composantes:
        repartition = composante.volumes_par_tranche(morceau.volume, morceau.depuis, morceau.facteur_seuils)
        for tranche, quantite in repartition:
            if quantite or len(repartition) == 1:
                lignes.append(
                    Ligne(
                        service.code,
                        composante.nom,
                        quantite,
                        tranche.prix_ht,
                        quantite * tranche.prix_ht,
                        composante.redevance,
                        morceau.du,
                        morceau.au,
                    )
                )
    _LOGGER.debug("_lignes: sortie | %s", resumer(lignes))
    return lignes


def _facture(morceaux: list[Morceau], volume: Decimal) -> Facture:
    _LOGGER.debug("_facture: entrée | morceaux=%s, volume=%s", resumer(morceaux), resumer(volume))
    lignes: list[Ligne] = []
    totaux: dict[str, list[Decimal]] = {}  # service → [HT, TVA, taux]
    for morceau in morceaux:
        for service in morceau.periode.services:
            lignes_service = _lignes(service, morceau)
            ht = sum((ligne.montant_ht for ligne in lignes_service), ZERO)
            total = totaux.setdefault(service.code, [ZERO, ZERO, service.tva])
            total[0] += ht
            total[1] += ht * service.tva / CENT
            total[2] = service.tva
            lignes += lignes_service
    services = tuple(TotalService(code, ht, tva, taux) for code, (ht, tva, taux) in totaux.items())
    _LOGGER.debug("_facture: sortie")
    return Facture(tuple(lignes), services, volume)


def facture_periode(
    tarif: Tarif,
    du: date,
    au: date,
    volume_m3: Decimal | int | str,
    cumul_annee: Decimal | int | str = 0,
) -> Facture:
    """Facture de ``volume_m3`` m³ consommés du ``du`` (inclus) au ``au`` (exclu).

    ``cumul_annee`` : m³ déjà facturés depuis le 1er janvier de l'année de ``du``
    (tranches ``cumul_annuel`` seulement).
    """
    _LOGGER.debug(
        "facture_periode: entrée | tarif=%s, du=%s, au=%s, volume_m3=%s, cumul_annee=%s",
        resumer(tarif),
        resumer(du),
        resumer(au),
        resumer(volume_m3),
        resumer(cumul_annee),
    )
    volume = Decimal(str(volume_m3))
    _LOGGER.debug("facture_periode: sortie")
    return _facture(decouper(tarif, du, au, volume, Decimal(str(cumul_annee))), volume)


def facture_sur_un_an(periode: Periode, volume_m3: Decimal | int | str) -> Facture:
    """Facture d'une année complète au tarif ``periode``, pour vérifier une facture type (120 m³)."""
    _LOGGER.debug(
        "facture_sur_un_an: entrée | periode=%s, volume_m3=%s", resumer(periode), resumer(volume_m3)
    )
    volume = Decimal(str(volume_m3))
    if volume < 0:
        _LOGGER.debug("facture_sur_un_an: sortie par ValueError")
        raise ValueError("volume négatif")
    _LOGGER.debug("facture_sur_un_an: sortie")
    return _facture(
        [Morceau(periode.debut, periode.debut, periode, volume, ZERO, Decimal(1), Decimal(1))], volume
    )


@dataclass(frozen=True)
class Marginal:
    """Ce que coûte le prochain m³, et jusqu'où ce prix tient."""

    prix_ttc: Decimal  # €/m³ TTC
    tranche: int  # 1 = première tranche
    volume_restant: Decimal | None  # m³ avant le prochain changement de prix, None : dernière tranche


def prix_marginal(
    tarif: Tarif, jour: date, cumul_annee: Decimal | int | str, facteur_seuils: Decimal | int | str = 1
) -> Marginal:
    """Prix TTC du prochain m³ le ``jour`` donné, après ``cumul_annee`` m³ comptés dans les tranches.

    Pour des tranches ``prorata``, passer le volume depuis le début de la facture, et
    ``facteur_seuils`` = jours de la facture / jours de l'année.
    """
    _LOGGER.debug(
        "prix_marginal: entrée | tarif=%s, jour=%s, cumul_annee=%s, facteur_seuils=%s",
        resumer(tarif),
        resumer(jour),
        resumer(cumul_annee),
        resumer(facteur_seuils),
    )
    cumul, facteur = Decimal(str(cumul_annee)), Decimal(str(facteur_seuils))
    prix, tranche, restant = ZERO, 0, None
    for service in tarif.periode_au(jour).services:
        for composante in service.composantes:
            indice, reste = composante.tranche_au(cumul, facteur)
            prix += composante.tranches[indice].prix_ht * (CENT + service.tva) / CENT
            tranche = max(tranche, indice)
            if reste is not None:
                restant = reste if restant is None else min(restant, reste)
    _LOGGER.debug("prix_marginal: sortie")
    return Marginal(prix, tranche + 1, restant)
