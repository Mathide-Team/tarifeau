"""Recalage sur une facture réelle (issue #9) : action ``tarifeau.saisir_facture``.

La facture saisie est comparée au calcul sur la même période, puis gardée dans
l'historique de l'entrée (``.storage/tarifeau.<entry_id>.factures``). Si elle porte
l'index relevé, la relève de l'entrée est recalée : le suivi repart de cette facture.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .calcul import arrondi_euros, facture_periode
from .const import (
    CONF_DATE_RELEVE,
    CONF_INDEX,
    CONF_INDEX_RELEVE,
    CONF_MONTANT_FACTURE,
    CONF_NOM,
    CONF_SOURCE,
    CONF_VOLUME_FACTURE,
    DOMAIN,
    EVENEMENT_ECART,
    HISTORIQUE_MAX,
    SERVICE_SAISIR_FACTURE,
    SEUIL_ECART,
    SOURCE_TAUX_FACTURE,
)
from .modele import prolonger

if TYPE_CHECKING:
    from . import TarifeauConfigEntry
    from .suivi import SuiviFacture

ATTR_ENTREE = "config_entry_id"
ATTR_DEBUT = "debut"
ATTR_FIN = "fin"
ATTR_VOLUME = "volume"
ATTR_MONTANT = "montant_ttc"
ATTR_INDEX = "index_releve"

_POSITIF = vol.All(vol.Coerce(float), vol.Range(min=0))
SCHEMA_SAISIR_FACTURE = vol.Schema(
    {
        vol.Required(ATTR_ENTREE): cv.string,
        vol.Required(ATTR_DEBUT): cv.date,
        vol.Required(ATTR_FIN): cv.date,
        vol.Required(ATTR_VOLUME): _POSITIF,
        vol.Required(ATTR_MONTANT): _POSITIF,
        vol.Optional(ATTR_INDEX): _POSITIF,
    }
)


def store_factures(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    return Store(hass, 1, f"{DOMAIN}.{entry_id}.factures")


def id_alerte(entry_id: str) -> str:
    return f"ecart_facture_{entry_id}"


def _erreur(cle: str, **valeurs: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key=cle, translation_placeholders=valeurs or None
    )


def montant_calcule(suivi: SuiviFacture, debut: date, fin: date, volume: Decimal) -> Decimal | None:
    """Montant TTC calculé par l'intégration pour ``volume`` m³ du ``debut`` au ``fin`` (exclu)."""
    if suivi.tarif is None:  # entité de prix pas encore connue
        return None
    tarif, _ = prolonger(suivi.tarif, debut, fin)
    # Même estimation que le suivi : volume déjà passé dans les tranches avant ``debut``.
    cumul = volume / (fin - debut).days * (debut - date(debut.year, 1, 1)).days
    return facture_periode(tarif, debut, fin, volume, cumul).total_ttc


def comparer(suivi: SuiviFacture, saisie: dict[str, Any]) -> dict[str, Any]:
    """Enregistrement d'historique : la facture saisie, le calcul et l'écart."""
    debut, fin = saisie[ATTR_DEBUT], saisie[ATTR_FIN]
    volume = Decimal(str(saisie[ATTR_VOLUME]))
    montant = arrondi_euros(Decimal(str(saisie[ATTR_MONTANT])))
    calcul = montant_calcule(suivi, debut, fin, volume)
    ecart = None if calcul is None else montant - calcul
    ecart_pct = None if ecart is None or calcul == 0 else (ecart / calcul * 100).quantize(Decimal("0.1"))
    return {
        "debut": debut.isoformat(),
        "fin": fin.isoformat(),
        "volume": float(volume),
        "montant_ttc": float(montant),
        "index_releve": saisie.get(ATTR_INDEX),
        "calcul_ttc": None if calcul is None else float(calcul),
        "ecart": None if ecart is None else float(ecart),
        "ecart_pct": None if ecart_pct is None else float(ecart_pct),
        "taux_effectif": None if volume == 0 else float((montant / volume).quantize(Decimal("0.0001"))),
        "tarif": None if suivi.tarif is None else suivi.tarif.nom,
        "saisie_le": dt_util.now().isoformat(timespec="seconds"),
    }


def _verifier(hass: HomeAssistant, entry: TarifeauConfigEntry, saisie: dict[str, Any]) -> None:
    debut, fin = saisie[ATTR_DEBUT], saisie[ATTR_FIN]
    if fin <= debut:
        raise _erreur("periode_invalide")
    if fin > dt_util.now().date():
        raise _erreur("date_future")
    if (index := saisie.get(ATTR_INDEX)) is not None:
        actuel = entry.runtime_data.lire_index()
        if actuel is not None and Decimal(str(index)) > actuel + Decimal("0.000001"):
            raise _erreur("index_incoherent", actuel=str(actuel))


