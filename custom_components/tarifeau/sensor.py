"""Capteurs d'une facture d'eau (issue #5) : un appareil « Facture d'eau » par entrée."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import slugify

from . import TarifeauConfigEntry
from .calcul import Facture, arrondi_euros
from .const import DOMAIN, SEUIL_ECART
from .modele import prolonger
from .suivi import Etat, SuiviFacture

QUATRE_DECIMALES = Decimal("0.0001")


def _detail(facture: Facture) -> dict[str, Any]:
    return {
        "total_ht": float(facture.total_ht),
        "services": {
            s.service: {
                "ht": float(arrondi_euros(s.ht)),
                "tva": float(arrondi_euros(s.tva)),
                "taux_tva": float(s.taux_tva),
                "ttc": float(arrondi_euros(s.ttc)),
            }
            for s in facture.services
        },
    }


def _attributs_cout(etat: Etat) -> dict[str, Any]:
    periode = prolonger(etat.tarif, etat.jour, etat.jour)[0].periode_au(etat.jour)
    return {
        **_detail(etat.facture),
        "lignes": [
            {
                "service": ligne.service,
                "libelle": ligne.libelle,
                "quantite": float(round(ligne.quantite, 4)),
                "prix_unitaire_ht": float(ligne.prix_unitaire_ht),
                "montant_ht": float(arrondi_euros(ligne.montant_ht)),
            }
            for ligne in etat.facture.lignes
        ],
        "tarif": etat.tarif.nom,
        "source": periode.source,
        "date_source": periode.date_source.isoformat(),
        "tarif_prolonge": etat.tarif_prolonge,
        # Source « prix fixe » ou entité de prix : abonnement réparti dans le prix, pas de tranches.
        "prix_moyen_seul": len(periode.services) == 1 and periode.services[0].code == "autre",
    }


@dataclass(frozen=True, kw_only=True)
class DescriptionCapteur(SensorEntityDescription):
    """Description d'un capteur : comment lire sa valeur dans l'état calculé."""

    valeur: Callable[[Etat], Decimal | int | None]
    attributs: Callable[[Etat], dict[str, Any]] | None = None
    unite_prix: bool = False  # unité « <devise>/m³ »
    unite_devise: bool = False  # unité « <devise> »


CAPTEURS: tuple[DescriptionCapteur, ...] = (
    DescriptionCapteur(
        key="cout_releve",
        translation_key="cout_releve",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        unite_devise=True,
        suggested_display_precision=2,
        valeur=lambda e: e.facture.total_ttc,
        attributs=_attributs_cout,
    ),
    DescriptionCapteur(
        key="estimation",
        translation_key="estimation",
        device_class=SensorDeviceClass.MONETARY,
        unite_devise=True,
        suggested_display_precision=2,
        valeur=lambda e: (e.estimation or e.facture).total_ttc,
        attributs=lambda e: {**_detail(e.estimation or e.facture), "fin_periode": e.fin_periode.isoformat()},
    ),
    DescriptionCapteur(
        key="cout_jour",
        translation_key="cout_jour",
        device_class=SensorDeviceClass.MONETARY,
        unite_devise=True,
        suggested_display_precision=2,
        valeur=lambda e: e.cout_jour,
    ),
    DescriptionCapteur(
        key="cout_mois",
        translation_key="cout_mois",
        device_class=SensorDeviceClass.MONETARY,
        unite_devise=True,
        suggested_display_precision=2,
        valeur=lambda e: e.cout_mois,
    ),
    DescriptionCapteur(
        key="prix_marginal",
        translation_key="prix_marginal",
        unite_prix=True,
        suggested_display_precision=4,
        valeur=lambda e: e.marginal.prix_ttc.quantize(QUATRE_DECIMALES),
    ),
    DescriptionCapteur(
        key="prix_moyen",
        translation_key="prix_moyen",
        unite_prix=True,
        suggested_display_precision=4,
        valeur=lambda e: e.facture.prix_moyen_ttc,
    ),
    DescriptionCapteur(
        key="volume_releve",
        translation_key="volume_releve",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        valeur=lambda e: e.volume,
    ),
    DescriptionCapteur(
        key="tranche",
        translation_key="tranche",
        valeur=lambda e: e.marginal.tranche,
        attributs=lambda e: {
            "volume_restant": None
            if e.marginal.volume_restant is None
            else float(round(e.marginal.volume_restant, 3))
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: TarifeauConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Crée les capteurs de l'entrée."""
    async_add_entities(
        [*(CapteurFacture(entry, description) for description in CAPTEURS), CapteurEcart(entry, ECART)]
    )


