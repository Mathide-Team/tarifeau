#!/usr/bin/env python3
"""Génère la vue « Facture d'eau » (cartes natives) pour une ou plusieurs entrées tarifeau.

    uv run --with pyyaml python scripts/generer_tableau_de_bord.py                      # « Facture d'eau »
    uv run --with pyyaml python scripts/generer_tableau_de_bord.py "Maison" "Dupont" --max 400

Une section par entrée (par compteur), dans l'ordre donné. Le nom est celui de l'entrée
(titre dans Paramètres → Appareils et services) : les capteurs s'appellent
sensor.<nom en minuscules, sans accents, _ pour les séparateurs>_<clé>, par exemple
sensor.facture_d_eau_prix_marginal.

Sans argument -o, écrit dashboard/facture_eau.yaml (version de référence, versionnée).
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

import yaml

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "dashboard" / "facture_eau.yaml"
NOM_PAR_DEFAUT = "Facture d'eau"
CLES = ("cout_releve", "estimation", "prix_marginal", "prix_moyen", "volume_releve", "tranche")

EN_TETE = """\
# Tableau de bord Home Assistant « Facture d'eau » (tarifeau), cartes natives uniquement.
#
# Installation : Paramètres > Tableaux de bord > Ajouter un tableau de bord > Nouveau tableau de bord
# à partir de zéro. Ouvre-le, puis crayon > ⋮ > Éditeur de configuration brute : colle ce fichier.
# Pour l'ajouter à un tableau existant, colle seulement le contenu de « views: » comme nouvelle vue.
#
# Généré par scripts/generer_tableau_de_bord.py ({entrees}). Plusieurs compteurs :
#   uv run --with pyyaml python scripts/generer_tableau_de_bord.py "Maison" "Dupont" -o mon_tableau.yaml
"""

# Détail ligne par ligne, lu dans les attributs du capteur « Coût depuis la dernière relève ».
DETAIL = """\
{%- set c = 'ENTITE' -%}
{%- set services = state_attr(c, 'services') or {} -%}
{%- set noms = {'eau_potable': 'Eau potable', 'assainissement': 'Assainissement', 'autre': 'Prix fixe'} -%}
| Service | Ligne | Quantité | Prix HT | Montant HT |
|---|---|--:|--:|--:|
{%- for l in state_attr(c, 'lignes') or [] %}
| {{ noms.get(l.service, l.service) }} | {{ l.libelle }} | {{ l.quantite }} | {{ l.prix_unitaire_ht }} | {{ '%.2f' % l.montant_ht }} € |
{%- endfor %}
{%- for code, s in services.items() %}
| **{{ noms.get(code, code) }}** | TVA {{ s.taux_tva }} % | | {{ '%.2f' % s.ht }} € HT | **{{ '%.2f' % s.ttc }} € TTC** |
{%- endfor %}

Tarif : [{{ state_attr(c, 'tarif') }}]({{ state_attr(c, 'source') }})
{%- if state_attr(c, 'tarif_prolonge') %} — **tarif de l'année pas encore saisi, dernier tarif prolongé**{% endif %}"""


def slug(nom: str) -> str:
    """Comme homeassistant.util.slugify pour les noms courants : « Facture d'eau » → facture_d_eau."""
    ascii_ = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_.lower()).strip("_") or "facture_d_eau"


def section(nom: str, maximum: int) -> dict:
    """Section d'une entrée : jauge, prix, statistiques, détail."""
    e = {cle: f"sensor.{slug(nom)}_{cle}" for cle in CLES}
    return {
        "type": "grid",
        "cards": [
            {"type": "heading", "heading": nom, "icon": "mdi:water-circle"},
            {
                "type": "gauge",
                "entity": e["cout_releve"],
                "name": "Depuis la dernière relève",
                "min": 0,
                "max": maximum,
                "needle": True,
            },
            {
                "type": "tile",
                "entity": e["estimation"],
                "name": "Prochaine facture (estimation)",
                "vertical": True,
            },
            {"type": "tile", "entity": e["prix_marginal"], "name": "Prix du prochain m³", "icon": "mdi:cash"},
            {"type": "tile", "entity": e["prix_moyen"], "name": "Prix moyen", "icon": "mdi:scale-balance"},
            {
                "type": "tile",
                "entity": e["volume_releve"],
                "name": "Volume depuis la relève",
                "icon": "mdi:water",
            },
            {"type": "tile", "entity": e["tranche"], "name": "Tranche actuelle", "icon": "mdi:stairs"},
            {
                "type": "statistics-graph",
                "title": "Coût par jour",
                "entities": [e["cout_releve"]],
                "stat_types": ["change"],
                "period": "day",
                "days_to_show": 30,
                "chart_type": "bar",
            },
            {
                "type": "statistics-graph",
                "title": "Coût par mois",
                "entities": [e["cout_releve"]],
                "stat_types": ["change"],
                "period": "month",
                "days_to_show": 365,
                "chart_type": "bar",
            },
            {
                "type": "markdown",
                "title": "Détail de la facture en cours",
                "content": DETAIL.replace("ENTITE", e["cout_releve"]),
            },
        ],
    }


def tableau(noms: list[str], maximum: int) -> dict:
    """Tableau complet : une vue « Facture d'eau », une section par entrée."""
    return {
        "title": "Facture d'eau",
        "views": [
            {
                "title": "Facture d'eau",
                "path": "facture-eau",
                "icon": "mdi:receipt-text",
                "type": "sections",
                "max_columns": 3,
                "sections": [section(nom, maximum) for nom in noms],
            }
        ],
    }


class _Dumper(yaml.SafeDumper):
    pass


def _texte(dumper: yaml.SafeDumper, valeur: str) -> yaml.ScalarNode:
    style = "|" if "\n" in valeur else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", valeur, style=style)


_Dumper.add_representer(str, _texte)


def en_yaml(noms: list[str], maximum: int) -> str:
    """Texte YAML du tableau, avec son en-tête."""
    corps = yaml.dump(tableau(noms, maximum), Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=120)
    return EN_TETE.format(entrees=", ".join(f"« {n} »" for n in noms)) + corps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("noms", nargs="*", default=[NOM_PAR_DEFAUT], help="noms des entrées tarifeau")
    parser.add_argument("--max", type=int, default=300, help="maximum de la jauge, en € (défaut : 300)")
    parser.add_argument("-o", "--sortie", type=Path, default=SORTIE, help="fichier à écrire")
    args = parser.parse_args(argv)
    if len({slug(n) for n in args.noms}) != len(args.noms):
        parser.error("deux noms donnent les mêmes identifiants d'entités")
    args.sortie.parent.mkdir(parents=True, exist_ok=True)
    args.sortie.write_text(en_yaml(args.noms, args.max), encoding="utf-8")
    print(f"{args.sortie} : {len(args.noms)} section(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
