"""Fixtures communes : active le chargement des intégrations de custom_components/."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Toutes les fonctions de test voient custom_components/tarifeau."""
    return
