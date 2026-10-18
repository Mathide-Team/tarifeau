"""Tarifs personnels : fichiers YAML dans <config>/tarifeau/ (issue #17)."""

import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifeau.const import (
    CONF_ASSAINISSEMENT,
    CONF_DATE_RELEVE,
    CONF_FACTURATION,
    CONF_INDEX,
    CONF_INDEX_RELEVE,
    CONF_NOM,
    CONF_PREREGLAGE,
    CONF_SOURCE,
    DOMAIN,
)
from custom_components.tarifeau.modele import (
    TarifInvalide,
    charger_tarif,
    tarifs_perso,
    verifier_tarifs_perso,
)

EXEMPLE = Path(__file__).parents[1] / "docs/exemples/mon_tarif.yaml"
INDEX = "sensor.compteur_eau_volume_total"
HIER = (date.today() - timedelta(days=1)).isoformat()
INVALIDE = """\
id: casse
nom: Tarif cassé
periodes:
  - debut: 2026-01-01
    source: https://www.example.org/
    services:
      eau_potable:
        tva: 5.5
        composantes:
          - nom: Consommation
            prix_ht: -1
"""


@pytest.fixture
def dossier(tmp_path: Path) -> Path:
    d = tmp_path / "tarifeau"
    d.mkdir()
    shutil.copy(EXEMPLE, d / "ma_commune.yaml")
    (d / "casse.yml").write_text(INVALIDE, encoding="utf-8")
    (d / "notes.txt").write_text("ignoré", encoding="utf-8")
    return d


@pytest.fixture
def config_hass(hass: HomeAssistant, dossier: Path) -> Path:
    hass.config.config_dir = str(dossier.parent)
    hass.states.async_set(INDEX, "123.456", {"unit_of_measurement": "m³", "state_class": "total_increasing"})
    return dossier


def test_exemple_de_la_documentation_valide() -> None:
    tarif = charger_tarif(EXEMPLE)
    assert tarif.nom == "Ma commune (exemple)"
    assert {s.code for s in tarif.periodes[0].services} == {"eau_potable", "assainissement"}


def test_liste_et_verification(dossier: Path) -> None:
    assert tarifs_perso(dossier) == ["perso:casse", "perso:ma_commune"]
    assert tarifs_perso(dossier / "absent") == []
    assert tarifs_perso(None) == []
    (casse, tarif_casse, erreur), (commune, tarif, aucune) = verifier_tarifs_perso(dossier)
    assert (casse, tarif_casse) == ("perso:casse", None)
    assert erreur.startswith("casse.yml : ")
    assert "composantes[0].prix_ht" in erreur  # chemin précis de la valeur fautive
    assert (commune, tarif.nom, aucune) == ("perso:ma_commune", "Ma commune (exemple)", None)


@pytest.mark.parametrize(
    ("contenu", "message"),
    [
        (b"periodes: [", "YAML invalide"),
        (b"\xff\xfe\x00", "fichier illisible"),
    ],
)
def test_fichier_illisible(dossier: Path, contenu: bytes, message: str) -> None:
    (dossier / "illisible.yaml").write_bytes(contenu)
    with pytest.raises(TarifInvalide, match=message):
        charger_tarif("perso:illisible", dossier)


def test_fichier_absent_ou_dossier_inconnu(dossier: Path) -> None:
    with pytest.raises(TarifInvalide, match=r"absent\.yaml : fichier absent"):
        charger_tarif("perso:absent", dossier)
    with pytest.raises(TarifInvalide, match="dossier des tarifs personnels inconnu"):
        charger_tarif("perso:ma_commune")


async def test_configuration_avec_mon_tarif(hass: HomeAssistant, config_hass: Path) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NOM: "Maison", CONF_INDEX: INDEX}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SOURCE: "prereglage"})
    assert result["step_id"] == "prereglage"
    assert str(config_hass) == result["description_placeholders"]["dossier"]
    options = result["data_schema"].schema[CONF_PREREGLAGE].config["options"]
    libelles = {o["value"]: o["label"] for o in options}
    assert libelles["perso:ma_commune"] == "Mon tarif : Ma commune (exemple) (ma_commune)"
    assert libelles["perso:casse"] == "Mon tarif : casse (invalide)"
    assert "grand_besancon_regie" in libelles

    # Fichier invalide : erreur avec le message précis, et le formulaire reste sur ce choix.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PREREGLAGE: "perso:casse", CONF_ASSAINISSEMENT: True}
    )
    assert result["errors"] == {"base": "tarif_invalide"}
    assert "prix_ht" in result["description_placeholders"]["erreur"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PREREGLAGE: "perso:ma_commune", CONF_ASSAINISSEMENT: True}
    )
    assert result["step_id"] == "releve"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FACTURATION: "semestrielle", CONF_DATE_RELEVE: HIER, CONF_INDEX_RELEVE: 120}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PREREGLAGE] == "perso:ma_commune"
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.state is ConfigEntryState.LOADED
    cout = next(s for s in hass.states.async_all("sensor") if s.entity_id.endswith("_cout_releve"))
    assert cout.attributes["tarif"] == "Ma commune (exemple)"


def _entree(hass: HomeAssistant, prereglage: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=INDEX,
        data={
            CONF_NOM: "Maison",
            CONF_INDEX: INDEX,
            CONF_SOURCE: "prereglage",
            CONF_PREREGLAGE: prereglage,
            CONF_ASSAINISSEMENT: False,
            CONF_FACTURATION: "semestrielle",
            CONF_DATE_RELEVE: "2026-01-02",
            CONF_INDEX_RELEVE: 100,
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_fichier_supprime_apres_coup(hass: HomeAssistant, config_hass: Path) -> None:
    entry = _entree(hass, "perso:disparu")
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert "disparu.yaml : fichier absent" in entry.reason


async def test_options_verifier_mes_fichiers(hass: HomeAssistant, config_hass: Path) -> None:
    entry = _entree(hass, "grand_besancon_regie")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "verifier" in result["menu_options"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "verifier"}
    )
    assert result["step_id"] == "verifier"
    rapport = result["description_placeholders"]["rapport"]
    assert "- **casse** : invalide. casse.yml : " in rapport
    assert "- **ma_commune** : valide, « Ma commune (exemple) », 1 période(s) depuis le 01/01/2026" in rapport
    # Valider ramène au menu, sans rien modifier.
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.MENU
    assert entry.options == {}


async def test_options_verifier_sans_dossier(hass: HomeAssistant, tmp_path: Path) -> None:
    hass.config.config_dir = str(tmp_path)
    entry = _entree(hass, "grand_besancon_regie")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "verifier"}
    )
    assert (
        result["description_placeholders"]["rapport"]
        == f"Aucun fichier `.yaml` dans `{tmp_path / 'tarifeau'}`."
    )