def _nouvelle_releve(entry: TarifeauConfigEntry, saisie: dict[str, Any]) -> dict[str, Any] | None:
    """Options recalées sur la facture, ou ``None`` si la facture ne permet pas de recaler."""
    config = {**entry.data, **entry.options}
    index = saisie.get(ATTR_INDEX)
    if index is None:
        # Sans index relevé : on peut avancer depuis la relève actuelle si la facture en part.
        if saisie[ATTR_DEBUT].isoformat() != config[CONF_DATE_RELEVE]:
            return None
        index = float(Decimal(str(config[CONF_INDEX_RELEVE])) + Decimal(str(saisie[ATTR_VOLUME])))
    if saisie[ATTR_FIN].isoformat() < config[CONF_DATE_RELEVE]:
        return None  # ancienne facture : historique seulement
    options = {k: v for k, v in config.items() if k not in (CONF_NOM, CONF_INDEX)}
    options[CONF_DATE_RELEVE] = saisie[ATTR_FIN].isoformat()
    options[CONF_INDEX_RELEVE] = index
    if config.get(CONF_SOURCE) == SOURCE_TAUX_FACTURE and saisie[ATTR_VOLUME] > 0:
        options[CONF_MONTANT_FACTURE] = saisie[ATTR_MONTANT]
        options[CONF_VOLUME_FACTURE] = saisie[ATTR_VOLUME]
    return options


def mettre_a_jour_alerte(hass: HomeAssistant, entry: TarifeauConfigEntry, facture: dict[str, Any]) -> None:
    """Alerte si l'écart dépasse le seuil ; retirée sinon.

    Deux canaux : Paramètres → Réparations, et l'événement ``tarifeau_ecart_facture`` pour
    les automatisations (notification ntfy : voir blueprints/automation/tarifeau/).
    """
    ecart_pct = facture["ecart_pct"]
    if ecart_pct is None or abs(ecart_pct) <= SEUIL_ECART:
        ir.async_delete_issue(hass, DOMAIN, id_alerte(entry.entry_id))
        return
    hass.bus.async_fire(
        EVENEMENT_ECART,
        {
            "config_entry_id": entry.entry_id,
            "nom": entry.title,
            "seuil_pct": SEUIL_ECART,
            **{
                k: facture[k]
                for k in ("debut", "fin", "volume", "montant_ttc", "calcul_ttc", "ecart", "ecart_pct")
            },
        },
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        id_alerte(entry.entry_id),
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="ecart_facture",
        translation_placeholders={
            "nom": entry.title,
            "debut": facture["debut"],
            "fin": facture["fin"],
            "montant": f"{facture['montant_ttc']:.2f}",
            "calcul": f"{facture['calcul_ttc']:.2f}",
            "ecart_pct": f"{ecart_pct:+.1f}",
            "seuil": str(SEUIL_ECART),
        },
    )


async def async_saisir_facture(hass: HomeAssistant, appel: ServiceCall) -> ServiceResponse:
    """Action ``tarifeau.saisir_facture``."""
    entry: TarifeauConfigEntry | None = hass.config_entries.async_get_entry(appel.data[ATTR_ENTREE])
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        raise _erreur("entree_inconnue")
    saisie = dict(appel.data)
    _verifier(hass, entry, saisie)
    suivi = entry.runtime_data
    facture = comparer(suivi, saisie)
    suivi.factures = [*suivi.factures, facture][-HISTORIQUE_MAX:]
    if suivi.store_factures is not None:
        await suivi.store_factures.async_save({"factures": suivi.factures})
    mettre_a_jour_alerte(hass, entry, facture)
    options = _nouvelle_releve(entry, saisie)
    suivi.prevenir()
    if options is not None:
        hass.config_entries.async_update_entry(entry, options=options)
        hass.config_entries.async_schedule_reload(entry.entry_id)
    return {**facture, "releve_recalee": options is not None}


def async_enregistrer_actions(hass: HomeAssistant) -> None:
    """Déclare les actions de l'intégration (une fois, au chargement du domaine)."""

    async def _saisir(appel: ServiceCall) -> ServiceResponse:
        return await async_saisir_facture(hass, appel)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SAISIR_FACTURE,
        _saisir,
        schema=SCHEMA_SAISIR_FACTURE,
        supports_response=SupportsResponse.OPTIONAL,
    )
