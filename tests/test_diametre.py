"""Abonnement selon le diamètre du compteur (issue #4)."""

import shutil
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifeau import modele
from custom_components.tarifeau.const import (
    CONF_ASSAINISSEMENT,
    CONF_DATE_RELEVE,
    CONF_DIAMETRE,
    CONF_FACTURATION,
    CONF_INDEX,
    CONF_INDEX_RELEVE,
    CONF_NOM,
    CONF_PREREGLAGE,
    CONF_PRIX_FIXE,
    CONF_SOURCE,
    DOMAIN,
)
from custom_components.tarifeau.modele import (
    TarifInvalide,
    avec_diametre,
    charger_tarif,
    diametres,
    tarif_depuis_dict,
)
from custom_components.tarifeau.suivi import charger_tarif_config

INDEX = "sensor.compteur_eau_volume_total"
ABONNEMENT_DN = {15: 40.0, 20: 64.0, 30: 150.0}


def _belfort_par_diametre() -> dict:
    """Préréglage Grand Belfort, avec une table d'abonnements par diamètre (montants d'essai)."""
    donnees = yaml.safe_load((modele.DOSSIER_TARIFS / "grand_belfort.yaml").read_text(encoding="utf-8"))
    donnees["id"] = "essai_diametre"
    donnees["periodes"][0]["services"]["eau_potable"]["abonnements"][0]["par_diametre"] = ABONNEMENT_DN
    return donnees


def test_lecture_et_application() -> None:
    tarif = tarif_depuis_dict(_belfort_par_diametre())
    assert diametres(tarif) == [15, 20, 30]
    assert diametres(charger_tarif("grand_besancon_regie")) == []

    def abonnement_eau(t) -> Decimal:
        return t.periodes[0].services[0].abonnements[0].montant_ht_an

    assert abonnement_eau(avec_diametre(tarif, 20)) == Decimal(64)
    # Diamètre absent de la table : montant par défaut ; services sans table inchangés.
    assert abonnement_eau(avec_diametre(tarif, 40)) == Decimal(40)
    assert avec_diametre(tarif, 30).periodes[0].services[1] == tarif.periodes[0].services[1]


def test_factures_types_retirees_si_l_abonnement_change() -> None:
    besancon = charger_tarif("grand_besancon_regie")
    assert avec_diametre(besancon, 15) == besancon  # rien ne change : factures types gardées
    donnees = yaml.safe_load(
        (modele.DOSSIER_TARIFS / "grand_besancon_regie.yaml").read_text(encoding="utf-8")
    )
    donnees["periodes"][0]["services"]["eau_potable"]["abonnements"][0]["par_diametre"] = {15: 15, 20: 30}
    tarif = tarif_depuis_dict(donnees)
    assert tarif.periodes[0].factures_types
    assert avec_diametre(tarif, 20).periodes[0].factures_types == ()


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ([40], "dictionnaire attendu"),
        ({"DN15": 40}, "diamètre invalide"),
        ({0: 40}, "diamètre invalide"),
        ({True: 40}, "diamètre invalide"),
    ],
)
def test_table_refusee(table, message) -> None:
    donnees = _belfort_par_diametre()
    donnees["periodes"][0]["services"]["eau_potable"]["abonnements"][0]["par_diametre"] = table
    with pytest.raises(TarifInvalide, match=message):
        tarif_depuis_dict(donnees)


@pytest.fixture
def dossier_essai(tmp_path: Path):
    """Dossier de préréglages : les vrais, plus un tarif avec table par diamètre."""
    for fichier in modele.DOSSIER_TARIFS.glob("*.yaml"):
        shutil.copy(fichier, tmp_path)
    (tmp_path / "essai_diametre.yaml").write_text(yaml.safe_dump(_belfort_par_diametre()), encoding="utf-8")
    with patch.object(modele, "DOSSIER_TARIFS", tmp_path):
        yield


@pytest.mark.usefixtures("dossier_essai")
async def test_configuration_avec_diametre(hass: HomeAssistant) -> None:
    hass.states.async_set(INDEX, "123", {"unit_of_measurement": "m³", "state_class": "total_increasing"})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NOM: "Maison", CONF_INDEX: INDEX}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SOURCE: "prereglage"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PREREGLAGE: "essai_diametre", CONF_ASSAINISSEMENT: True}
    )
    assert result["step_id"] == "diametre"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_DIAMETRE: "20"})
    assert result["step_id"] == "releve"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_FACTURATION: "semestrielle", CONF_DATE_RELEVE: "2026-05-01", CONF_INDEX_RELEVE: 100},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DIAMETRE] == 20
    tarif = charger_tarif_config(result["data"])
    eau = next(s for s in tarif.periodes[0].services if s.code == "eau_potable")
    assert eau.abonnements[0].montant_ht_an == Decimal(64)


@pytest.mark.usefixtures("dossier_essai")
async def test_options_diametre_puis_autre_source(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=INDEX,
        data={
            CONF_NOM: "Maison",
            CONF_INDEX: INDEX,
            CONF_SOURCE: "prereglage",
            CONF_PREREGLAGE: "essai_diametre",
            CONF_ASSAINISSEMENT: True,
            CONF_DIAMETRE: 30,
            CONF_FACTURATION: "semestrielle",
            CONF_DATE_RELEVE: "2026-05-01",
            CONF_INDEX_RELEVE: 100,
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "tarif"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SOURCE: "prereglage"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PREREGLAGE: "essai_diametre", CONF_ASSAINISSEMENT: True}
    )
    assert result["step_id"] == "diametre"
    schema = result["data_schema"].schema
    assert next(iter(schema)).default() == "30"  # diamètre actuel proposé
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_DIAMETRE: "15"})
    assert entry.options[CONF_DIAMETRE] == 15
    await hass.async_block_till_done()
    # Préréglage sans table : le diamètre est oublié.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "tarif"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SOURCE: "prereglage"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PREREGLAGE: "grand_besancon_regie", CONF_ASSAINISSEMENT: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_DIAMETRE not in entry.options
    await hass.async_block_till_done()
    # Et vers le prix fixe : plus aucun champ du préréglage.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "tarif"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_SOURCE: "prix_fixe"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_PRIX_FIXE: 4})
    assert CONF_PREREGLAGE not in entry.options
    await hass.async_block_till_done()
