"""Fixture compartida para los tests que necesitan Postgres.

Usan una base desechable en TEST_DATABASE_URL (nunca la de producción:
los tests insertan y borran filas). Sin esa variable se omiten.
Instrucciones para levantarla en el README.
"""

import os

import pytest

from backend.db.migrar import aplicar_migraciones


@pytest.fixture
def base_de_prueba(monkeypatch: pytest.MonkeyPatch) -> None:
    """Apunta DATABASE_URL a la base de prueba y deja el esquema al día."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL no definida")
    monkeypatch.setenv("DATABASE_URL", url)
    aplicar_migraciones()
