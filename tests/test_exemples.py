"""Exemples de docs/ : ils doivent marcher tels quels dans Home Assistant (issue #10)."""

import importlib.util
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml
from pytest_homeassistant_custom_component.common import async_mock_service

RACINE = Path(__file__).parents[1]
EXEMPLES = RACINE / "docs/exemples"
PRIX = "sensor.facture_d_eau_prix_marginal"


@pytest.mark.parametrize(("etat", "attendu"), [("4.1234", 4.12), ("unavailable", None)])
async def test_prix_marginal_vers_l_esp(hass: HomeAssistant, etat, attendu) -> None:
    appels = async_mock_service(hass, "number", "set_value")
    automatisations = load_yaml(str(EXEMPLES / "esphome_prix_marginal.yaml"))
    assert await async_setup_component(hass, "automation", {"automation": automatisations})
    await hass.async_block_till_done()
    hass.states.async_set(PRIX, etat, {"unit_of_measurement": "EUR/m³"})
    await hass.async_block_till_done()
    if attendu is None:
        assert appels == []
        return
    assert len(appels) == 1
    assert appels[0].data["entity_id"] == ["number.compteur_eau_lora_prix_de_l_eau_au_m3"]
    assert appels[0].data["value"] == attendu


# --- Publication : notes de version et contrôle du tag -------------------------------------------

_spec = importlib.util.spec_from_file_location("publication", RACINE / "scripts" / "notes_de_version.py")
publication = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(publication)


def test_notes_de_la_version_du_manifest(capsys) -> None:
    version = publication.version_manifest()
    assert publication.main(["notes", f"v{version}"]) == 0
    sortie = capsys.readouterr().out
    assert "### Ajouté" in sortie
    assert "## [" not in sortie  # une seule section, sans son titre


def test_tag_different_du_manifest(capsys, journal_loguru) -> None:
    assert publication.main(["notes", "v9.9.9"]) == 1
    assert any("manifest.json" in m for m in journal_loguru)
    assert capsys.readouterr().out == ""  # rien dans notes.md
    assert publication.main(["notes"]) == 2
    assert "Usage" in capsys.readouterr().err


def test_version_absente_du_journal() -> None:
    journal = "# Journal\n\n## [0.2.0] : 2027-01-01\n\n- truc\n\n## [0.1.0] : 2026-10-18\n\n"
    assert publication.notes("0.2.0", journal) == "- truc\n"
    with pytest.raises(ValueError, match="absente"):
        publication.notes("0.1.0", journal)  # section vide
    with pytest.raises(ValueError, match="absente"):
        publication.notes("0.3.0", journal)


def test_version_absente_du_vrai_journal(monkeypatch, capsys, journal_loguru) -> None:
    monkeypatch.setattr(publication, "version_manifest", lambda: "0.0.1")
    assert publication.main(["notes", "v0.0.1"]) == 1
    assert any("absente" in m for m in journal_loguru)
    assert capsys.readouterr().out == ""
