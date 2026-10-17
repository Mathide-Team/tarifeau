"""Assistant « Ajouter une intégration » (issue #1)."""

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.tarifeau.const import CONF_NOM, DOMAIN, NOM_PAR_DEFAUT


async def _demarrer(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


async def test_formulaire_puis_creation(hass: HomeAssistant) -> None:
    result = await _demarrer(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_NOM: "  Maison  "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Maison"
    assert result["data"] == {CONF_NOM: "Maison"}


async def test_nom_vide_prend_le_nom_par_defaut(hass: HomeAssistant) -> None:
    result = await _demarrer(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_NOM: "   "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NOM_PAR_DEFAUT


async def test_meme_nom_refuse(hass: HomeAssistant) -> None:
    for attendu in (FlowResultType.CREATE_ENTRY, FlowResultType.ABORT):
        result = await _demarrer(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_NOM: "Maison"})
        assert result["type"] is attendu
    assert result["reason"] == "already_configured"
