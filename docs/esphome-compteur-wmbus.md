# Exemple complet : tarifeau avec Esphome-Compteur-wmbus

[Esphome-Compteur-wmbus](https://github.com/Mathilde-Team/Esphome-Compteur-wmbus) lit par radio (wM-Bus) l'index de ton compteur d'eau et de ceux des voisins. tarifeau en fait des factures.

Les noms d'entités ci-dessous sont ceux de la configuration par défaut de l'ESP (`compteur-eau-lora`, « Compteur Eau LoRa »). Retrouve les tiens dans Paramètres → Appareils et services → ESPHome.

## 1. Une facture par compteur

Paramètres → Appareils et services → Ajouter une intégration → **tarifeau**.

| Compteur | Capteur d'index à choisir | Nom de la facture conseillé |
|---|---|---|
| Le tien | « Compteur eau - Volume total » (`sensor.compteur_eau_lora_compteur_eau_volume_total`) — proposé par défaut s'il est détecté | Facture d'eau |
| Voisin « Dupont » | « Dupont - Index » (`sensor.compteur_eau_lora_dupont_index`) | Dupont |

Les index de l'ESP sont en m³, en `total_increasing` : ils conviennent tels quels. Si le capteur « Volume total » de ton compteur est présent (et lui seul), il est déjà pré-choisi dans le formulaire. Il est reconnu par le marqueur stable de l'ESP : appareil de fabricant `mathilde-team` et de modèle `compteur-eau-wmbus`, et capteur de nom d'origine « Compteur eau - Volume total » ([Esphome-Compteur-wmbus#47](https://github.com/Mathilde-Team/Esphome-Compteur-wmbus/issues/47)). Il reste reconnu si tu as renommé l'appareil ou l'entité, et les index des voisins ne sont jamais proposés. Un ESP flashé avant ce marqueur reste reconnu par son nom. Choisis ensuite le préréglage de ta collectivité (Grand Besançon, Grand Belfort…), puis la date et l'index de la dernière facture.

## 2. Tableau de bord Énergie

Paramètres → Tableaux de bord → **Énergie** → Consommation d'eau → Ajouter :

- **Consommation** : le capteur d'index de l'ESP ;
- **Coût** : « Utiliser une entité avec le prix actuel » → **Facture d'eau Prix marginal** (`sensor.facture_d_eau_prix_marginal`).

Le tableau de bord Énergie multiplie chaque m³ par le prix du moment. Avec le prix marginal, les m³ gratuits coûtent bien 0 €, et chaque tranche est comptée à son prix. L'abonnement n'est pas dans ce tableau : il se trouve dans « Coût depuis la dernière relève ».

## 3. Le prix du prochain m³ recopié dans l'ESP

L'ESP a un réglage **« Prix de l'eau au m³ »** (`number.compteur_eau_lora_prix_de_l_eau_au_m3`), saisi à la main. Il sert à ses capteurs « Coût jour » et « Coût mois », et à son écran. L'automatisation [exemples/esphome_prix_marginal.yaml](exemples/esphome_prix_marginal.yaml) y recopie le prix marginal de tarifeau à chaque changement de tranche ou de tarif, et au démarrage de Home Assistant :

```yaml
- alias: "tarifeau - prix de l'eau vers l'ESP"
  id: tarifeau_prix_eau_vers_esp
  mode: queued
  triggers:
    - trigger: state
      entity_id: sensor.facture_d_eau_prix_marginal
    - trigger: homeassistant
      event: start
  conditions:
    - condition: template
      value_template: "{{ states('sensor.facture_d_eau_prix_marginal') | is_number }}"
  actions:
    - action: number.set_value
      target:
        entity_id: number.compteur_eau_lora_prix_de_l_eau_au_m3
      data:
        value: "{{ states('sensor.facture_d_eau_prix_marginal') | float | round(2) }}"
```

Les coûts de l'ESP restent sans abonnement. Pour le montant complet de la facture, utilise les capteurs de tarifeau.

## 4. Tableau de bord des factures

Le générateur fait une section par facture :

```bash
uv run --with pyyaml --with loguru python scripts/generer_tableau_de_bord.py "Facture d'eau" "Dupont" -o factures.yaml
```

Puis Paramètres → Tableaux de bord → Ajouter → à partir de zéro → ⋮ → Éditeur de configuration brute, et colle le fichier.

## 5. À chaque facture

Outils de développement → Actions → **tarifeau : Saisir une facture**, avec les dates, le volume, le montant TTC et l'index relevé. La relève est recalée, et un écart de plus de 10 % lève une alerte (Réparations), qu'on peut aussi recevoir par ntfy : voir le blueprint dans le [README](../README.md#notification-ntfy). Les voisins qui utilisent déjà [Esphome-Compteur-wmbus-ntfy](https://github.com/Mathilde-Team/Esphome-Compteur-wmbus-ntfy) peuvent la recevoir sur le même sujet.
