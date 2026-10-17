"""Capteurs de la facture (issue #5)."""

from datetime import date
from decimal import Decimal

import pytest
from homeassistant.components.energy.validate import (
    WATER_PRICE_UNIT_ERROR,
    WATER_PRICE_UNITS,
    ValidationIssues,
    _async_validate_price_entity,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)

from custom_components.tarifeau.calcul import facture_periode
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
from custom_components.tarifeau.modele import charger_tarif
from custom_components.tarifeau.suivi import ajouter_mois

INDEX = "sensor.compteur_eau_volume_total"
ATTRS = {"unit_of_measurement": "m³", "state_class": "total_increasing"}
BESANCON = charger_tarif("grand_besancon_regie")


def _entree(hass: HomeAssistant, **options) -> MockConfigEntry:
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
        },
        options=options,
    )
    entry.add_to_hass(hass)
    return entry


async def _demarrer(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, str]:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registre = er.async_get(hass)
    return {
        e.unique_id.removeprefix(f"{entry.entry_id}_"): e.entity_id
        for e in er.async_entries_for_config_entry(registre, entry.entry_id)
    }


def _valeur(hass: HomeAssistant, entity_id: str) -> str:
    return hass.states.get(entity_id).state


@pytest.fixture
def le_1er_avril(freezer) -> None:
    freezer.move_to("2026-04-01 12:00:00+02:00")


@pytest.mark.usefixtures("le_1er_avril")
async def test_capteurs_au_1er_avril(hass: HomeAssistant) -> None:
    await hass.config.async_update(currency="EUR", time_zone="Europe/Paris")
    hass.states.async_set(INDEX, "130", ATTRS)  # 30 m³ depuis la relève du 1er janvier
    ids = await _demarrer(hass, _entree(hass))
    assert set(ids) == {
        "cout_releve",
        "cout_jour",
        "cout_mois",
        "estimation",
        "prix_marginal",
        "prix_moyen",
        "volume_releve",
        "tranche",
    }

    attendu = facture_periode(BESANCON, date(2026, 1, 1), date(2026, 4, 2), 30)
    cout = hass.states.get(ids["cout_releve"])
    assert Decimal(cout.state) == attendu.total_ttc
    assert cout.attributes["unit_of_measurement"] == "EUR"
    assert cout.attributes["device_class"] == "monetary"
    assert cout.attributes["state_class"] == "total"
    assert cout.attributes["tarif"] == "Grand Besançon Métropole (régie)"
    assert cout.attributes["tarif_prolonge"] is False
    assert cout.attributes["source"].startswith("https://datasets.grandbesancon.fr/")
    assert set(cout.attributes["services"]) == {"eau_potable", "assainissement"}

    # Projection au 1er juillet, au rythme de 30 m³ en 91 jours.
    estimation = facture_periode(BESANCON, date(2026, 1, 1), date(2026, 7, 1), Decimal(30) * 181 / 91)
    assert Decimal(_valeur(hass, ids["estimation"])) == estimation.total_ttc
    assert hass.states.get(ids["estimation"]).attributes["fin_periode"] == "2026-07-01"

    assert Decimal(_valeur(hass, ids["volume_releve"])) == 30
    assert _valeur(hass, ids["tranche"]) == "2"
    assert hass.states.get(ids["tranche"]).attributes["volume_restant"] == 70
    prix = hass.states.get(ids["prix_marginal"])
    assert prix.attributes["unit_of_measurement"] == "EUR/m³"
    assert Decimal(prix.state) == (
        Decimal("1.865") * Decimal("1.055") + Decimal("1.70") * Decimal("1.10")
    ).quantize(Decimal("0.0001"))
    assert Decimal(_valeur(hass, ids["prix_moyen"])) == (attendu.prix_moyen_ttc)


