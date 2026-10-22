#!/usr/bin/env python3
"""Génère la vue « Facture d'eau » (cartes natives) pour une ou plusieurs entrées tarifeau.

    uv run --with pyyaml --with loguru python scripts/generer_tableau_de_bord.py                      # « Facture d'eau »
    uv run --with pyyaml --with loguru python scripts/generer_tableau_de_bord.py "Maison" "Dupont" --max 400

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
from loguru import logger

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "dashboard" / "facture_eau.yaml"
NOM_PAR_DEFAUT = "Facture d'eau"
CLES = (
    "cout_releve",
    "cout_jour",
    "cout_hier",
    "cout_semaine",
    "cout_semaine_derniere",
    "cout_mois",
    "cout_mois_dernier",
    "ecart_facture",
    "estimation",
    "prix_marginal",
    "prix_moyen",
    "volume_releve",
    "tranche",
)

EN_TETE = """\
# Tableau de bord Home Assistant « Facture d'eau » (tarifeau), cartes natives uniquement.
#
# Installation : Paramètres > Tableaux de bord > Ajouter un tableau de bord > Nouveau tableau de bord
# à partir de zéro. Ouvre-le, puis crayon > ⋮ > Éditeur de configuration brute : colle ce fichier.
# Pour l'ajouter à un tableau existant, colle seulement le contenu de « views: » comme nouvelle vue.
#
# Généré par scripts/generer_tableau_de_bord.py ({entrees}). Plusieurs compteurs :
#   uv run --with pyyaml --with loguru python scripts/generer_tableau_de_bord.py "Maison" "Dupont" -o mon_tableau.yaml
"""

# Détail ligne par ligne, lu dans les attributs du capteur « Coût depuis la dernière relève ».
DETAIL = """\
{%- set c = 'ENTITE' -%}
{%- set services = state_attr(c, 'services') or {} -%}
{%- set noms = {'eau_potable': 'Eau potable', 'assainissement': 'Assainissement', 'autre': 'Prix fixe'} -%}
{%- macro fr(x, f='%.2f') %}{{ (f % x) | replace('.', ',') }}{% endmacro -%}
| Ligne | Quantité | Prix HT | Montant HT |
|---|--:|--:|--:|
{%- for l in state_attr(c, 'lignes') or [] %}
{%- if loop.changed(l.service) %}
| **{{ noms.get(l.service, l.service) }}** | | | |
{%- endif %}
{%- if l.unite == 'an' %}
| {{ l.libelle }} | {{ l.jours ~ ' j' if l.jours is defined else fr(l.quantite, '%g') ~ ' an' }} | {{ fr(l.prix_unitaire_ht, '%g') }} €/an | {{ fr(l.montant_ht) }} € |
{%- else %}
| {{ l.libelle }} | {{ fr(l.quantite, '%g') }} m³ | {{ fr(l.prix_unitaire_ht, '%g') }} €/m³ | {{ fr(l.montant_ht) }} € |
{%- endif %}
{%- endfor %}
{%- for code, s in services.items() %}
| **Total {{ noms.get(code, code) | lower }}** | TVA {{ fr(s.taux_tva, '%g') }} % | {{ fr(s.ht) }} € HT | **{{ fr(s.ttc) }} € TTC** |
{%- endfor %}

Tarif : [{{ state_attr(c, 'tarif') }}]({{ state_attr(c, 'source') }})
{%- if state_attr(c, 'tarif_prolonge') %} — **tarif de l'année pas encore saisi, dernier tarif prolongé**{% endif %}"""


def slug(nom: str) -> str:
    """Comme homeassistant.util.slugify pour les noms courants : « Facture d'eau » → facture_d_eau."""
    logger.debug("slug: entrée | nom={!r:.80}", nom)
    ascii_ = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    logger.debug("slug: sortie")
    return re.sub(r"[^a-z0-9]+", "_", ascii_.lower()).strip("_") or "facture_d_eau"


