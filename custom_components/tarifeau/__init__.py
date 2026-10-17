"""tarifeau : facture d'eau française calculée d'après la consommation réelle.

Chaque entrée suit un capteur d'index et calcule la facture en cours selon son tarif
(``suivi.py``). Le calcul vit dans ``calcul.py`` et ``modele.py``, en Python pur.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .factures import async_enregistrer_actions, id_alerte, store_factures
from .suivi import SuiviFacture, charger_tarif_config

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type TarifeauConfigEntry = ConfigEntry[SuiviFacture]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Actions de l'intégration (``tarifeau.saisir_facture``)."""
    async_enregistrer_actions(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TarifeauConfigEntry) -> bool:
    """Charge le tarif (hors boucle), démarre le suivi puis les capteurs."""
    config = {**entry.data, **entry.options}
    tarif = await hass.async_add_executor_job(charger_tarif_config, config)
    store: Store[dict[str, str]] = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
    reperes = await store.async_load() or {}
    historique = store_factures(hass, entry.entry_id)
    factures = (await historique.async_load() or {}).get("factures", [])
    entry.runtime_data = SuiviFacture(
        hass, config, tarif, reperes=reperes, store=store, factures=factures, store_factures=historique
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.runtime_data.demarrer()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TarifeauConfigEntry) -> bool:
    """Arrête le suivi et décharge les capteurs."""
    suivi = entry.runtime_data
    suivi.arreter()
    if suivi.store is not None:
        await suivi.store.async_save(dict(suivi.reperes))  # remplace une sauvegarde différée en attente
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: TarifeauConfigEntry) -> None:
    """Supprime les repères, l'historique des factures et l'alerte d'écart de l'entrée."""
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
    await store_factures(hass, entry.entry_id).async_remove()
    ir.async_delete_issue(hass, DOMAIN, id_alerte(entry.entry_id))
