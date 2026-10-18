"""Événement tarifeau_ecart_facture et blueprint de notification ntfy (#26)."""

import shutil
from pathlib import Path

import pytest
from homeassistant.components.blueprint import models
from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml_dict
from pytest_homeassistant_custom_component.common import async_capture_events, async_mock_service

from custom_components.tarifeau.const import EVENEMENT_ECART

from .test_factures import CALCUL, _demarrer, _saisir

BLUEPRINT = Path(__file__).parents[1] / "blueprints/automation/tarifeau/ecart_facture_ntfy.yaml"
SUJET = "notify.eau_alertes"


@pytest.fixture(autouse=True)
def le_2_juillet(freezer) -> None:
    freezer.move_to("2026-07-02 12:00:00+02:00")


def test_blueprint_valide() -> None:
    blueprint = models.Blueprint(
        load_yaml_dict(str(BLUEPRINT)), expected_domain="automation", schema=BLUEPRINT_SCHEMA
    )
    assert set(blueprint.inputs) == {"sujet_ntfy", "facture", "priorite"}


async def _automatisation(hass: HomeAssistant, tmp_path: Path, **entrees) -> None:
    hass.config.config_dir = str(tmp_path)
    cible = tmp_path / "blueprints/automation/tarifeau"
    cible.mkdir(parents=True)
    shutil.copy(BLUEPRINT, cible)
    automatisation = {
        "use_blueprint": {
            "path": "tarifeau/ecart_facture_ntfy.yaml",
            "input": {"sujet_ntfy": SUJET, **entrees},
        }
    }
    assert await async_setup_component(hass, "automation", {"automation": [automatisation]})
    await hass.async_block_till_done()


async def test_evenement_et_notification_ntfy(hass: HomeAssistant, tmp_path: Path) -> None:
    publies = async_mock_service(hass, "ntfy", "publish")
    evenements = async_capture_events(hass, EVENEMENT_ECART)
    entry = await _demarrer(hass)
    await _automatisation(hass, tmp_path, facture=entry.entry_id)

    # Facture conforme : ni événement ni notification.
    await _saisir(hass, entry, index_releve=160)
    assert evenements == []
    assert publies == []

    # Un jour d'abonnement facturé 1 € au lieu de 0,07 € : bien au-delà du seuil.
    await _saisir(hass, entry, debut="2026-07-01", fin="2026-07-02", volume=0, montant_ttc=1.0)
    assert len(evenements) == 1
    donnees = evenements[0].data
    assert donnees["config_entry_id"] == entry.entry_id
    assert donnees["nom"] == "Maison"
    assert donnees["montant_ttc"] == 1.0
    assert donnees["calcul_ttc"] == 0.07
    assert donnees["seuil_pct"] == 10
    assert donnees["ecart_pct"] > 1000

    assert len(publies) == 1
    appel = publies[0]
    assert appel.data["entity_id"] == [SUJET]
    assert appel.data["title"].startswith("Maison : écart de +")
    assert "1.00 €, calcul : 0.07 €" in appel.data["message"]
    assert "du 2026-07-01 au 2026-07-02" in appel.data["message"]
    assert appel.data["priority"] == "4"
    assert appel.data["tags"] == ["warning", "droplet"]


async def test_filtre_sur_une_autre_facture(hass: HomeAssistant, tmp_path: Path) -> None:
    publies = async_mock_service(hass, "ntfy", "publish")
    entry = await _demarrer(hass)
    await _automatisation(hass, tmp_path, facture="autre_entree", priorite="5")
    await _saisir(hass, entry, montant_ttc=round(float(CALCUL) * 1.5, 2), index_releve=160)
    await hass.async_block_till_done()
    assert publies == []