@pytest.mark.usefixtures("le_1er_avril")
async def test_prix_marginal_accepte_par_le_tableau_energie(hass: HomeAssistant) -> None:
    await hass.config.async_update(currency="EUR")
    hass.states.async_set(INDEX, "130", ATTRS)
    ids = await _demarrer(hass, _entree(hass))
    problemes = ValidationIssues()
    _async_validate_price_entity(
        hass, ids["prix_marginal"], problemes, WATER_PRICE_UNITS, WATER_PRICE_UNIT_ERROR
    )
    assert not problemes.issues


@pytest.mark.usefixtures("le_1er_avril")
async def test_mise_a_jour_a_chaque_index_et_index_indisponible(hass: HomeAssistant) -> None:
    hass.states.async_set(INDEX, "130", ATTRS)
    ids = await _demarrer(hass, _entree(hass))
    hass.states.async_set(INDEX, "150", ATTRS)
    await hass.async_block_till_done()
    assert Decimal(_valeur(hass, ids["volume_releve"])) == 50
    hass.states.async_set(INDEX, "unavailable", ATTRS)
    await hass.async_block_till_done()
    assert Decimal(_valeur(hass, ids["volume_releve"])) == 50  # dernière valeur gardée
    hass.states.async_remove(INDEX)
    await hass.async_block_till_done()
    assert Decimal(_valeur(hass, ids["volume_releve"])) == 50


@pytest.mark.usefixtures("le_1er_avril")
async def test_index_en_litres_et_compteur_remplace(hass: HomeAssistant) -> None:
    hass.states.async_set(INDEX, "130500", {**ATTRS, "unit_of_measurement": "L"})
    ids = await _demarrer(hass, _entree(hass))
    assert Decimal(_valeur(hass, ids["volume_releve"])) == Decimal("30.5")
    hass.states.async_set(INDEX, "4", ATTRS)  # nouveau compteur
    await hass.async_block_till_done()
    assert Decimal(_valeur(hass, ids["volume_releve"])) == 4


@pytest.mark.usefixtures("le_1er_avril")
async def test_reprise_apres_redemarrage(hass: HomeAssistant) -> None:
    entry = _entree(hass)
    unique_id = f"{entry.entry_id}_cout_releve"
    registre = er.async_get(hass)
    registre.async_get_or_create("sensor", DOMAIN, unique_id, config_entry=entry, suggested_object_id="cout")
    mock_restore_cache_with_extra_data(
        hass,
        [(State("sensor.cout", "123.45"), {"native_value": 123.45, "native_unit_of_measurement": "EUR"})],
    )
    hass.states.async_set(INDEX, "unavailable", ATTRS)  # index pas encore disponible au démarrage
    await _demarrer(hass, entry)
    assert _valeur(hass, "sensor.cout") == "123.45"


