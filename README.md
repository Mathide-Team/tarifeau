# tarifeau

Intégration Home Assistant qui calcule **ta facture d'eau réelle** (France) à partir de **ta consommation** : abonnement, tranches, eau potable, assainissement, redevances des agences de l'eau et TVA, sur ta période de facturation. Elle vient avec un tableau de bord.

> Projet en démarrage : la feuille de route est dans les [issues](https://github.com/Mathide-Team/tarifeau/issues). Il est né de [Esphome-Compteur-wmbus#20](https://github.com/Mathide-Team/Esphome-Compteur-wmbus/issues/20).

## Pourquoi

- Les intégrations d'opérateurs (Veolia, Suez, Eau d'Île-de-France, Eau du Grand Lyon…) lisent la consommation sur le portail client, avec un prix moyen.
- [HydroTarif](https://github.com/jul-fls/ha-hydrotarif) donne le **prix moyen par commune** d'après SISPEA : TTC, calculé sur 120 m³/an, abonnement réparti.
- Il manque le **calcul de la facture d'après la conso réelle**, à partir de n'importe quel capteur d'index : compteur wM-Bus [Esphome-Compteur-wmbus](https://github.com/Mathide-Team/Esphome-Compteur-wmbus), capteur à impulsions, intégration d'opérateur… Par exemple, à Besançon, les 3 premiers m³ sont gratuits et la TVA vaut 5,5 % pour l'eau potable, 10 % pour l'assainissement.

tarifeau complète ces intégrations sans les refaire. Il peut se servir de HydroTarif comme source de prix par défaut.

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
