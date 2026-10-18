"""Période entre deux dates : fin de période saisie, pour une facture irrégulière (issue #35)."""

from datetime import date, timedelta

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifeau.const import (
    CONF_ASSAINISSEMENT,
    CONF_DATE_RELEVE,
    CONF_FACTURATION,
    CONF_FIN_PERIODE,
    CONF_INDEX,
    CONF_INDEX_RELEVE,
    CONF_NOM,
    CONF_PREREGLAGE,
    CONF_SOURCE,
    DOMAIN,
)

INDEX = "sensor.compteur_eau_volume_total"
ATTRS = {"unit_of_measurement": "m³", "state_class": "total_increasing"}


def _entree(hass: HomeAssistant, **data) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Maison",
        unique_id=INDEX,
        data={
            CONF_NOM: "Maison",
            CONF_INDEX: INDEX,
            CONF_SOURCE: "prereglage",
            CONF_PREREGLAGE: "grand_besancon_regie",
            CONF_ASSAINISSEMENT: True,
            CONF_FACTURATION: "annuelle",
            CONF_DATE_RELEVE: "2025-09-05",
            CONF_INDEX_RELEVE: 100,
            **data,
        },
    )
    entry.add_to_hass(hass)
    return entry


async def _estimation(hass: HomeAssistant, entry: MockConfigEntry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registre = er.async_get(hass)
    ident = registre.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_estimation")
    return hass.states.get(ident)


@pytest.mark.parametrize(
    ("fin", "attendu"),
    [
        ("2026-08-18", "2026-08-18"),  # facture réelle : du 05/09/2025 au 18/08/2026
        (None, "2026-09-05"),  # sans fin : relève + 12 mois
        ("2025-09-05", "2026-09-05"),  # fin incohérente (pas après le début) : ignorée
    ],
)
async def test_fin_de_periode(hass: HomeAssistant, freezer, fin, attendu) -> None:
    freezer.move_to("2026-03-01 12:00:00+01:00")
    hass.states.async_set(INDEX, "150", ATTRS)
    entry = _entree(hass, **({CONF_FIN_PERIODE: fin} if fin else {}))
    estimation = await _estimation(hass, entry)
    assert estimation.attributes["fin_periode"] == attendu


async def test_estimation_suit_la_fin_saisie(hass: HomeAssistant, freezer) -> None:
    """La période plus courte (348 jours au lieu de 365) donne une estimation plus basse."""
    freezer.move_to("2026-03-01 12:00:00+01:00")
    hass.states.async_set(INDEX, "150", ATTRS)
    courte = await _estimation(hass, _entree(hass, **{CONF_FIN_PERIODE: "2026-08-18"}))
    entree2 = MockConfigEntry(
        domain=DOMAIN,
        title="Voisin",
        unique_id="sensor.autre",
        data={
            CONF_NOM: "Voisin",
            CONF_INDEX: INDEX,
            CONF_SOURCE: "prereglage",
            CONF_PREREGLAGE: "grand_besancon_regie",
            CONF_ASSAINISSEMENT: True,
            CONF_FACTURATION: "annuelle",
            CONF_DATE_RELEVE: "2025-09-05",
            CONF_INDEX_RELEVE: 100,
        },
    )
    entree2.add_to_hass(hass)
    longue = await _estimation(hass, entree2)
    assert float(courte.state) < float(longue.state)


async def _jusqua_releve(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NOM: "Maison", CONF_INDEX: INDEX}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SOURCE: "prix_fixe"})
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"prix_fixe": 4.0})


async def test_formulaire_fin_facultative_et_verifiee(hass: HomeAssistant) -> None:
    hass.states.async_set(INDEX, "150", ATTRS)
    result = await _jusqua_releve(hass)
    assert result["step_id"] == "releve"
    debut = (date.today() - timedelta(days=200)).isoformat()
    saisie = {CONF_FACTURATION: "annuelle", CONF_DATE_RELEVE: debut, CONF_INDEX_RELEVE: 100}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**saisie, CONF_FIN_PERIODE: debut}
    )
    assert result["errors"] == {CONF_FIN_PERIODE: "fin_avant_debut"}
    fin = (date.today() + timedelta(days=148)).isoformat()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**saisie, CONF_FIN_PERIODE: fin}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_FIN_PERIODE] == fin


async def test_options_vider_la_fin_revient_a_la_duree(hass: HomeAssistant) -> None:
    hass.states.async_set(INDEX, "150", ATTRS)
    entry = _entree(hass, **{CONF_FIN_PERIODE: "2026-08-18"})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "releve"})
    champ = next(k for k in result["data_schema"].schema if k == CONF_FIN_PERIODE)
    assert champ.description == {"suggested_value": "2026-08-18"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_FACTURATION: "annuelle", CONF_DATE_RELEVE: "2025-09-05", CONF_INDEX_RELEVE: 100},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_FIN_PERIODE not in entry.options


async def test_recalage_sur_facture_oublie_la_fin(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-08-20 12:00:00+02:00")
    await hass.config.async_update(currency="EUR", time_zone="Europe/Paris")
    hass.states.async_set(INDEX, "170", ATTRS)
    entry = _entree(hass, **{CONF_FIN_PERIODE: "2026-08-18"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        DOMAIN,
        "saisir_facture",
        {
            "config_entry_id": entry.entry_id,
            "debut": "2025-09-05",
            "fin": "2026-08-18",
            "volume": 65,
            "montant_ttc": 300.0,
            "index_releve": 165,
        },
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done()
    assert entry.options[CONF_DATE_RELEVE] == "2026-08-18"
    assert CONF_FIN_PERIODE not in entry.options  # la nouvelle période reprend la durée
