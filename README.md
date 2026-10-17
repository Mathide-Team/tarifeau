# tarifeau

Intégration Home Assistant qui calcule **ta facture d'eau réelle** (France) à partir de **ta consommation** : abonnement, tranches, eau potable, assainissement, redevances des agences de l'eau et TVA, sur ta période de facturation. Elle vient avec un tableau de bord.

> Projet en démarrage : la feuille de route est dans les [issues](https://github.com/Mathide-Team/tarifeau/issues). Il est né de [Esphome-Compteur-wmbus#20](https://github.com/Mathide-Team/Esphome-Compteur-wmbus/issues/20).

## Pourquoi

- Les intégrations d'opérateurs (Veolia, Suez, Eau d'Île-de-France, Eau du Grand Lyon…) lisent la consommation sur le portail client, avec un prix moyen.
- [HydroTarif](https://github.com/jul-fls/ha-hydrotarif) donne le **prix moyen par commune** d'après SISPEA : TTC, calculé sur 120 m³/an, abonnement réparti.
- Il manque le **calcul de la facture d'après la conso réelle**, à partir de n'importe quel capteur d'index : compteur wM-Bus [Esphome-Compteur-wmbus](https://github.com/Mathide-Team/Esphome-Compteur-wmbus), capteur à impulsions, intégration d'opérateur… Par exemple, à Besançon, les 3 premiers m³ sont gratuits et la TVA vaut 5,5 % pour l'eau potable, 10 % pour l'assainissement.

tarifeau complète ces intégrations sans les refaire. Il peut se servir de HydroTarif comme source de prix par défaut.

## Installation (HACS)

> En cours : configuration, capteurs et tableau de bord disponibles ; la première version est suivie dans l'issue #10.

1. HACS → menu ⋮ → **Dépôts personnalisés** → `https://github.com/Mathide-Team/tarifeau`, catégorie **Intégration**.
2. Installer **tarifeau**, puis redémarrer Home Assistant (2026.3 ou plus récent, pour l'icône fournie dans `brand/`).
3. **Paramètres → Appareils et services → Ajouter une intégration → tarifeau**, puis :
   1. le **capteur d'index** du compteur (m³ ou L, `state_class` `total_increasing` ou `total`), par exemple « Compteur eau - Volume total » d'[Esphome-Compteur-wmbus](https://github.com/Mathide-Team/Esphome-Compteur-wmbus). Une facture par compteur : une par voisin, par exemple ;
   2. la **source du tarif** : le tarif d'une collectivité (avec ou sans assainissement collectif) ou un prix fixe TTC au m³ ;
   3. la **dernière relève** : facturation annuelle ou semestrielle, date et index, repris de ta dernière facture.

   Ensuite, **Configurer** permet de changer de tarif ou de saisir une nouvelle relève à chaque facture.

## Capteurs

Un appareil « Facture d'eau » par entrée, recalculé à chaque nouvel index (et à minuit) :

| Capteur | Unité | Usage |
|---|---|---|
| Coût depuis la dernière relève | € TTC | détail HT, TVA et TTC par service et ligne par ligne en attributs, avec le tarif et sa source |
| Estimation de la prochaine facture | € TTC | projection à la fin de la période (6 ou 12 mois après la relève), au rythme actuel |
| Prix marginal | €/m³ TTC | prix du prochain m³ selon la tranche : **entité de prix pour le tableau de bord Énergie** (Eau) |
| Prix moyen | €/m³ TTC | total / volume, abonnements compris |
| Volume depuis la dernière relève | m³ | |
| Tranche actuelle | 1, 2, 3… | attribut `volume_restant` avant la tranche suivante |

Les capteurs gardent leur dernière valeur si l'index devient indisponible, et la retrouvent au redémarrage. Si le tarif de l'année n'est pas encore dans le préréglage, le dernier tarif connu est prolongé : l'attribut `tarif_prolonge` passe alors à `true` et un avertissement est écrit dans le journal.

**Tableau de bord Énergie** : Paramètres → Tableaux de bord → Énergie → Consommation d'eau → ajouter le capteur d'index, puis « Utiliser une entité avec le prix actuel » → **Prix marginal**.

## Tableau de bord

[`dashboard/facture_eau.yaml`](dashboard/facture_eau.yaml) est une vue « Facture d'eau » faite uniquement de cartes natives : jauge du coût depuis la relève, estimation, prix marginal et prix moyen, volume, tranche, coût par jour et par mois (statistiques), et détail ligne par ligne (carte Markdown avec le HT, la TVA et le TTC de chaque service, ainsi que le lien vers la délibération).

Il suppose une entrée nommée « Facture d'eau ». Les capteurs ont des identifiants fixes, quelle que soit la langue : `sensor.<nom>_<clé>`, par exemple `sensor.facture_d_eau_prix_marginal`. Pour d'autres noms, ou une section par compteur :

```bash
uv run --with pyyaml python scripts/generer_tableau_de_bord.py "Maison" "Dupont" --max 400 -o mon_tableau.yaml
```

Puis Paramètres → Tableaux de bord → Ajouter un tableau de bord → à partir de zéro → ⋮ → Éditeur de configuration brute, et coller le fichier.

## Décrire un tarif

Un tarif est un fichier YAML, rangé dans `custom_components/tarifeau/tarifs/`. Le format est documenté en tête de `modele.py` :

- une ou plusieurs **périodes** (dates d'effet), chacune avec l'URL de la délibération ;
- pour chaque **service** (`eau_potable`, `assainissement`, `autre`) : son taux de TVA, ses abonnements (€ HT/an) et ses composantes au m³ (€ HT/m³), éventuellement par **tranches annuelles** ;
- les **redevances** de l'agence de l'eau sont des composantes marquées `redevance: true`.

Préréglages fournis :

| Collectivité | Depuis | 120 m³ | Source |
|---|---|---|---|
| Grand Besançon Métropole (régie) | 01/01/2026 | 484,23 € TTC, égal à la facture type officielle | [RPQS 2025](https://datasets.grandbesancon.fr/fichiers/delibs/grandBesancon/conseilCommunautaire/2026/20260924/0000C9DA.PDF) |
| Grand Belfort (régie) | 01/05/2026 | 624,32 € TTC (assainissement non assujetti à la TVA) | [page Abonnements et tarifs](https://www.grandbelfort.fr/eau/abonnements-et-tarifs.html) |

Ta commune manque ? Ouvre une issue **« Ajouter ma commune »**, ou suis le guide [`tarifs/CONTRIBUER.md`](custom_components/tarifeau/tarifs/CONTRIBUER.md).

## Comment la facture est calculée

Le moteur (`custom_components/tarifeau/calcul.py`, Python pur) reprend les règles des factures :

- la période facturée est découpée au 1er janvier et à chaque changement de tarif. Le volume est réparti **au prorata des jours** ;
- l'**abonnement** est proratisé au jour près (365 ou 366 jours) ;
- les **tranches** sont annuelles. Elles s'appliquent au volume cumulé depuis le 1er janvier (`cumul_annuel`, par défaut), ou avec des seuils proratisés selon la durée de la facture (`prorata`). La gratuité des premiers m³ est une tranche à 0 € ;
- on calcule le HT par ligne, la TVA **par service** (5,5 % pour l'eau potable, 10 % pour l'assainissement), puis le TTC. Seul le total est arrondi au centime ;
- sorties pour les capteurs : **prix marginal** du prochain m³ (TTC), **prix moyen**, tranche actuelle et volume restant avant la tranche suivante ;
- si l'index revient en arrière, le compteur est considéré comme remplacé.

## Développement

```bash
uv run --only-group lint ruff check . && uv run --only-group lint ruff format --check .
uv run -p 3.13 --only-group test pytest --cov     # Home Assistant 2026.2.3 (pytest-homeassistant-custom-component)
```

| Dossier | Rôle |
|---|---|
| `custom_components/tarifeau/` | L'intégration (seul dossier installé par HACS) |
| `custom_components/tarifeau/calcul.py` | Moteur de calcul en Python pur, sans Home Assistant |
| `custom_components/tarifeau/brand/` | Icône (256 et 512 px) |
| `tests/` | Tests pytest |

La CI lance aussi **hassfest** et la **validation HACS** (job « Validation Home Assistant »). Ce sont des actions Docker : elles tournent sur `ubuntu-latest` tant que la variable `RUNS_ON_DOCKER` n'est pas définie.

## Socle qualité Mathide-Team

Ce dépôt est créé depuis [`modele-depot`](https://github.com/Mathide-Team/modele-depot). Il suit le [socle qualité de l'équipe](https://github.com/Mathide-Team/.github/blob/main/SOCLE.md) :

- **`main`** (livraison) et **`dev`** (intégration) protégées. On n'y pousse jamais directement : PR vers `dev`, puis PR `dev` → `main`.
- **CI** : job « Qualité (lint, tests) », requis sur les deux branches. À adapter au langage du projet dans `.github/workflows/ci.yml`, en gardant le nom du job.
- **Garde** : `.github/workflows/guard-main.yml` refuse les PR vers `main` qui ne viennent pas de `dev`.
- **Protections versionnées** : `.github/branch-protection/{main,dev}.json`, vérifiées chaque jour par le workflow « Protection des branches ».
- **Licence** : [MIT](LICENSE).

### Après « Use this template »

Les protections ne sont pas copiées par GitHub avec le modèle. Un administrateur les applique une fois :

```bash
gh repo create Mathide-Team/<nom> --public --template Mathide-Team/modele-depot --clone
cd <nom>
scripts/appliquer_socle.sh Mathide-Team/<nom>     # crée dev + applique les protections
```

Puis pour chaque sujet :

```bash
git switch dev && git pull && git switch -c feat/<n°>-description
# …
gh pr create --base dev
```
