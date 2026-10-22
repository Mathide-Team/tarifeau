"""Résumé des valeurs journalisées (issue #52, SOCLE §8).

Une trace de debug montre la forme des données, jamais un objet entier ni
la valeur d'un dictionnaire de saisie.
"""

from __future__ import annotations

import enum
import importlib.util
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from homeassistant.core import State

from custom_components.tarifeau.journal import LONGUEUR_MAX, resumer

DOSSIER = Path(__file__).resolve().parents[1] / "custom_components" / "tarifeau"


class Couleur(enum.Enum):
    BLEU = "bleu"


@dataclass
class Facture:
    total: Decimal


@pytest.mark.parametrize(
    ("valeur", "attendu"),
    [
        (None, "None"),
        (True, "True"),
        (12, "12"),
        (1.5, "1.5"),
        (Decimal("3.4567"), "Decimal('3.4567')"),
        (timedelta(days=2), "datetime.timedelta(days=2)"),
        (date(2026, 1, 15), "2026-01-15"),
        (datetime(2026, 1, 15, 8, 30), "2026-01-15T08:30:00"),
        (time(0, 0, 5), "00:00:05"),
        (Couleur.BLEU, "Couleur.BLEU"),
        ("m³", "'m³'"),
        (b"\x00\x01", "bytes(2 octets)"),
        ([1, 2, 3], "list(3)"),
        ((1,), "tuple(1)"),
        ({1}, "set(1)"),
        (Facture(Decimal(1)), "<Facture>"),
        (object(), "<object>"),
    ],
)
def test_scalaires_et_collections(valeur: object, attendu: str) -> None:
    assert resumer(valeur) == attendu


def test_chaine_longue_tronquee() -> None:
    texte = "x" * (LONGUEUR_MAX + 40)
    assert resumer(texte) == repr("x" * LONGUEUR_MAX) + f"…({LONGUEUR_MAX + 40} car.)"


def test_dictionnaire_cles_sans_valeurs() -> None:
    saisie = {"index": "sensor.compteur", "jeton": "secret-a-ne-pas-voir"}
    resume = resumer(saisie)
    assert resume == "dict(2 clés : index, jeton)"
    assert "secret" not in resume


def test_dictionnaire_long_coupe_a_huit_cles() -> None:
    resume = resumer({f"c{i}": i for i in range(10)})
    assert resume.startswith("dict(10 clés : c0, c1")
    assert resume.endswith("c7, …)")


def test_etat_home_assistant() -> None:
    assert resumer(State("sensor.compteur_eau", "123.4")) == "<State sensor.compteur_eau='123.4'>"


def test_entite_sans_etat_textuel() -> None:
    class Entite:
        entity_id = "sensor.facture_eau"
        state = None

    assert resumer(Entite()) == "<Entite sensor.facture_eau>"


def test_entity_id_non_textuel_ignore() -> None:
    class Bizarre:
        entity_id = 42

    assert resumer(Bizarre()) == "<Bizarre>"


@pytest.mark.parametrize("nom", ["calcul", "modele"])
def test_repli_hors_paquet(nom: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Chargé seul (générateur, test sans Home Assistant), le module garde un
    ``resumer`` qui ne montre que le type."""
    spec = importlib.util.spec_from_file_location(f"_seul_{nom}", DOSSIER / f"{nom}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, f"_seul_{nom}", module)
    spec.loader.exec_module(module)
    assert module.resumer is not resumer
    assert module.resumer({"cle": "valeur"}) == "<dict>"
    assert module.resumer("texte") == "<str>"