def sections(nom: str, maximum: int) -> list[dict]:
    """Trois sections par entrée : résumé (jauge et prix), coûts (statistiques), détail."""
    logger.debug("sections: entrée | nom={!r:.80}, maximum={!r:.80}", nom, maximum)
    e = {cle: f"sensor.{slug(nom)}_{cle}" for cle in CLES}
    resume = {
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
                "name": "Prochaine facture",
                "vertical": True,
            },
            {
                "type": "tile",
                "entity": e["ecart_facture"],
                "name": "Écart facture",
                "icon": "mdi:receipt-text-check",
            },
            {"type": "tile", "entity": e["prix_marginal"], "name": "Prix du prochain m³", "icon": "mdi:cash"},
            {"type": "tile", "entity": e["prix_moyen"], "name": "Prix moyen", "icon": "mdi:scale-balance"},
            {
                "type": "tile",
                "entity": e["volume_releve"],
                "name": "Volume",
                "icon": "mdi:water",
            },
            {"type": "tile", "entity": e["tranche"], "name": "Tranche actuelle", "icon": "mdi:stairs"},
        ],
    }
    couts = {
        "type": "grid",
        "cards": [
            {
                "type": "heading",
                "heading": f"{nom} : coûts",
                "heading_style": "subtitle",
                "icon": "mdi:chart-bar",
            },
            # Coût par période (issue #36) : en cours à gauche, période précédente à droite.
            {"type": "tile", "entity": e["cout_jour"], "name": "Aujourd'hui", "icon": "mdi:calendar-today"},
            {"type": "tile", "entity": e["cout_hier"], "name": "Hier", "icon": "mdi:calendar-arrow-left"},
            {
                "type": "tile",
                "entity": e["cout_semaine"],
                "name": "Cette semaine",
                "icon": "mdi:calendar-week",
            },
            {
                "type": "tile",
                "entity": e["cout_semaine_derniere"],
                "name": "Semaine dernière",
                "icon": "mdi:calendar-week-begin",
            },
            {"type": "tile", "entity": e["cout_mois"], "name": "Ce mois-ci", "icon": "mdi:calendar-month"},
            {
                "type": "tile",
                "entity": e["cout_mois_dernier"],
                "name": "Mois dernier",
                "icon": "mdi:calendar-month-outline",
            },
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
                "title": "Coût par semaine",
                "entities": [e["cout_releve"]],
                "stat_types": ["change"],
                "period": "week",
                "days_to_show": 84,
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
        ],
    }
    detail = {
        "type": "grid",
        "column_span": 2,  # tableau à 4 colonnes : trop étroit sur une seule
        "cards": [
            {
                "type": "heading",
                "heading": f"{nom} : détail de la facture en cours",
                "heading_style": "subtitle",
                "icon": "mdi:receipt-text-outline",
            },
            {"type": "markdown", "content": DETAIL.replace("ENTITE", e["cout_releve"])},
        ],
    }
    logger.debug("sections: sortie")
    return [resume, couts, detail]


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
                "sections": [s for nom in noms for s in sections(nom, maximum)],
            }
        ],
    }


class _Dumper(yaml.SafeDumper):
    pass


def _texte(dumper: yaml.SafeDumper, valeur: str) -> yaml.ScalarNode:
    logger.debug("_texte: entrée | dumper={!r:.80}, valeur={!r:.80}", dumper, valeur)
    style = "|" if "\n" in valeur else None
    logger.debug("_texte: sortie")
    return dumper.represent_scalar("tag:yaml.org,2002:str", valeur, style=style)


_Dumper.add_representer(str, _texte)


def en_yaml(noms: list[str], maximum: int) -> str:
    """Texte YAML du tableau, avec son en-tête."""
    logger.debug("en_yaml: entrée | noms={!r:.80}, maximum={!r:.80}", noms, maximum)
    corps = yaml.dump(tableau(noms, maximum), Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=120)
    logger.debug("en_yaml: sortie")
    return EN_TETE.format(entrees=", ".join(f"« {n} »" for n in noms)) + corps


def main(argv: list[str] | None = None) -> int:
    logger.debug("main: entrée | argv={!r:.80}", argv)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("noms", nargs="*", default=[NOM_PAR_DEFAUT], help="noms des entrées tarifeau")
    parser.add_argument("--max", type=int, default=300, help="maximum de la jauge, en € (défaut : 300)")
    parser.add_argument("-o", "--sortie", type=Path, default=SORTIE, help="fichier à écrire")
    args = parser.parse_args(argv)
    if len({slug(n) for n in args.noms}) != len(args.noms):
        parser.error("deux noms donnent les mêmes identifiants d'entités")
    args.sortie.parent.mkdir(parents=True, exist_ok=True)
    args.sortie.write_text(en_yaml(args.noms, args.max), encoding="utf-8")
    logger.info("{} : {} section(s)", args.sortie, len(args.noms))
    return 0


if __name__ == "__main__":
    sys.exit(main())
