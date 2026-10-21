"""Configuration et options depuis l'interface (issues #1 et #4)."""

from datetime import date, timedelta

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifeau.config_flow import _capteur_index_par_defaut
from custom_components.tarifeau.const import (
    CONF_ASSAINISSEMENT,
    CONF_DATE_RELEVE,
    CONF_FACTURATION,
    CONF_INDEX,
    CONF_INDEX_RELEVE,
    CONF_NOM,
    CONF_PREREGLAGE,
    CONF_PRIX_FIXE,
    CONF_SOURCE,
    DOMAIN,
    NOM_PAR_DEFAUT,
)

INDEX = "sensor.compteur_eau_volume_total"
HIER = (date.today() - timedelta(days=1)).isoformat()


@pytest.fixture(autouse=True)
def capteur_index(hass: HomeAssistant) -> None:
    hass.states.async_set(INDEX, "123.456", {"unit_of_measurement": "m³", "state_class": "total_increasing"})


async def _jusqua_tarif(hass: HomeAssistant, nom: str = "Maison", index: str = INDEX):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NOM: nom, CONF_INDEX: index}
    )


async def test_capteur_wmbus_propose_par_defaut(hass: HomeAssistant) -> None:
    """L'index d'Esphome-Compteur-wmbus est pré-choisi s'il est seul candidat (issue #43)."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    cle = next(k for k in result["data_schema"].schema if k.schema == CONF_INDEX)
    assert callable(cle.default) and cle.default() == INDEX


async def test_capteur_wmbus_ambigu_pas_de_defaut(hass: HomeAssistant) -> None:
    """Deux capteurs « volume total » : aucun n'est imposé par défaut."""
    hass.states.async_set(
        "sensor.deuxieme_esp_compteur_eau_volume_total",
        "12",
        {"unit_of_measurement": "m³", "state_class": "total_increasing"},
    )
    assert _capteur_index_par_defaut(hass) is None


async def test_capteur_sans_nom_wmbus_pas_de_defaut(hass: HomeAssistant) -> None:
    """Un capteur d'index valide mais sans lien avec le compteur wM-Bus n'est pas pré-choisi."""
    hass.states.async_set(INDEX, "123.456")  # remplace : plus d'attributs → candidat invalide
    hass.states.async_set(
        "sensor.mon_index_eau",
        "99",
        {"unit_of_measurement": "m³", "state_class": "total_increasing"},
    )
    assert _capteur_index_par_defaut(hass) is None


async def test_configuration_avec_prereglage(hass: HomeAssistant) -> None:
    result = await _jusqua_tarif(hass, "  Maison  ")
    assert result["step_id"] == "tarif"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SOURCE: "prereglage"})
    assert result["step_id"] == "prereglage"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PREREGLAGE: "grand_besancon_regie", CONF_ASSAINISSEMENT: True}
    )
    assert result["step_id"] == "releve"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FACTURATION: "semestrielle", CONF_DATE_RELEVE: HIER, CONF_INDEX_RELEVE: 120}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Maison"
    assert result["data"] == {
        CONF_NOM: "Maison",
        CONF_INDEX: INDEX,
        CONF_SOURCE: "prereglage",
        CONF_PREREGLAGE: "grand_besancon_regie",
        CONF_ASSAINISSEMENT: True,
        CONF_FACTURATION: "semestrielle",
        CONF_DATE_RELEVE: HIER,
        CONF_INDEX_RELEVE: 120,
    }
    assert result["result"].unique_id == INDEX


async def test_configuration_avec_prix_fixe_et_nom_vide(hass: HomeAssistant) -> None:
    result = await _jusqua_tarif(hass, "   ")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SOURCE: "prix_fixe"})
    assert result["step_id"] == "prix_fixe"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PRIX_FIXE: 4.2})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FACTURATION: "annuelle", CONF_DATE_RELEVE: HIER, CONF_INDEX_RELEVE: 0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NOM_PAR_DEFAUT
    assert result["data"][CONF_PRIX_FIXE] == 4.2
    assert CONF_PREREGLAGE not in result["data"]


