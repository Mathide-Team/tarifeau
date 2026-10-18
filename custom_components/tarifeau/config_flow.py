"""Configuration depuis l'interface (issue #4).

Étapes : capteur d'index → source du tarif → préréglage ou prix fixe → dernière relève.
Les options permettent ensuite de changer de tarif ou de saisir une nouvelle relève.
Une entrée par capteur d'index : par exemple une par voisin du compteur wM-Bus.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CHAMPS_SOURCE,
    CONF_ASSAINISSEMENT,
    CONF_DATE_RELEVE,
    CONF_DIAMETRE,
    CONF_ENTITE_PRIX,
    CONF_FACTURATION,
    CONF_FIN_PERIODE,
    CONF_INDEX,
    CONF_INDEX_RELEVE,
    CONF_MONTANT_FACTURE,
    CONF_NOM,
    CONF_PREREGLAGE,
    CONF_PRIX_FIXE,
    CONF_SOURCE,
    CONF_VOLUME_FACTURE,
    DOMAIN,
    FACTURATIONS,
    NOM_PAR_DEFAUT,
    SOURCE_ENTITE_PRIX,
    SOURCE_PREREGLAGE,
    SOURCE_PRIX_FIXE,
    SOURCE_TAUX_FACTURE,
    SOURCES,
    STATE_CLASSES_INDEX,
    UNITES_INDEX,
)
from .modele import (
    PREFIXE_PERSO,
    Tarif,
    TarifInvalide,
    charger_tarif,
    diametres,
    prereglages,
    verifier_tarifs_perso,
)
from .suivi import dossier_perso, prix_entite, unite_prix_valide


def index_actuel_m3(hass: HomeAssistant, entity_id: str) -> float | None:
    """Index actuel du capteur, converti en m³. ``None`` si indisponible ou non numérique."""
    etat = hass.states.get(entity_id)
    if etat is None:
        return None
    diviseur = UNITES_INDEX.get(etat.attributes.get(ATTR_UNIT_OF_MEASUREMENT, ""))
    try:
        return float(etat.state) / diviseur if diviseur else None
    except ValueError:
        return None


def _verifier_capteur(hass: HomeAssistant, entity_id: str) -> str | None:
    """Code d'erreur si le capteur ne convient pas comme index, sinon ``None``."""
    etat = hass.states.get(entity_id)
    if etat is None:
        return "capteur_absent"
    if etat.attributes.get(ATTR_UNIT_OF_MEASUREMENT) not in UNITES_INDEX:
        return "unite"
    if etat.attributes.get("state_class") not in STATE_CLASSES_INDEX:
        return "state_class"
    return None


async def _noms_prereglages(hass: HomeAssistant) -> list[selector.SelectOptionDict]:
    """Préréglages fournis, puis tarifs personnels de ``<config>/tarifeau/`` (même invalides, signalés)."""

    def lire() -> list[selector.SelectOptionDict]:
        options = [selector.SelectOptionDict(value=i, label=charger_tarif(i).nom) for i in prereglages()]
        for ident, tarif, _erreur in verifier_tarifs_perso(dossier_perso(hass)):
            fichier = ident.removeprefix(PREFIXE_PERSO)
            libelle = f"Mon tarif : {tarif.nom} ({fichier})" if tarif else f"Mon tarif : {fichier} (invalide)"
            options.append(selector.SelectOptionDict(value=ident, label=libelle))
        return options

    return await hass.async_add_executor_job(lire)


def _rapport_tarifs_perso(hass: HomeAssistant) -> str:
    """Texte Markdown : état de chaque fichier de ``<config>/tarifeau/`` (hors boucle d'événements)."""
    dossier = dossier_perso(hass)
    resultats = verifier_tarifs_perso(dossier)
    if not resultats:
        return f"Aucun fichier `.yaml` dans `{dossier}`."
    lignes = []
    for ident, tarif, erreur in resultats:
        fichier = ident.removeprefix(PREFIXE_PERSO)
        if tarif:
            debut = tarif.periodes[0].debut.strftime("%d/%m/%Y")
            lignes.append(
                f"- **{fichier}** : valide, « {tarif.nom} », "
                f"{len(tarif.periodes)} période(s) depuis le {debut}"
            )
        else:
            lignes.append(f"- **{fichier}** : invalide. {erreur}")
    return "\n".join(lignes)


