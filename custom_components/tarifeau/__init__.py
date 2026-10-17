"""tarifeau : facture d'eau française calculée d'après la consommation réelle.

Chaque entrée suit un capteur d'index et calcule la facture en cours selon son tarif
(``suivi.py``). Le calcul vit dans ``calcul.py`` et ``modele.py``, en Python pur.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .suivi import SuiviFacture, charger_tarif_config

PLATFORMS: list[Platform] = [Platform.SENSOR]

type TarifeauConfigEntry = ConfigEntry[SuiviFacture]


async def async_setup_entry(hass: HomeAssistant, entry: TarifeauConfigEntry) -> bool:
    """Charge le tarif (hors boucle), démarre le suivi puis les capteurs."""
    config = {**entry.data, **entry.options}
    tarif = await hass.async_add_executor_job(charger_tarif_config, config)
    store: Store[dict[str, str]] = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
    reperes = await store.async_load() or {}
    entry.runtime_data = SuiviFacture(hass, config, tarif, reperes=reperes, store=store)
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
    """Supprime les repères mémorisés de l'entrée."""
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