async def test_fin_de_periode_depassee_estimation_egale_au_cout(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2026-08-15 12:00:00+02:00")
    hass.states.async_set(INDEX, "160", ATTRS)
    ids = await _demarrer(hass, _entree(hass))
    assert _valeur(hass, ids["estimation"]) == _valeur(hass, ids["cout_releve"])


async def test_annee_suivante_sans_assainissement_minuit(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2027-02-01 12:00:00+01:00")
    hass.states.async_set(INDEX, "200", ATTRS)
    entry = _entree(
        hass, **{CONF_ASSAINISSEMENT: False, CONF_FACTURATION: "annuelle", CONF_DATE_RELEVE: "2026-02-01"}
    )
    ids = await _demarrer(hass, entry)
    cout = hass.states.get(ids["cout_releve"])
    assert set(cout.attributes["services"]) == {"eau_potable"}
    assert cout.attributes["tarif_prolonge"] is True  # tarif 2027 pas encore saisi
    avant = cout.state
    entry.runtime_data.rafraichir()  # comme à minuit
    await hass.async_block_till_done()
    assert _valeur(hass, ids["cout_releve"]) == avant


@pytest.mark.parametrize(
    ("jour", "mois", "attendu"),
    [
        (date(2026, 1, 1), 6, date(2026, 7, 1)),
        (date(2026, 8, 31), 6, date(2027, 2, 28)),
        (date(2027, 8, 31), 6, date(2028, 2, 29)),
        (date(2026, 7, 15), 12, date(2027, 7, 15)),
    ],
)
def test_ajouter_mois(jour, mois, attendu) -> None:
    assert ajouter_mois(jour, mois) == attendu


async def test_cout_du_jour_et_du_mois(hass: HomeAssistant, freezer, hass_storage) -> None:
    freezer.move_to("2026-04-01 08:00:00+02:00")
    await hass.config.async_update(time_zone="Europe/Paris")
    hass.states.async_set(INDEX, "130", ATTRS)
    entry = _entree(hass)
    ids = await _demarrer(hass, entry)
    # Premier démarrage : repères posés sur l'index actuel ; seule la part d'abonnement du jour compte.
    abonnement_jour = (Decimal(15) * Decimal("1.055") + Decimal(10) * Decimal("1.10")) / 365
    assert Decimal(_valeur(hass, ids["cout_jour"])) == round(abonnement_jour, 2)
    assert Decimal(_valeur(hass, ids["cout_mois"])) == round(abonnement_jour, 2)
    hass.states.async_set(INDEX, "131", ATTRS)  # 1 m³ dans la matinée
    await hass.async_block_till_done()
    un_m3 = Decimal("1.865") * Decimal("1.055") + Decimal("1.70") * Decimal("1.10")  # 2e tranche
    assert Decimal(_valeur(hass, ids["cout_jour"])) == round(un_m3 + abonnement_jour, 2)

    # Le lendemain : le coût du jour repart de l'index de la veille, l'abonnement du jour s'ajoute.
    freezer.move_to("2026-04-02 08:00:00+02:00")
    hass.states.async_set(INDEX, "132", ATTRS)
    await hass.async_block_till_done()
    assert Decimal(_valeur(hass, ids["cout_jour"])) == round(un_m3 + abonnement_jour, 2)
    assert Decimal(_valeur(hass, ids["cout_mois"])) == round(2 * un_m3 + 2 * abonnement_jour, 2)

    # Repères mémorisés (Store), puis supprimés avec l'entrée.
    await hass.async_block_till_done()
    freezer.tick(5)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    cle = f"{DOMAIN}.{entry.entry_id}"
    assert entry.runtime_data.reperes["jour"] == "2026-04-02"
    assert hass_storage[cle]["data"]["jour"] == "2026-04-02"
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert await Store(hass, 1, cle).async_load() is None


async def test_reperes_restaures_et_compteur_remplace(hass: HomeAssistant, freezer, hass_storage) -> None:
    freezer.move_to("2026-04-02 08:00:00+02:00")
    await hass.config.async_update(time_zone="Europe/Paris")
    entry = _entree(hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"jour": "2026-04-01", "index_jour": "125", "mois": "2026-04-01", "index_mois": "120"},
    }
    hass.states.async_set(INDEX, "130", ATTRS)
    ids = await _demarrer(hass, entry)
    # Nouveau jour, repère du mois gardé : 10 m³ depuis le 1er avril.
    assert entry.runtime_data.reperes["index_mois"] == "120"
    assert entry.runtime_data.reperes["index_jour"] == "130"
    assert Decimal(_valeur(hass, ids["cout_mois"])) > 10 * Decimal("1.865")
    # Compteur remplacé le 3 avril : repères repartis du nouvel index.
    freezer.move_to("2026-04-03 08:00:00+02:00")
    hass.states.async_set(INDEX, "2", ATTRS)
    await hass.async_block_till_done()
    assert entry.runtime_data.reperes["index_jour"] == "2"


@pytest.mark.usefixtures("le_1er_avril")
async def test_repere_sans_index_ignore(hass: HomeAssistant) -> None:
    hass.states.async_set(INDEX, "130", ATTRS)
    entry = _entree(hass)
    await _demarrer(hass, entry)
    etat = entry.runtime_data.calculer(Decimal(130), date(2026, 4, 1), {"jour": "2026-04-01"})
    assert etat.cout_jour is None
    assert etat.cout_mois is None
