"""Recalage sur une facture réelle : action tarifeau.saisir_facture (issue #9)."""

from datetime import date
from decimal import Decimal

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tarifeau.calcul import facture_periode
from custom_components.tarifeau.const import (
    CONF_ASSAINISSEMENT,
    CONF_DATE_RELEVE,
    CONF_ENTITE_PRIX,
    CONF_FACTURATION,
    CONF_INDEX,
    CONF_INDEX_RELEVE,
    CONF_MONTANT_FACTURE,
    CONF_NOM,
    CONF_PREREGLAGE,
    CONF_PRIX_FIXE,
    CONF_SOURCE,
    CONF_VOLUME_FACTURE,
    DOMAIN,
    HISTORIQUE_MAX,
)
from custom_components.tarifeau.modele import charger_tarif

INDEX = "sensor.compteur_eau_volume_total"
ATTRS = {"unit_of_measurement": "m³", "state_class": "total_increasing"}
BESANCON = charger_tarif("grand_besancon_regie")
ECART = "sensor.maison_ecart_facture"
# Premier semestre 2026 : 60 m³ du 1er janvier au 1er juillet (exclu).
CALCUL = facture_periode(BESANCON, date(2026, 1, 1), date(2026, 7, 1), 60).total_ttc


@pytest.fixture(autouse=True)
def le_2_juillet(freezer) -> None:
    freezer.move_to("2026-07-02 12:00:00+02:00")


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
            CONF_FACTURATION: "semestrielle",
            CONF_DATE_RELEVE: "2026-01-01",
            CONF_INDEX_RELEVE: 100,
            **data,
        },
    )
    entry.add_to_hass(hass)
    return entry


async def _demarrer(hass: HomeAssistant, **data) -> MockConfigEntry:
    await hass.config.async_update(currency="EUR", time_zone="Europe/Paris")
    hass.states.async_set(INDEX, "165", ATTRS)
    entry = _entree(hass, **data)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _saisir(hass: HomeAssistant, entry: MockConfigEntry, **champs) -> dict:
    donnees = {
        "config_entry_id": entry.entry_id,
        "debut": "2026-01-01",
        "fin": "2026-07-01",
        "volume": 60,
        "montant_ttc": float(CALCUL),
        **champs,
    }
    reponse = await hass.services.async_call(
        DOMAIN, "saisir_facture", donnees, blocking=True, return_response=True
    )
    await hass.async_block_till_done()
    return reponse


async def test_facture_conforme_et_releve_recalee(hass: HomeAssistant) -> None:
    entry = await _demarrer(hass)
    assert hass.states.get(ECART).state == "unknown"  # pas encore de facture saisie
    reponse = await _saisir(hass, entry, index_releve=160)
    assert reponse["calcul_ttc"] == float(CALCUL)
    assert reponse["ecart"] == 0
    assert reponse["releve_recalee"] is True
    assert reponse["taux_effectif"] == float((CALCUL / 60).quantize(Decimal("0.0001")))
    # Relève recalée : l'entrée a été rechargée et repart du 1er juillet, index 160.
    assert entry.options[CONF_DATE_RELEVE] == "2026-07-01"
    assert entry.options[CONF_INDEX_RELEVE] == 160
    assert Decimal(hass.states.get("sensor.maison_volume_releve").state) == 5
    ecart = hass.states.get(ECART)
    assert Decimal(ecart.state) == 0
    assert ecart.attributes["unit_of_measurement"] == "EUR"
    assert ecart.attributes["montant_ttc"] == float(CALCUL)
    assert ecart.attributes["nombre_factures"] == 1
    assert ecart.attributes["historique"][0]["fin"] == "2026-07-01"
    assert not ir.async_get(hass).async_get_issue(DOMAIN, f"ecart_facture_{entry.entry_id}")


async def test_ecart_au_dela_du_seuil_puis_retour(hass: HomeAssistant) -> None:
    entry = await _demarrer(hass)
    trop = float(CALCUL * Decimal("1.2"))
    reponse = await _saisir(hass, entry, montant_ttc=trop, index_releve=160)
    assert reponse["ecart_pct"] == pytest.approx(20, abs=0.1)
    alerte = ir.async_get(hass).async_get_issue(DOMAIN, f"ecart_facture_{entry.entry_id}")
    assert alerte is not None
    assert alerte.translation_key == "ecart_facture"
    assert alerte.translation_placeholders["ecart_pct"].startswith("+20")
    # Facture suivante, dans le seuil : l'alerte disparaît.
    hass.states.async_set(INDEX, "165", ATTRS)
    un_jour = facture_periode(BESANCON, date(2026, 7, 1), date(2026, 7, 2), 0).total_ttc  # abonnement seul
    await _saisir(hass, entry, debut="2026-07-01", fin="2026-07-02", volume=0, montant_ttc=float(un_jour))
    assert not ir.async_get(hass).async_get_issue(DOMAIN, f"ecart_facture_{entry.entry_id}")


async def test_sans_index_la_releve_avance_du_volume(hass: HomeAssistant) -> None:
    entry = await _demarrer(hass)
    reponse = await _saisir(hass, entry)
    assert reponse["releve_recalee"] is True
    assert entry.options[CONF_INDEX_RELEVE] == 160


