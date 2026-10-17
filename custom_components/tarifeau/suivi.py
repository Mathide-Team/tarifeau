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
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .calcul import Facture, Marginal, arrondi_euros, consommation, facture_periode, prix_marginal
from .const import (
    CONF_ASSAINISSEMENT,
    CONF_DATE_RELEVE,
    CONF_DIAMETRE,
    CONF_ENTITE_PRIX,
    CONF_FACTURATION,
    CONF_INDEX,
    CONF_INDEX_RELEVE,
    CONF_MONTANT_FACTURE,
    CONF_PREREGLAGE,
    CONF_PRIX_FIXE,
    CONF_SOURCE,
    CONF_VOLUME_FACTURE,
    SOURCE_ENTITE_PRIX,
    SOURCE_PREREGLAGE,
    SOURCE_TAUX_FACTURE,
    UNITES_INDEX,
)
from .modele import Tarif, avec_diametre, charger_tarif, prolonger, sans_assainissement, tarif_prix_fixe

_LOGGER = logging.getLogger(__name__)

MOIS_PAR_FACTURATION = {"annuelle": 12, "semestrielle": 6}


def ajouter_mois(jour: date, mois: int) -> date:
    """``jour`` + ``mois`` mois, ramené au dernier jour du mois si besoin (31/08 + 6 mois → 28/02)."""
    total = jour.month - 1 + mois
    annee, mois_cible = jour.year + total // 12, total % 12 + 1
    return date(annee, mois_cible, min(jour.day, calendar.monthrange(annee, mois_cible)[1]))


def _ttc(facture: Facture) -> Decimal:
    return sum((s.ttc for s in facture.services), Decimal(0))


def unite_prix_valide(unite: str | None) -> bool:
    """Unité d'un capteur de prix au m³ : « €/m³ », « EUR/m³ »…"""
    return bool(unite) and unite.replace(" ", "").endswith("/m³")


def prix_entite(etat: State | None) -> Decimal | None:
    """Prix au m³ lu sur un capteur (HydroTarif…), ``None`` s'il est indisponible ou invalide."""
    if etat is None or not unite_prix_valide(etat.attributes.get(ATTR_UNIT_OF_MEASUREMENT)):
        return None
    try:
        prix = Decimal(etat.state)
    except ArithmeticError:
        return None
    return prix if prix.is_finite() and prix >= 0 else None


def tarif_entite(etat: State, prix: Decimal) -> Tarif:
    """Tarif « prix moyen » construit d'après un capteur de prix (HydroTarif : D102.0 de SISPEA)."""
    source = etat.attributes.get("water_source_url") or f"entité {etat.entity_id}"
    annee = etat.attributes.get("water_data_year")
    # SISPEA, année N : tarif en vigueur au 1er janvier N+1 (convention de HydroTarif).
    date_source = date(annee + 1, 1, 1) if isinstance(annee, int) else None
    nom = f"Prix moyen {prix} €/m³ ({etat.name})"
    return tarif_prix_fixe(prix, nom=nom, source=source, date_source=date_source)


def tarif_taux_facture(montant_ttc: float | Decimal, volume: float | Decimal) -> Tarif:
    """Taux effectif de la dernière facture : montant TTC ÷ volume, abonnement compris."""
    prix = (Decimal(str(montant_ttc)) / Decimal(str(volume))).quantize(Decimal("0.0001"))
    return tarif_prix_fixe(prix, nom=f"Taux de la dernière facture {prix} €/m³")


def charger_tarif_config(config: dict[str, Any]) -> Tarif | None:
    """Tarif de l'entrée (lecture de fichier : à appeler hors de la boucle d'événements).

    ``None`` pour la source « entité de prix » : le tarif est lu sur l'entité à chaque calcul.
    """
    if config.get(CONF_SOURCE) == SOURCE_ENTITE_PRIX:
        return None
    if config.get(CONF_SOURCE) == SOURCE_TAUX_FACTURE:
        return tarif_taux_facture(config[CONF_MONTANT_FACTURE], config[CONF_VOLUME_FACTURE])
    if config.get(CONF_SOURCE) == SOURCE_PREREGLAGE:
        tarif = charger_tarif(config[CONF_PREREGLAGE])
        if CONF_DIAMETRE in config:
            tarif = avec_diametre(tarif, config[CONF_DIAMETRE])
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
    cout_jour: Decimal | None = None  # € TTC depuis minuit (None : pas encore de repère)
    cout_mois: Decimal | None = None  # € TTC depuis le 1er du mois (ou la relève si elle est plus récente)


