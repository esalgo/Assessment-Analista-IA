"""Pool de conexiones de la API y la sesión con aislamiento por empresa."""

from collections.abc import Iterator

import psycopg
from fastapi import Depends
from psycopg_pool import ConnectionPool

from backend.api.auth import Usuario, usuario_actual
from backend.config import database_url

_pool: ConnectionPool | None = None


def abrir_pool() -> None:
    """autocommit=True no es opcional. Sin autocommit, la primera consulta abre
    una transacción implícita y los `transaction()` siguientes son savepoints:
    SET LOCAL ROLE y set_config(..., true) sobrevivirían al request y el
    siguiente que reutilice la conexión vería datos de otra empresa."""
    global _pool
    _pool = ConnectionPool(database_url(), kwargs={"autocommit": True}, min_size=1, max_size=10, open=True)


def cerrar_pool() -> None:
    if _pool is not None:
        _pool.close()


def pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("la pool no está abierta")
    return _pool


def sesion_tenant(usuario: Usuario = Depends(usuario_actual)) -> Iterator[psycopg.Connection]:
    """Conexión para un request autenticado: todo corre como app_tenant y con
    app.empresa_id del token, dentro de una transacción. Las políticas RLS
    filtran en el motor; al cerrar la transacción el rol y la variable se
    deshacen y la conexión vuelve limpia a la pool."""
    with pool().connection() as conn, conn.transaction():
        conn.execute("SELECT set_config('app.empresa_id', %s, true)", (usuario.empresa_id,))
        conn.execute("SET LOCAL ROLE app_tenant")
        yield conn
