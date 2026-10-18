# Tarif personnel (fichier YAML)

Quand aucun préréglage ne correspond à ton service d'eau, décris ton tarif dans un fichier YAML du dossier `/config/tarifeau/` de Home Assistant, à côté de `configuration.yaml`. Le format est celui des préréglages de [`custom_components/tarifeau/tarifs/`](../custom_components/tarifeau/tarifs/).

## Mise en place

1. Crée `/config/tarifeau/`.
2. Copie [`exemples/mon_tarif.yaml`](exemples/mon_tarif.yaml) sous un nom simple : `ma_commune.yaml`. Le nom du fichier sert d'identifiant, il ne doit pas changer une fois l'entrée créée.
3. Remplis-le à partir de ta facture ou, mieux, de la délibération tarifaire de ta collectivité (voir [CONTRIBUER.md](../custom_components/tarifeau/tarifs/CONTRIBUER.md), « Trouver la source officielle »).
4. Dans Home Assistant : **Paramètres → Appareils et services → tarifeau → Configurer → Vérifier mes fichiers de tarif**.
5. Puis **Changer de tarif → Tarif d'une collectivité**, et choisis « Mon tarif : … ». À la création d'une nouvelle entrée, il est proposé au même endroit.

## Correspondance avec la facture

| Sur la facture ou la délibération | Dans le fichier |
|---|---|
| Abonnement, part fixe (€ HT **par an**) | `abonnements: - {nom, montant_ht_an}`. Une part fixe semestrielle se multiplie par 2 |
| Abonnement selon le diamètre du compteur | `montant_ht_an` du compteur courant, plus `par_diametre: {15: 40.00, 20: 64.00}` |
| Prix au m³ (€ HT) | `composantes: - {nom, prix_ht}` |
| Tranches (0 à 30 m³, puis au-delà) | `tranches:` avec des seuils `jusqua` **annuels** croissants ; la dernière n'a pas de seuil |
| m³ gratuits | première tranche à `prix_ht: 0` |
| Redevances de l'agence de l'eau | composantes avec `redevance: true` |
| TVA | `tva` du service : 5,5 pour l'eau potable, 10 pour l'assainissement, 0 s'il n'est pas assujetti |

Une facture qui ne couvre pas l'année entière applique les tranches annuelles selon `tranches` :
- `cumul_annuel` : la 1re facture de l'année compte depuis 0 m³, la suivante reprend le cumul ;
- `prorata` : les seuils sont réduits selon la durée de la facture.

## Nouveau tarif au 1er janvier

Ajoute une période. Celle d'avant reçoit une `fin` (veille du nouveau `debut`) :

```yaml
periodes:
  - debut: 2026-01-01
    fin: 2026-12-31
    source: https://…/deliberation-2026.pdf
    services: …
  - debut: 2027-01-01
    source: https://…/deliberation-2027.pdf
    services: …
```

Recharge ensuite l'intégration. Tant que la période de l'année n'existe pas, le dernier tarif est prolongé, et l'attribut `tarif_prolonge` le signale.

## Erreurs

La vérification indique le fichier et le chemin de la valeur fautive, par exemple :

```
ma_commune.yaml : tarif.periodes[0].services.eau_potable.composantes[0].tranches[0].prix_ht : doit être positif ou nul
```

Si un fichier utilisé est supprimé ou devient invalide, l'entrée s'arrête avec ce message (Paramètres → Appareils et services → tarifeau), au lieu de calculer une facture fausse. Corrige le fichier, puis recharge l'intégration.

## Partager ton tarif

Un tarif vérifié sur une vraie facture peut devenir un préréglage pour tout le monde : ouvre une issue « Ajouter ma commune » avec le fichier, ou une PR qui l'ajoute dans `custom_components/tarifeau/tarifs/`.