def _schema_source(defaut: str = SOURCE_PREREGLAGE) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_SOURCE, default=defaut): selector.SelectSelector(
                selector.SelectSelectorConfig(options=list(SOURCES), translation_key=CONF_SOURCE)
            )
        }
    )


def _schema_prereglage(options: list[selector.SelectOptionDict], actuel: dict[str, Any]) -> vol.Schema:
    defaut = actuel.get(CONF_PREREGLAGE, options[0]["value"])
    return vol.Schema(
        {
            vol.Required(CONF_PREREGLAGE, default=defaut): selector.SelectSelector(
                selector.SelectSelectorConfig(options=options)
            ),
            vol.Required(CONF_ASSAINISSEMENT, default=actuel.get(CONF_ASSAINISSEMENT, True)): bool,
        }
    )


def _schema_prix_fixe(actuel: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_PRIX_FIXE, default=actuel.get(CONF_PRIX_FIXE, 4.0)): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=50,
                    step="any",
                    unit_of_measurement="€/m³",
                    mode=selector.NumberSelectorMode.BOX,
                )
            )
        }
    )


def _schema_entite_prix() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ENTITE_PRIX): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            )
        }
    )


def _schema_taux_facture(actuel: dict[str, Any]) -> vol.Schema:
    def nombre(unite: str) -> selector.NumberSelector:
        return selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, step="any", unit_of_measurement=unite, mode=selector.NumberSelectorMode.BOX
            )
        )

    return vol.Schema(
        {
            vol.Required(CONF_MONTANT_FACTURE, default=actuel.get(CONF_MONTANT_FACTURE, 0)): nombre("€"),
            vol.Required(CONF_VOLUME_FACTURE, default=actuel.get(CONF_VOLUME_FACTURE, 0)): nombre("m³"),
        }
    )


def _verifier_entite_prix(hass: HomeAssistant, entity_id: str) -> str | None:
    """Code d'erreur si l'entité ne donne pas un prix au m³ exploitable, sinon ``None``."""
    etat = hass.states.get(entity_id)
    if etat is None:
        return "capteur_absent"
    if not unite_prix_valide(etat.attributes.get(ATTR_UNIT_OF_MEASUREMENT)):
        return "unite_prix"
    if prix_entite(etat) is None:
        return "prix_indisponible"
    return None


def _schema_releve(actuel: dict[str, Any], index_m3: float | None) -> vol.Schema:
    index_defaut = actuel.get(CONF_INDEX_RELEVE, round(index_m3, 3) if index_m3 is not None else 0)
    return vol.Schema(
        {
            vol.Required(CONF_FACTURATION, default=actuel.get(CONF_FACTURATION, "semestrielle")): (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(FACTURATIONS), translation_key=CONF_FACTURATION
                    )
                )
            ),
            vol.Required(CONF_DATE_RELEVE, default=actuel.get(CONF_DATE_RELEVE, date.today().isoformat())): (
                selector.DateSelector()
            ),
            vol.Optional(CONF_FIN_PERIODE, description={"suggested_value": actuel.get(CONF_FIN_PERIODE)}): (
                selector.DateSelector()
            ),
            vol.Required(CONF_INDEX_RELEVE, default=index_defaut): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, step="any", unit_of_measurement="m³", mode=selector.NumberSelectorMode.BOX
                )
            ),
        }
    )


def _verifier_releve(hass: HomeAssistant, entity_id: str, saisie: dict[str, Any]) -> dict[str, str]:
    erreurs: dict[str, str] = {}
    if date.fromisoformat(saisie[CONF_DATE_RELEVE]) > date.today():
        erreurs[CONF_DATE_RELEVE] = "date_future"
    if (fin := saisie.get(CONF_FIN_PERIODE)) and fin <= saisie[CONF_DATE_RELEVE]:
        erreurs[CONF_FIN_PERIODE] = "fin_avant_debut"
    index_m3 = index_actuel_m3(hass, entity_id)
    if index_m3 is not None and saisie[CONF_INDEX_RELEVE] > index_m3 + 1e-6:
        erreurs[CONF_INDEX_RELEVE] = "index_incoherent"
    return erreurs