@pytest.mark.parametrize(
    ("entity_id", "etat", "attributs", "erreur"),
    [
        ("sensor.absent", None, None, "capteur_absent"),
        ("sensor.gaz", "10", {"unit_of_measurement": "kWh", "state_class": "total_increasing"}, "unite"),
        ("sensor.debit", "10", {"unit_of_measurement": "L", "state_class": "measurement"}, "state_class"),
    ],
)
async def test_capteur_refuse(hass: HomeAssistant, entity_id, etat, attributs, erreur) -> None:
    if etat is not None:
        hass.states.async_set(entity_id, etat, attributs)
    result = await _jusqua_tarif(hass, index=entity_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {CONF_INDEX: erreur}


async def test_meme_capteur_refuse(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=INDEX, data={CONF_NOM: "A", CONF_INDEX: INDEX}).add_to_hass(hass)
    result = await _jusqua_tarif(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def _jusqua_releve(hass: HomeAssistant, index: str = INDEX):
    result = await _jusqua_tarif(hass, index=index)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SOURCE: "prix_fixe"})
    return await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PRIX_FIXE: 4})


async def test_index_et_date_incoherents(hass: HomeAssistant) -> None:
    result = await _jusqua_releve(hass)
    demain = (date.today() + timedelta(days=1)).isoformat()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FACTURATION: "annuelle", CONF_DATE_RELEVE: demain, CONF_INDEX_RELEVE: 200}
    )
    assert result["step_id"] == "releve"
    assert result["errors"] == {CONF_DATE_RELEVE: "date_future", CONF_INDEX_RELEVE: "index_incoherent"}


async def test_index_en_litres_converti_en_m3(hass: HomeAssistant) -> None:
    capteur = "sensor.impulsions"
    hass.states.async_set(capteur, "12000", {"unit_of_measurement": "L", "state_class": "total"})
    result = await _jusqua_releve(hass, capteur)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FACTURATION: "annuelle", CONF_DATE_RELEVE: HIER, CONF_INDEX_RELEVE: 12.5}
    )
    assert result["errors"] == {CONF_INDEX_RELEVE: "index_incoherent"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FACTURATION: "annuelle", CONF_DATE_RELEVE: HIER, CONF_INDEX_RELEVE: 12}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_index_indisponible_pas_de_controle(hass: HomeAssistant) -> None:
    result = await _jusqua_releve(hass)
    hass.states.async_set(
        INDEX, "unavailable", {"unit_of_measurement": "m³", "state_class": "total_increasing"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FACTURATION: "annuelle", CONF_DATE_RELEVE: HIER, CONF_INDEX_RELEVE: 999}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_index_sans_entite_pas_de_controle(hass: HomeAssistant) -> None:
    result = await _jusqua_releve(hass)
    hass.states.async_remove(INDEX)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FACTURATION: "annuelle", CONF_DATE_RELEVE: HIER, CONF_INDEX_RELEVE: 999}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


# ── Options ──


def _entree(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=INDEX,
        data={
            CONF_NOM: "Maison",
            CONF_INDEX: INDEX,
            CONF_SOURCE: "prereglage",
            CONF_PREREGLAGE: "grand_besancon_regie",
            CONF_ASSAINISSEMENT: True,
            CONF_FACTURATION: "semestrielle",
            CONF_DATE_RELEVE: "2026-01-02",
            CONF_INDEX_RELEVE: 100,
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_options_nouvelle_releve(hass: HomeAssistant) -> None:
    entry = _entree(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "releve"})
    assert result["step_id"] == "releve"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_FACTURATION: "semestrielle", CONF_DATE_RELEVE: HIER, CONF_INDEX_RELEVE: 123}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_INDEX_RELEVE] == 123
    assert entry.options[CONF_PREREGLAGE] == "grand_besancon_regie"
    assert CONF_INDEX not in entry.options


async def test_options_changer_de_tarif(hass: HomeAssistant) -> None:
    entry = _entree(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "tarif"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SOURCE: "prix_fixe"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_PRIX_FIXE: 3.5})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SOURCE] == "prix_fixe"
    assert CONF_PREREGLAGE not in entry.options
    # Et retour à un préréglage, sans assainissement.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "tarif"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SOURCE: "prereglage"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PREREGLAGE: "grand_besancon_regie", CONF_ASSAINISSEMENT: False}
    )
    assert entry.options[CONF_ASSAINISSEMENT] is False
    assert CONF_PRIX_FIXE not in entry.options
