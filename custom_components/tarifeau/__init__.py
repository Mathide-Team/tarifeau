"""tarifeau : facture d'eau française calculée d'après la consommation réelle.

Chaque entrée suit un capteur d'index et calcule la facture en cours selon son tarif
(``suivi.py``). Le calcul vit dans ``calcul.py`` et ``modele.py``, en Python pur.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .factures import async_enregistrer_actions, id_alerte, store_factures
from .journal import resumer
from .modele import TarifInvalide
from .suivi import SuiviFacture, charger_tarif_config, dossier_perso

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type TarifeauConfigEntry = ConfigEntry[SuiviFacture]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Actions de l'intégration (``tarifeau.saisir_facture``)."""
    _LOGGER.debug("async_setup: entrée | hass=%s, config=%s", resumer(hass), resumer(config))
    async_enregistrer_actions(hass)
    _LOGGER.debug("async_setup: sortie | True")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TarifeauConfigEntry) -> bool:
    """Charge le tarif (hors boucle), démarre le suivi puis les capteurs."""
    _LOGGER.debug("async_setup_entry: entrée | hass=%s, entry=%s", resumer(hass), resumer(entry))
    config = {**entry.data, **entry.options}
    try:
        tarif = await hass.async_add_executor_job(charger_tarif_config, config, dossier_perso(hass))
    except TarifInvalide as err:
        # Fichier personnel supprimé ou devenu invalide : l'entrée affiche l'erreur, sans réessayer.
        _LOGGER.debug("async_setup_entry: sortie par ConfigEntryError | cause=%s", err)
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="tarif_invalide",
            translation_placeholders={"erreur": str(err)},
        ) from err
    store: Store[dict[str, str]] = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
    reperes = await store.async_load() or {}
    historique = store_factures(hass, entry.entry_id)
    factures = (await historique.async_load() or {}).get("factures", [])
    entry.runtime_data = SuiviFacture(
        hass, config, tarif, reperes=reperes, store=store, factures=factures, store_factures=historique
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.runtime_data.demarrer()
    _LOGGER.debug("async_setup_entry: sortie | True")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TarifeauConfigEntry) -> bool:
    """Arrête le suivi et décharge les capteurs."""
    _LOGGER.debug("async_unload_entry: entrée | hass=%s, entry=%s", resumer(hass), resumer(entry))
    suivi = entry.runtime_data
    suivi.arreter()
    if suivi.store is not None:
        await suivi.store.async_save(dict(suivi.reperes))  # remplace une sauvegarde différée en attente
    _LOGGER.debug("async_unload_entry: sortie")
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: TarifeauConfigEntry) -> None:
    """Supprime les repères, l'historique des factures et l'alerte d'écart de l'entrée."""
    _LOGGER.debug("async_remove_entry: entrée | hass=%s, entry=%s", resumer(hass), resumer(entry))
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
    await store_factures(hass, entry.entry_id).async_remove()
    ir.async_delete_issue(hass, DOMAIN, id_alerte(entry.entry_id))
    _LOGGER.debug("async_remove_entry: sortie")
