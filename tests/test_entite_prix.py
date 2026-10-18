"""Source « entité de prix » : prix moyen lu sur un capteur, par exemple HydroTarif (issue #8)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifeau.const import (
    CONF_ASSAINISSEMENT,
    CONF_DATE_RELEVE,
    CONF_ENTITE_PRIX,
    CONF_FACTURATION,
    CONF_INDEX,
    CONF_INDEX_RELEVE,
    CONF_NOM,
    CONF_PREREGLAGE,
    CONF_PRIX_FIXE,
    CONF_SOURCE,
    DOMAIN,
)
from custom_components.tarifeau.suivi import prix_entite, unite_prix_valide

INDEX = "sensor.compteur_eau_volume_total"
PRIX = "sensor.hydrotarif_besancon_prix_total"
ATTRS_INDEX = {"unit_of_measurement": "m³", "state_class": "total_increasing"}
# Attributs exposés par HydroTarif 0.1.7 sur son capteur total_price.
ATTRS_PRIX = {
    "unit_of_measurement": "€/m³",
    "state_class": "measurement",
    "friendly_name": "HydroTarif - Besançon Prix total",
    "commune": "Besançon",
    "code_insee": "25056",
    "reference_consumption_m3_per_year": 120,
    "water_data_year": 2024,
    "water_source_url": "https://www.services.eaufrance.fr/donnees/commune/25056/2024",
}
HIER = (date.today() - timedelta(days=1)).isoformat()


@pytest.fixture(autouse=True)
def capteurs(hass: HomeAssistant) -> None:
    hass.states.async_set(INDEX, "130", ATTRS_INDEX)
    hass.states.async_set(PRIX, "4.12", ATTRS_PRIX)


def test_unite_et_prix() -> None:
    assert unite_prix_valide("€/m³")
    assert unite_prix_valide("EUR / m³")
    assert not unite_prix_valide("€")
    assert not unite_prix_valide(None)
    assert prix_entite(None) is None


# --- Configuration -------------------------------------------------------------------------------


async def _jusqua_entite(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NOM: "Maison", CONF_INDEX: INDEX}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SOURCE: "entite_prix"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "entite_prix"
    return result


async def test_configuration_avec_entite_de_prix(hass: HomeAssistant) -> None:
    result = await _jusqua_entite(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_ENTITE_PRIX: PRIX})
    assert result["step_id"] == "releve"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FACTURATION: "semestrielle", CONF_DATE_RELEVE: HIER, CONF_INDEX_RELEVE: 120}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SOURCE] == "entite_prix"
    assert result["data"][CONF_ENTITE_PRIX] == PRIX
    assert CONF_PRIX_FIXE not in result["data"]


@pytest.mark.parametrize(
    ("entity_id", "etat", "attributs", "erreur"),
    [
        ("sensor.absent", None, None, "capteur_absent"),
        ("sensor.facture", "12", {"unit_of_measurement": "€"}, "unite_prix"),
        ("sensor.prix_hs", "unavailable", {"unit_of_measurement": "€/m³"}, "prix_indisponible"),
        ("sensor.prix_negatif", "-1", {"unit_of_measurement": "€/m³"}, "prix_indisponible"),
    ],
)
async def test_entite_refusee(hass: HomeAssistant, entity_id, etat, attributs, erreur) -> None:
    if etat is not None:
        hass.states.async_set(entity_id, etat, attributs)
    result = await _jusqua_entite(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_ENTITE_PRIX: entity_id})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_ENTITE_PRIX: erreur}


def _entree(hass: HomeAssistant, **data) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Maison",
        unique_id=INDEX,
        data={
            CONF_NOM: "Maison",
            CONF_INDEX: INDEX,
            CONF_SOURCE: "entite_prix",
            CONF_ENTITE_PRIX: PRIX,
            CONF_FACTURATION: "semestrielle",
            CONF_DATE_RELEVE: "2026-01-01",
            CONF_INDEX_RELEVE: 100,
            **data,
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_options_vers_entite_puis_prereglage(hass: HomeAssistant) -> None:
    entry = _entree(hass, **{CONF_SOURCE: "prix_fixe", CONF_PRIX_FIXE: 3.5, CONF_ENTITE_PRIX: None})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "tarif"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SOURCE: "entite_prix"}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_ENTITE_PRIX: PRIX})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ENTITE_PRIX] == PRIX
    assert CONF_PRIX_FIXE not in entry.options
    await hass.async_block_till_done()
    # Retour à un préréglage : l'entité de prix est oubliée.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "tarif"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SOURCE: "prereglage"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PREREGLAGE: "grand_besancon_regie", CONF_ASSAINISSEMENT: True}
    )
    assert CONF_ENTITE_PRIX not in entry.options
    await hass.async_block_till_done()


# --- Capteurs ------------------------------------------------------------------------------------


async def _demarrer(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, str]:
    await hass.config.async_update(currency="EUR", time_zone="Europe/Paris")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return {
        e.unique_id.removeprefix(f"{entry.entry_id}_"): e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


@pytest.fixture
def le_1er_avril(freezer) -> None:
    freezer.move_to("2026-04-01 12:00:00+02:00")


@pytest.mark.usefixtures("le_1er_avril")
async def test_capteurs_au_prix_moyen(hass: HomeAssistant) -> None:
    ids = await _demarrer(hass, _entree(hass))
    cout = hass.states.get(ids["cout_releve"])
    assert Decimal(cout.state) == Decimal("123.60")  # 30 m³ à 4,12 €
    assert cout.attributes["prix_moyen_seul"] is True
    assert cout.attributes["source"] == ATTRS_PRIX["water_source_url"]
    assert cout.attributes["date_source"] == "2025-01-01"  # SISPEA 2024 → tarif au 1er janvier 2025
    assert "HydroTarif - Besançon Prix total" in cout.attributes["tarif"]
    assert Decimal(hass.states.get(ids["prix_marginal"]).state) == Decimal("4.12")

    # HydroTarif publie un nouveau prix : recalcul immédiat.
    hass.states.async_set(PRIX, "4.50", ATTRS_PRIX)
    await hass.async_block_till_done()
    assert Decimal(hass.states.get(ids["cout_releve"]).state) == Decimal("135.00")

    # Prix indisponible (coupure réseau…) : on garde le dernier prix connu.
    hass.states.async_set(PRIX, "unavailable", ATTRS_PRIX)
    hass.states.async_set(INDEX, "131", ATTRS_INDEX)
    await hass.async_block_till_done()
    assert Decimal(hass.states.get(ids["cout_releve"]).state) == Decimal("139.50")


@pytest.mark.usefixtures("le_1er_avril")
async def test_prix_jamais_connu(hass: HomeAssistant) -> None:
    hass.states.async_remove(PRIX)
    entry = _entree(hass)
    ids = await _demarrer(hass, entry)
    assert hass.states.get(ids["cout_releve"]).state == "unknown"
    assert entry.runtime_data.etat is None
    # Le prix arrive après le démarrage (HydroTarif chargé plus tard), sans source ni année.
    hass.states.async_set(PRIX, "4", {"unit_of_measurement": "€/m³"})
    await hass.async_block_till_done()
    cout = hass.states.get(ids["cout_releve"])
    assert Decimal(cout.state) == Decimal("120.00")
    assert cout.attributes["source"] == f"entité {PRIX}"
