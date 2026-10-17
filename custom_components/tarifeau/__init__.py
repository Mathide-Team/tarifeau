"""tarifeau : facture d'eau française calculée d'après la consommation réelle.

Squelette (issue #1) : l'entrée de configuration est créée et chargée, sans
capteur pour l'instant. Les capteurs arrivent avec l'issue #5, la
configuration complète (capteur d'index, tarif, période) avec l'issue #4.
Le calcul vit dans ``calcul.py``, en Python pur (sans Home Assistant).
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

PLATFORMS: list[str] = []


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Charge une entrée de configuration."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharge une entrée de configuration."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
