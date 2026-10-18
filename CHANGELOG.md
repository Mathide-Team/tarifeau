# Journal des versions

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Les numéros suivent [SemVer](https://semver.org/lang/fr/), et la version de `manifest.json` est égale au tag.

## [0.1.0] : non publiée

Première version.

### Ajouté
- **Facture réelle de référence** (#9) : transcription anonymisée d'une facture du Grand Besançon (05/09/2025 au 18/08/2026, 88 m³, 360,87 € TTC), vérifiée par les tests : 360,70 € calculés avec les tarifs 2025 de la commune, 359,12 € (-0,48 %) avec le préréglage seul.
- **Préréglage Grand Besançon** : tranches proratisées selon la durée de la facture, comme sur la facture réelle (#15).
- **Configuration depuis l'interface** (#4) : capteur d'index en m³ ou en L, source du tarif, diamètre du compteur si le tarif en dépend, dernière relève, qui marque le début d'une période de 1, 2, 3, 4, 6 ou 12 mois (#20). Les options permettent de changer de tarif ou de saisir une nouvelle relève. Une entrée par compteur.
- **Modèle de tarif en YAML** (#2) : périodes, services, abonnements, composantes, tranches annuelles cumulées ou proratisées, TVA par service, factures types vérifiées.
- **Moteur de calcul** (#3) : découpage au 1er janvier et à chaque changement de tarif, abonnement au jour près, prix marginal, compteur remplacé.
- **Capteurs** (#5) : coût depuis la relève (détail ligne par ligne), coût du jour et du mois, estimation de la prochaine facture, prix marginal (pour le tableau de bord Énergie), prix moyen, volume, tranche.
- **Tarif personnel en YAML** (#17) : fichiers de `/config/tarifeau/` proposés sous « Mon tarif », vérification dans les options avec le chemin de l'erreur, exemple commenté `docs/exemples/mon_tarif.yaml`.
- **Préréglages** (#7) : Grand Besançon Métropole (régie) 2026 et Grand Belfort au 01/05/2026. Guide de contribution et formulaire « Ajouter ma commune ».
- **Tableau de bord** « Facture d'eau » en cartes natives (résumé, coûts, détail regroupé par service, nombres à la française), avec un générateur pour plusieurs compteurs et des captures dans le README (#6).
- **Source « entité de prix »** (#8) : prix moyen lu sur HydroTarif (données SISPEA) ou sur tout autre capteur en €/m³.
- **Recalage sur facture** (#9) : action `tarifeau.saisir_facture`, capteur d'écart, historique, alerte dans Réparations au-delà de 10 %, source « taux de la dernière facture ».
- **Événement `tarifeau_ecart_facture`** et blueprint de notification ntfy (#26).
- Exemple complet avec Esphome-Compteur-wmbus (#10).
