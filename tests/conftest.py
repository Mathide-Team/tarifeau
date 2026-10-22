"""Fixtures communes : active le chargement des intégrations de custom_components/."""

from collections.abc import Iterator

import pytest
from loguru import logger


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Toutes les fonctions de test voient custom_components/tarifeau."""
    return


@pytest.fixture
def journal_loguru() -> Iterator[list[str]]:
    """Messages loguru (niveau INFO et plus) émis par les scripts pendant le test.

    Le puits stderr par défaut de loguru est lié au flux de l'import et
    échappe à ``capsys`` : on écoute donc loguru directement.
    """
    messages: list[str] = []
    ident = logger.add(lambda m: messages.append(m.record["message"]), level="INFO", format="{message}")
    yield messages
    logger.remove(ident)
