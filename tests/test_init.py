"""Chargement et déchargement d'une entrée (issues #1 et #5)."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifeau.const import (
    CONF_DATE_RELEVE,
    CONF_FACTURATION,
    CONF_INDEX,
    CONF_INDEX_RELEVE,
    CONF_NOM,
    CONF_PRIX_FIXE,
    CONF_SOURCE,
    DOMAIN,
)


async def test_chargement_et_dechargement(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "sensor.index", "10", {"unit_of_measurement": "m³", "state_class": "total_increasing"}
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Maison",
        data={
            CONF_NOM: "Maison",
            CONF_INDEX: "sensor.index",
            CONF_SOURCE: "prix_fixe",
            CONF_PRIX_FIXE: 4,
            CONF_FACTURATION: "annuelle",
            CONF_DATE_RELEVE: "2026-01-01",
            CONF_INDEX_RELEVE: 0,
        },
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    suivi = entry.runtime_data
    assert suivi.etat is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert suivi._desabonnements == []
