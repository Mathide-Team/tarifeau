"""Tableau de bord prêt à coller (issue #6)."""

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from homeassistant.util import slugify

from custom_components.tarifeau.sensor import CAPTEURS, ECART
from tests.test_sensor import ATTRS, INDEX, _demarrer, _entree

RACINE = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("generer", RACINE / "scripts" / "generer_tableau_de_bord.py")
generer = importlib.util.module_from_spec(_spec)
sys.modules["generer"] = generer
_spec.loader.exec_module(generer)


def _entites(noeud) -> set[str]:
    if isinstance(noeud, dict):
        trouve = {noeud["entity"]} if "entity" in noeud else set()
        for valeur in noeud.values():
            trouve |= _entites(valeur)
        return trouve
    if isinstance(noeud, list):
        return set().union(*(_entites(v) for v in noeud)) if noeud else set()
    if isinstance(noeud, str) and noeud.startswith("sensor."):
        return {noeud}
    return set()


def test_cles_alignees_sur_les_capteurs() -> None:
    assert set(generer.CLES) == {d.key for d in CAPTEURS} | {ECART.key}


@pytest.mark.parametrize(
    "nom", ["Facture d'eau", "Maison", "Voisin Dupont", "Éric & Zoé", "  Rez-de-chaussée 2 "]
)
def test_slug_identique_a_home_assistant(nom: str) -> None:
    assert generer.slug(nom) == slugify(nom)


def test_fichier_de_reference_a_jour() -> None:
    """dashboard/facture_eau.yaml = sortie du script sans argument (à régénérer sinon)."""
    assert (RACINE / "dashboard" / "facture_eau.yaml").read_text(encoding="utf-8") == generer.en_yaml(
        [generer.NOM_PAR_DEFAUT], 300
    )


def test_plusieurs_entrees(tmp_path) -> None:
    sortie = tmp_path / "t.yaml"
    assert generer.main(["Maison", "Dupont", "--max", "400", "-o", str(sortie)]) == 0
    tableau = yaml.safe_load(sortie.read_text(encoding="utf-8"))
    sections = tableau["views"][0]["sections"]
    assert [s["cards"][0]["heading"] for s in sections] == [
        "Maison",
        "Maison : coûts",
        "Maison : détail de la facture en cours",
        "Dupont",
        "Dupont : coûts",
        "Dupont : détail de la facture en cours",
    ]
    assert sections[3]["cards"][1]["max"] == 400
    entites = _entites(tableau)
    assert {f"sensor.dupont_{cle}" for cle in generer.CLES} <= entites
    assert all(e.startswith(("sensor.maison_", "sensor.dupont_")) for e in entites)


def test_noms_en_double_refuses(tmp_path) -> None:
    with pytest.raises(SystemExit):
        generer.main(["Maison", "maison", "-o", str(tmp_path / "t.yaml")])


@pytest.fixture
def le_1er_avril(freezer) -> None:
    freezer.move_to("2026-04-01 12:00:00+02:00")


@pytest.mark.usefixtures("le_1er_avril")
async def test_entites_et_carte_detail_sur_une_vraie_entree(hass: HomeAssistant) -> None:
    hass.states.async_set(INDEX, "130", ATTRS)
    await _demarrer(hass, _entree(hass))  # entrée « Maison »
    tableau = generer.tableau(["Maison"], 300)
    for entity_id in _entites(tableau):
        assert hass.states.get(entity_id) is not None, entity_id
    detail = tableau["views"][0]["sections"][2]["cards"][-1]["content"]
    rendu = Template(detail, hass).async_render(parse_result=False)
    assert "| **Eau potable** | | | |" in rendu
    assert "| **Total assainissement** | TVA 10 % |" in rendu
    assert rendu.count("| **Assainissement** | | | |") == 1  # un intertitre par service
    assert "| Abonnement eau potable | 91 j | 15 €/an | 3,74 € |" in rendu  # 1er janvier → 1er avril
    assert "| Redevance consommation d'eau potable | 30 m³ | 0,39 €/m³ | 11,70 € |" in rendu
    assert "Grand Besançon Métropole (régie)" in rendu
    assert "prolongé" not in rendu