class _EtapesTarif:
    """Étapes communes à la configuration et aux options : tarif, puis relève."""

    hass: HomeAssistant
    _donnees: dict[str, Any]
    _diametres: list[int]
    _prereglage: dict[str, Any]

    def _actuel(self) -> dict[str, Any]:
        return self._donnees

    def _index_entity(self) -> str:
        return self._donnees[CONF_INDEX]

    async def async_step_tarif(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Source du tarif."""
        if user_input is not None:
            self._donnees[CONF_SOURCE] = user_input[CONF_SOURCE]
            if user_input[CONF_SOURCE] == SOURCE_PREREGLAGE:
                return await self.async_step_prereglage()
            if user_input[CONF_SOURCE] == SOURCE_PRIX_FIXE:
                return await self.async_step_prix_fixe()
            if user_input[CONF_SOURCE] == SOURCE_TAUX_FACTURE:
                return await self.async_step_taux_facture()
            return await self.async_step_entite_prix()
        return self.async_show_form(
            step_id="tarif", data_schema=_schema_source(self._actuel().get(CONF_SOURCE, SOURCE_PREREGLAGE))
        )

    async def async_step_prereglage(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choix d'un tarif de collectivité."""
        erreurs: dict[str, str] = {}
        details = {"erreur": ""}
        if user_input is not None:
            try:
                tarif = await self.hass.async_add_executor_job(
                    charger_tarif, user_input[CONF_PREREGLAGE], dossier_perso(self.hass)
                )
            except TarifInvalide as err:
                erreurs["base"], details["erreur"] = "tarif_invalide", str(err)
            else:
                return await self._apres_prereglage(user_input, tarif)
        options = await _noms_prereglages(self.hass)
        return self.async_show_form(
            step_id="prereglage",
            data_schema=_schema_prereglage(options, user_input or self._actuel()),
            errors=erreurs,
            description_placeholders={**details, "dossier": str(dossier_perso(self.hass))},
        )

    async def _apres_prereglage(self, user_input: dict[str, Any], tarif: Tarif) -> ConfigFlowResult:
        """Diamètre si l'abonnement en dépend, sinon le tarif est gardé."""
        self._diametres = diametres(tarif)
        if self._diametres:
            self._prereglage = user_input
            return await self.async_step_diametre()
        self._donnees.pop(CONF_DIAMETRE, None)  # préréglage précédent avec diamètre
        return await self._garder(SOURCE_PREREGLAGE, user_input)

    async def async_step_diametre(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Diamètre du compteur, quand l'abonnement du préréglage en dépend."""
        if user_input is not None:
            return await self._garder(
                SOURCE_PREREGLAGE, {**self._prereglage, CONF_DIAMETRE: int(user_input[CONF_DIAMETRE])}
            )
        actuel = self._actuel().get(CONF_DIAMETRE)
        defaut = actuel if actuel in self._diametres else self._diametres[0]
        schema = vol.Schema(
            {
                vol.Required(CONF_DIAMETRE, default=str(defaut)): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=str(dn), label=f"DN {dn}")
                            for dn in self._diametres
                        ]
                    )
                )
            }
        )
        return self.async_show_form(step_id="diametre", data_schema=schema)

    async def async_step_prix_fixe(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Prix TTC au m³, abonnement compris."""
        if user_input is not None:
            return await self._garder(SOURCE_PRIX_FIXE, user_input)
        return self.async_show_form(step_id="prix_fixe", data_schema=_schema_prix_fixe(self._actuel()))

    async def async_step_entite_prix(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Capteur de prix moyen au m³ (HydroTarif : prix total eau + assainissement)."""
        erreurs: dict[str, str] = {}
        if user_input is not None:
            erreur = _verifier_entite_prix(self.hass, user_input[CONF_ENTITE_PRIX])
            if erreur:
                erreurs[CONF_ENTITE_PRIX] = erreur
            else:
                return await self._garder(SOURCE_ENTITE_PRIX, user_input)
        actuel = {**self._actuel(), **(user_input or {})}
        schema = self.add_suggested_values_to_schema(_schema_entite_prix(), actuel)
        return self.async_show_form(step_id="entite_prix", data_schema=schema, errors=erreurs)

    async def async_step_taux_facture(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Montant TTC et volume de la dernière facture : taux effectif = montant ÷ volume."""
        erreurs: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_VOLUME_FACTURE] <= 0:
                erreurs[CONF_VOLUME_FACTURE] = "volume_nul"
            else:
                return await self._garder(SOURCE_TAUX_FACTURE, user_input)
        actuel = {**self._actuel(), **(user_input or {})}
        return self.async_show_form(
            step_id="taux_facture", data_schema=_schema_taux_facture(actuel), errors=erreurs
        )

    async def _garder(self, source: str, saisie: dict[str, Any]) -> ConfigFlowResult:
        """Enregistre les champs de ``source`` et efface ceux des autres sources."""
        for autre, champs in CHAMPS_SOURCE.items():
            if autre != source:
                for champ in champs:
                    self._donnees.pop(champ, None)
        self._donnees.update(saisie)
        return await self._apres_tarif()

    async def async_step_releve(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Date et index de la dernière relève (repris de la facture)."""
        erreurs: dict[str, str] = {}
        if user_input is not None:
            erreurs = _verifier_releve(self.hass, self._index_entity(), user_input)
            if not erreurs:
                self._donnees.pop(CONF_FIN_PERIODE, None)  # champ vidé : retour à la durée
                self._donnees.update(user_input)
                return self._terminer()
        actuel = {**self._actuel(), **(user_input or {})}
        schema = _schema_releve(actuel, index_actuel_m3(self.hass, self._index_entity()))
        return self.async_show_form(step_id="releve", data_schema=schema, errors=erreurs)

    async def _apres_tarif(self) -> ConfigFlowResult:
        return await self.async_step_releve()

    def _terminer(self) -> ConfigFlowResult:
        raise NotImplementedError  # pragma: no cover


class TarifeauConfigFlow(_EtapesTarif, ConfigFlow, domain=DOMAIN):
    """Assistant « Ajouter une intégration »."""

    VERSION = 1

    def __init__(self) -> None:
        self._donnees: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Nom de la facture et capteur d'index."""
        erreurs: dict[str, str] = {}
        if user_input is not None:
            erreur = _verifier_capteur(self.hass, user_input[CONF_INDEX])
            if erreur:
                erreurs[CONF_INDEX] = erreur
            else:
                await self.async_set_unique_id(user_input[CONF_INDEX])
                self._abort_if_unique_id_configured()
                nom = user_input[CONF_NOM].strip() or NOM_PAR_DEFAUT
                self._donnees = {CONF_NOM: nom, CONF_INDEX: user_input[CONF_INDEX]}
                return await self.async_step_tarif()

        schema = vol.Schema(
            {
                vol.Required(CONF_NOM, default=NOM_PAR_DEFAUT): str,
                vol.Required(CONF_INDEX): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
            }
        )
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(step_id="user", data_schema=schema, errors=erreurs)

    def _terminer(self) -> ConfigFlowResult:
        return self.async_create_entry(title=self._donnees[CONF_NOM], data=self._donnees)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> TarifeauOptionsFlow:
        """Options : changer de tarif, nouvelle relève."""
        return TarifeauOptionsFlow()


class TarifeauOptionsFlow(_EtapesTarif, OptionsFlowWithReload):
    """Options modifiables après coup. L'entrée est rechargée à l'enregistrement."""

    def __init__(self) -> None:
        self._donnees: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Menu : changer de tarif, ou saisir une nouvelle relève."""
        self._donnees = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_menu(step_id="init", menu_options=["tarif", "releve", "verifier"])

    async def async_step_verifier(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Vérifie les fichiers de tarif personnels, sans rien modifier (issue #17)."""
        if user_input is not None:
            return await self.async_step_init()
        rapport = await self.hass.async_add_executor_job(_rapport_tarifs_perso, self.hass)
        return self.async_show_form(
            step_id="verifier",
            data_schema=vol.Schema({}),
            description_placeholders={"dossier": str(dossier_perso(self.hass)), "rapport": rapport},
        )

    def _terminer(self) -> ConfigFlowResult:
        options = {k: v for k, v in self._donnees.items() if k not in (CONF_NOM, CONF_INDEX)}
        return self.async_create_entry(data=options)

    async def _apres_tarif(self) -> ConfigFlowResult:
        return self._terminer()  # changer de tarif ne demande pas de nouvelle relève
