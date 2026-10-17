"""Constantes de l'intégration tarifeau."""

DOMAIN = "tarifeau"
NOM_PAR_DEFAUT = "Facture d'eau"

CONF_NOM = "name"
CONF_INDEX = "index_entity"  # capteur d'index (m³ ou L, total_increasing)
CONF_SOURCE = "source_tarif"
CONF_PREREGLAGE = "prereglage"
CONF_PRIX_FIXE = "prix_fixe"  # € TTC/m³
CONF_ENTITE_PRIX = "entite_prix"  # capteur de prix moyen €/m³ (HydroTarif…)
CONF_FACTURATION = "facturation"
CONF_DATE_RELEVE = "date_releve"  # AAAA-MM-JJ
CONF_INDEX_RELEVE = "index_releve"  # m³, repris de la facture
CONF_ASSAINISSEMENT = "assainissement"

SOURCE_PREREGLAGE = "prereglage"
SOURCE_PRIX_FIXE = "prix_fixe"
SOURCE_ENTITE_PRIX = "entite_prix"
SOURCES = (SOURCE_PREREGLAGE, SOURCE_PRIX_FIXE, SOURCE_ENTITE_PRIX)

FACTURATIONS = ("annuelle", "semestrielle")
UNITES_INDEX = {"m³": 1, "L": 1000}  # unité → diviseur vers le m³
STATE_CLASSES_INDEX = ("total_increasing", "total")