@dataclass
class SuiviFacture:
    """Calcule la facture en cours d'une entrée et prévient les capteurs."""

    hass: HomeAssistant
    config: dict[str, Any]
    tarif: Tarif | None  # None : source « entité de prix » dont le prix n'est pas encore connu
    etat: Etat | None = None
    _ecouteurs: list[Callable[[], None]] = field(default_factory=list)
    _desabonnements: list[Callable[[], None]] = field(default_factory=list)
    _averti: bool = False
    reperes: dict[str, str] = field(default_factory=dict)  # index au début du jour et du mois
    store: Store | None = None
    factures: list[dict[str, Any]] = field(default_factory=list)  # saisies, de la plus ancienne à la récente
    store_factures: Store | None = None

    @property
    def prix_moyen_seul(self) -> bool:
        """Source « entité de prix » : prix moyen abonnement compris, sans tranches."""
        return self.config.get(CONF_SOURCE) == SOURCE_ENTITE_PRIX

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

    def lire_tarif(self) -> None:
        """Source « entité de prix » : reconstruit le tarif si le prix a changé ; sinon garde le dernier."""
        if not self.prix_moyen_seul:
            return
        etat = self.hass.states.get(self.config[CONF_ENTITE_PRIX])
        prix = prix_entite(etat)
        if etat is None or prix is None:
            return
        self.tarif = tarif_entite(etat, prix)

    def calculer(self, index: Decimal, jour: date, reperes: dict[str, str] | None = None) -> Etat:
        """Facture depuis la relève jusqu'à ``jour`` inclus, et projection à la fin de la période."""
        assert self.tarif is not None
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

        def cout_depuis(debut: date, index_debut: str | None) -> Decimal | None:
            """Coût TTC entre ``debut`` (index ``index_debut``) et maintenant."""
            if index_debut is None:
                return None
            if debut <= releve:
                return facture.total_ttc
            avant = facture_periode(
                tarif,
                releve,
                debut,
                consommation(Decimal(str(self.config[CONF_INDEX_RELEVE])), Decimal(index_debut)),
                cumul,
            )
            return arrondi_euros(_ttc(facture) - _ttc(avant))

        reperes = reperes or {}
        cout_jour = (
            cout_depuis(jour, reperes.get("index_jour")) if reperes.get("jour") == jour.isoformat() else None
        )
        mois = jour.replace(day=1)
        cout_mois = (
            cout_depuis(mois, reperes.get("index_mois")) if reperes.get("mois") == mois.isoformat() else None
        )
        return Etat(
            index,
            volume,
            facture,
            estimation,
            fin,
            marginal,
            self.tarif,
            jour,
            prolonge,
            cout_jour,
            cout_mois,
        )

    @callback
    def rafraichir(self, *_: Any) -> None:
        """Recalcule si l'index est lisible ; sinon garde le dernier état."""
        self.lire_tarif()
        index = self.lire_index()
        if index is not None and self.tarif is not None:
            jour = dt_util.now().date()
            self._avancer_reperes(index, jour)
            self.etat = self.calculer(index, jour, self.reperes)
        self.prevenir()

    @callback
    def _avancer_reperes(self, index: Decimal, jour: date) -> None:
        """Nouveau jour ou nouveau mois : l'index de départ est le dernier connu (sinon l'actuel)."""
        precedent = self.etat.index if self.etat is not None else index
        if index < precedent:  # compteur remplacé : on repart de l'index actuel
            precedent = index
        change = False
        for cle, debut in (("jour", jour), ("mois", jour.replace(day=1))):
            if self.reperes.get(cle) != debut.isoformat():
                connu = cle in self.reperes
                self.reperes[cle] = debut.isoformat()
                # Premier démarrage : sans repère connu, on part de l'index actuel.
                self.reperes[f"index_{cle}"] = str(precedent if connu else index)
                change = True
        if change and self.store is not None:
            self.store.async_delay_save(lambda: dict(self.reperes), 1)

    @callback
    def prevenir(self) -> None:
        """Prévient les capteurs (nouvelle facture saisie, par exemple)."""
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

        suivies = [self.config[CONF_INDEX]]
        if self.prix_moyen_seul:
            suivies.append(self.config[CONF_ENTITE_PRIX])
        self._desabonnements += [
            async_track_state_change_event(self.hass, suivies, _sur_index),
            async_track_time_change(self.hass, self.rafraichir, hour=0, minute=0, second=5),
        ]
        self.rafraichir()

    @callback
    def arreter(self) -> None:
        """Arrête le suivi (déchargement de l'entrée)."""
        while self._desabonnements:
            self._desabonnements.pop()()