async def test_facture_sans_recalage(hass: HomeAssistant) -> None:
    entry = await _demarrer(hass, **{CONF_DATE_RELEVE: "2026-03-01"})
    # Ancienne facture (finie avant la relève actuelle) : historique seulement.
    reponse = await _saisir(hass, entry, debut="2025-07-01", fin="2026-01-01", index_releve=90)
    assert reponse["releve_recalee"] is False
    # Sans index, et ne partant pas de la relève actuelle : pas de recalage non plus.
    reponse = await _saisir(hass, entry, debut="2026-01-01", fin="2026-07-01")
    assert reponse["releve_recalee"] is False
    assert entry.options == {}
    assert len(entry.runtime_data.factures) == 2


@pytest.mark.parametrize(
    ("champs", "cle"),
    [
        ({"fin": "2026-01-01"}, "periode_invalide"),
        ({"fin": "2026-08-01"}, "date_future"),
        ({"index_releve": 170}, "index_incoherent"),
        ({"config_entry_id": "inconnue"}, "entree_inconnue"),
    ],
)
async def test_saisie_refusee(hass: HomeAssistant, champs, cle) -> None:
    entry = await _demarrer(hass)
    with pytest.raises(ServiceValidationError) as erreur:
        await _saisir(hass, entry, **champs)
    assert erreur.value.translation_key == cle
    assert entry.runtime_data.factures == []


async def test_historique_garde_puis_supprime(hass: HomeAssistant, hass_storage) -> None:
    entry = await _demarrer(hass, **{CONF_DATE_RELEVE: "2026-03-01"})
    ancienne = {"debut": "2000-01-01", "volume": 0, "montant_ttc": 0, "ecart": None, "ecart_pct": None}
    entry.runtime_data.factures = [{**ancienne, "fin": str(i)} for i in range(HISTORIQUE_MAX)]
    await _saisir(hass, entry, debut="2025-07-01", fin="2026-01-01")
    assert len(entry.runtime_data.factures) == HISTORIQUE_MAX
    assert entry.runtime_data.factures[-1]["fin"] == "2026-01-01"
    # Rechargement : l'historique est relu depuis le stockage.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.factures[-1]["fin"] == "2026-01-01"
    assert hass.states.get(ECART).attributes["nombre_factures"] == HISTORIQUE_MAX
    # Suppression de l'entrée : historique et alerte supprimés.
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.factures").async_load() is None


async def test_entite_de_prix_inconnue_pas_d_ecart(hass: HomeAssistant) -> None:
    entry = await _demarrer(hass, **{CONF_SOURCE: "entite_prix", CONF_ENTITE_PRIX: "sensor.absent"})
    reponse = await _saisir(hass, entry)
    assert reponse["calcul_ttc"] is None
    assert reponse["ecart"] is None
    assert reponse["ecart_pct"] is None
    assert reponse["tarif"] is None
    assert hass.states.get(ECART).state == "unknown"


async def test_volume_nul_au_prix_fixe(hass: HomeAssistant) -> None:
    entry = await _demarrer(hass, **{CONF_SOURCE: "prix_fixe", CONF_PRIX_FIXE: 4})
    reponse = await _saisir(hass, entry, volume=0, montant_ttc=0.0)
    assert reponse["calcul_ttc"] == 0
    assert reponse["ecart_pct"] is None  # calcul nul : pas de pourcentage
    assert reponse["taux_effectif"] is None


# --- Source « taux de la dernière facture » ------------------------------------------------------


async def test_configuration_taux_facture(hass: HomeAssistant) -> None:
    hass.states.async_set(INDEX, "165", ATTRS)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NOM: "Maison", CONF_INDEX: INDEX}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SOURCE: "taux_facture"})
    assert result["step_id"] == "taux_facture"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MONTANT_FACTURE: 250, CONF_VOLUME_FACTURE: 0}
    )
    assert result["errors"] == {CONF_VOLUME_FACTURE: "volume_nul"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MONTANT_FACTURE: 250, CONF_VOLUME_FACTURE: 60}
    )
    assert result["step_id"] == "releve"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_FACTURATION: "semestrielle", CONF_DATE_RELEVE: "2026-07-01", CONF_INDEX_RELEVE: 160},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MONTANT_FACTURE] == 250
    assert CONF_PREREGLAGE not in result["data"]


async def test_taux_facture_mis_a_jour_par_la_saisie(hass: HomeAssistant) -> None:
    entry = await _demarrer(
        hass,
        **{CONF_SOURCE: "taux_facture", CONF_MONTANT_FACTURE: 240, CONF_VOLUME_FACTURE: 60},
    )
    assert entry.runtime_data.tarif.nom == "Taux de la dernière facture 4.0000 €/m³"
    reponse = await _saisir(hass, entry, montant_ttc=270.0, index_releve=160)
    assert reponse["calcul_ttc"] == 240  # 60 m³ à 4 €
    assert reponse["ecart_pct"] == 12.5
    assert entry.options[CONF_MONTANT_FACTURE] == 270
    assert entry.runtime_data.tarif.nom == "Taux de la dernière facture 4.5000 €/m³"
    assert Decimal(hass.states.get("sensor.maison_prix_marginal").state) == Decimal("4.5")
