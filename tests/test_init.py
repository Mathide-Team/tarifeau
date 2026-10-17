"""Chargement et déchargement d'une entrée (issue #1)."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifeau.const import CONF_NOM, DOMAIN


async def test_chargement_et_dechargement(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Maison", data={CONF_NOM: "Maison"})
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
