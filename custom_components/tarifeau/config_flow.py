"""Configuration depuis l'interface (squelette, issue #1).

Une seule étape : le nom de l'entrée. Le capteur d'index, la source du tarif
et la période de facturation viendront avec l'issue #4.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_NOM, DOMAIN, NOM_PAR_DEFAUT


class TarifeauConfigFlow(ConfigFlow, domain=DOMAIN):
    """Assistant « Ajouter une intégration »."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Étape unique : nom de la facture."""
        if user_input is not None:
            nom = user_input[CONF_NOM].strip() or NOM_PAR_DEFAUT
            await self.async_set_unique_id(nom.casefold())
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=nom, data={CONF_NOM: nom})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_NOM, default=NOM_PAR_DEFAUT): str}),
        )
