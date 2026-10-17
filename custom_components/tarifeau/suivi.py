"""Suivi d'une facture (issue #5) : relit l'index à chaque changement et recalcule.

Pas d'interrogation périodique : le calcul se refait à chaque nouvel état du capteur
d'index, et une fois à minuit (l'abonnement court au jour le jour).
"""

from __future__ import annotations

import calendar
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.util import dt as dt_util

from .calcul import Facture, Marginal, consommation, facture_periode, prix_marginal
from .const import (
    CONF_ASSAINISSEMENT,
    CONF_DATE_RELEVE,
    CONF_FACTURATION,
    CONF_INDEX,
    CONF_INDEX_RELEVE,
    CONF_PREREGLAGE,
    CONF_PRIX_FIXE,
    CONF_SOURCE,
    SOURCE_PREREGLAGE,
    UNITES_INDEX,
)
from .modele import Tarif, charger_tarif, prolonger, sans_assainissement, tarif_prix_fixe

_LOGGER = logging.getLogger(__name__)

MOIS_PAR_FACTURATION = {"annuelle": 12, "semestrielle": 6}


def ajouter_mois(jour: date, mois: int) -> date:
    """``jour`` + ``mois`` mois, ramené au dernier jour du mois si besoin (31/08 + 6 mois → 28/02)."""
    total = jour.month - 1 + mois
    annee, mois_cible = jour.year + total // 12, total % 12 + 1
    return date(annee, mois_cible, min(jour.day, calendar.monthrange(annee, mois_cible)[1]))


def charger_tarif_config(config: dict[str, Any]) -> Tarif:
    """Tarif de l'entrée (lecture de fichier : à appeler hors de la boucle d'événements)."""
    if config.get(CONF_SOURCE) == SOURCE_PREREGLAGE:
        tarif = charger_tarif(config[CONF_PREREGLAGE])
        return tarif if config.get(CONF_ASSAINISSEMENT, True) else sans_assainissement(tarif)
    return tarif_prix_fixe(config[CONF_PRIX_FIXE])


@dataclass(frozen=True)
class Etat:
    """Résultat d'un calcul, lu par les capteurs."""

    index: Decimal
    volume: Decimal
    facture: Facture
    estimation: Facture | None
    fin_periode: date
    marginal: Marginal
    tarif: Tarif
    jour: date
    tarif_prolonge: bool = False  # dates hors du tarif connu : dernier tarif prolongé


@dataclass
class SuiviFacture:
    """Calcule la facture en cours d'une entrée et prévient les capteurs."""

    hass: HomeAssistant
    config: dict[str, Any]
    tarif: Tarif
    etat: Etat | None = None
    _ecouteurs: list[Callable[[], None]] = field(default_factory=list)
    _desabonnements: list[Callable[[], None]] = field(default_factory=list)
    _averti: bool = False

    @property
    def date_releve(self) -> date:
        return date.fromisoformat(self.config[CONF_DATE_RELEVE])

    @property
    def fin_periode(self) -> date:
        mois = MOIS_PAR_FACTURATION.get(self.config.get(CONF_FACTURATION, "semestrielle"), 6)
        return ajouter_mois(self.date_releve, mois)

    def lire_index(self) -> Decimal | None:
        """Index actuel en m³, ou ``None`` s'il est indisponible."""
        etat = self.hass.states.get(self.config[CONF_INDEX])
        if etat is None:
            return None
        diviseur = UNITES_INDEX.get(etat.attributes.get(ATTR_UNIT_OF_MEASUREMENT, ""))
        try:
            return Decimal(etat.state) / diviseur if diviseur else None
        except ArithmeticError:
            return None

    def calculer(self, index: Decimal, jour: date) -> Etat:
        """Facture depuis la relève jusqu'à ``jour`` inclus, et projection à la fin de la période."""
        releve, fin = self.date_releve, self.fin_periode
        volume = consommation(Decimal(str(self.config[CONF_INDEX_RELEVE])), index)
        au = max(jour + timedelta(days=1), releve + timedelta(days=1))
        jours = (au - releve).days
        # Volume déjà passé dans les tranches cette année avant la relève, estimé au rythme actuel.
        cumul = volume / jours * (releve - date(releve.year, 1, 1)).days
        tarif, prolonge = prolonger(self.tarif, releve, max(au, fin))
        if prolonge and not self._averti:
            _LOGGER.warning(
                "%s : pas de tarif connu du %s au %s, le tarif le plus proche est prolongé",
                self.tarif.nom,
                releve.isoformat(),
                max(au, fin).isoformat(),
            )
            self._averti = True
        facture = facture_periode(tarif, releve, au, volume, cumul)
        estimation = None
        if au < fin:
            projete = volume * (fin - releve).days / jours
            estimation = facture_periode(tarif, releve, fin, projete, cumul)
        cumul_jour = (
            cumul + volume
            if jour.year == releve.year
            else volume * (jour - date(jour.year, 1, 1)).days / jours
        )
        marginal = prix_marginal(tarif, jour, cumul_jour)
        return Etat(index, volume, facture, estimation, fin, marginal, self.tarif, jour, prolonge)

    @callback
    def rafraichir(self, *_: Any) -> None:
        """Recalcule si l'index est lisible ; sinon garde le dernier état."""
        index = self.lire_index()
        if index is not None:
            self.etat = self.calculer(index, dt_util.now().date())
        for ecouteur in list(self._ecouteurs):
            ecouteur()

    @callback
    def ecouter(self, ecouteur: Callable[[], None]) -> Callable[[], None]:
        """Abonne un capteur aux mises à jour. Renvoie la fonction de désabonnement."""
        self._ecouteurs.append(ecouteur)
        return lambda: self._ecouteurs.remove(ecouteur)

    @callback
    def demarrer(self) -> None:
        """Suit l'index et minuit."""

        @callback
        def _sur_index(event: Event[EventStateChangedData]) -> None:
            self.rafraichir()

        self._desabonnements += [
            async_track_state_change_event(self.hass, [self.config[CONF_INDEX]], _sur_index),
            async_track_time_change(self.hass, self.rafraichir, hour=0, minute=0, second=5),
        ]
        self.rafraichir()

    @callback
    def arreter(self) -> None:
        """Arrête le suivi (déchargement de l'entrée)."""
        while self._desabonnements:
            self._desabonnements.pop()()
