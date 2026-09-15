"""Conexión síncrona para el CLI del pipeline."""

import psycopg

from backend.config import database_url


def conectar() -> psycopg.Connection:
    """Conexión en autocommit: cada `with conn.transaction()` es un BEGIN
    real. Sin autocommit, psycopg abre una transacción implícita con la
    primera consulta y los `transaction()` posteriores serían solo
    savepoints dentro de ella (y un SET LOCAL duraría más de lo previsto)."""
    return psycopg.connect(database_url(), autocommit=True)