ECART = SensorEntityDescription(
    key="ecart_facture",
    translation_key="ecart_facture",
    device_class=SensorDeviceClass.MONETARY,
    suggested_display_precision=2,
)


class CapteurFacture(RestoreSensor):
    """Un capteur de la facture. Garde sa dernière valeur si l'index devient indisponible."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: DescriptionCapteur

    def __init__(self, entry: TarifeauConfigEntry, description: DescriptionCapteur) -> None:
        self.entity_description = description
        self._suivi: SuiviFacture = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        # Identifiant stable quelle que soit la langue de l'instance : le tableau de bord
        # prêt à coller (dashboard/) s'y réfère. Exemple : sensor.facture_d_eau_prix_marginal.
        self.entity_id = f"sensor.{slugify(entry.title)}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="tarifeau",
            model=self._suivi.tarif.nom if self._suivi.tarif else "Prix moyen (entité)",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Restaure la dernière valeur, puis suit les recalculs."""
        await super().async_added_to_hass()
        devise = self.hass.config.currency
        if self.entity_description.unite_devise:
            self._attr_native_unit_of_measurement = devise
        elif self.entity_description.unite_prix:
            self._attr_native_unit_of_measurement = f"{devise}/{UnitOfVolume.CUBIC_METERS}"
        if self._suivi.etat is None and (precedent := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = precedent.native_value
        self._mettre_a_jour()
        self.async_on_remove(self._suivi.ecouter(self._sur_calcul))

    @callback
    def _sur_calcul(self) -> None:
        self._mettre_a_jour()
        self.async_write_ha_state()

    @callback
    def _mettre_a_jour(self) -> None:
        etat = self._suivi.etat
        if etat is None:
            return
        self._attr_native_value = self.entity_description.valeur(etat)
        if self.entity_description.attributs is not None:
            self._attr_extra_state_attributes = self.entity_description.attributs(etat)


class CapteurEcart(CapteurFacture):
    """Écart entre la dernière facture saisie et le calcul (action ``tarifeau.saisir_facture``)."""

    def __init__(self, entry: TarifeauConfigEntry, description: SensorEntityDescription) -> None:
        super().__init__(entry, description)  # type: ignore[arg-type]

    async def async_added_to_hass(self) -> None:
        """Lit l'historique, puis suit les nouvelles saisies."""
        self._attr_native_unit_of_measurement = self.hass.config.currency
        self._mettre_a_jour()
        self.async_on_remove(self._suivi.ecouter(self._sur_calcul))

    @callback
    def _mettre_a_jour(self) -> None:
        if not self._suivi.factures:
            return
        derniere = self._suivi.factures[-1]
        self._attr_native_value = None if derniere["ecart"] is None else Decimal(str(derniere["ecart"]))
        self._attr_extra_state_attributes = {
            **{k: v for k, v in derniere.items() if k != "ecart"},
            "seuil_pct": SEUIL_ECART,
            "nombre_factures": len(self._suivi.factures),
            "historique": [
                {k: f[k] for k in ("debut", "fin", "volume", "montant_ttc", "ecart_pct")}
                for f in self._suivi.factures[-12:]
            ],
        }
