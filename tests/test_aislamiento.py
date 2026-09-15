"""Test obligatorio de aislamiento multi-tenant con RLS.

El usuario de la imagen de Postgres es superusuario, igual que en
producción: así el test prueba el caso real, donde solo SET LOCAL ROLE
hace que RLS aplique.
"""

from collections.abc import Iterator

import psycopg
import pytest

from backend.db.conexion import conectar

EMPRESAS = ("EMP-T1", "EMP-T2")


def _borrar_datos_de_prueba(conn: psycopg.Connection) -> None:
    conn.execute("DELETE FROM leads WHERE empresa_id = ANY(%s)", (list(EMPRESAS),))
    conn.execute("DELETE FROM puntos_venta WHERE empresa_id = ANY(%s)", (list(EMPRESAS),))
    conn.execute("DELETE FROM empresas WHERE empresa_id = ANY(%s)", (list(EMPRESAS),))


@pytest.fixture
def conn(base_de_prueba: None) -> Iterator[psycopg.Connection]:
    with conectar() as conexion:
        _borrar_datos_de_prueba(conexion)
        conexion.execute("INSERT INTO empresas VALUES ('EMP-T1'), ('EMP-T2')")
        conexion.execute("INSERT INTO puntos_venta VALUES ('PV-T1', 'EMP-T1'), ('PV-T2', 'EMP-T2')")
        conexion.execute(
            """
            INSERT INTO leads (lead_id, empresa_id, punto_venta_id, fecha_registro,
                               canal, nombre_cliente, telefono_valido, estado_gestion)
            VALUES ('LD-T1', 'EMP-T1', 'PV-T1', now(), 'WhatsApp', 'Uno',  true, 'sin_gestion'),
                   ('LD-T2', 'EMP-T1', 'PV-T1', now(), 'Meta Ads', 'Dos',  true, 'sin_gestion'),
                   ('LD-T3', 'EMP-T2', 'PV-T2', now(), 'WhatsApp', 'Tres', true, 'sin_gestion')
            """
        )
        yield conexion
        _borrar_datos_de_prueba(conexion)


def _entrar_como_tenant(conn: psycopg.Connection, empresa_id: str | None) -> None:
    """Lo mismo que hará la dependencia de la API al inicio de cada request."""
    if empresa_id is not None:
        conn.execute("SELECT set_config('app.empresa_id', %s, true)", (empresa_id,))
    conn.execute("SET LOCAL ROLE app_tenant")


def _contar_leads_de_prueba(conn: psycopg.Connection) -> int:
    fila = conn.execute("SELECT count(*) FROM leads WHERE lead_id LIKE 'LD-T%'").fetchone()
    assert fila is not None
    return fila[0]


def test_cada_empresa_ve_solo_sus_leads(conn: psycopg.Connection) -> None:
    with conn.transaction():
        _entrar_como_tenant(conn, "EMP-T1")
        assert _contar_leads_de_prueba(conn) == 2

    with conn.transaction():
        _entrar_como_tenant(conn, "EMP-T2")
        assert _contar_leads_de_prueba(conn) == 1


def test_sin_empresa_fijada_no_ve_nada(conn: psycopg.Connection) -> None:
    with conn.transaction():
        _entrar_como_tenant(conn, None)
        assert _contar_leads_de_prueba(conn) == 0


def test_superusuario_sin_cambiar_de_rol_se_salta_rls(conn: psycopg.Connection) -> None:
    """Documenta por qué existe app_tenant: con el usuario de la imagen,
    FORCE ROW LEVEL SECURITY no filtra nada."""
    assert _contar_leads_de_prueba(conn) == 3


def test_no_puede_escribir_en_otra_empresa(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with conn.transaction():
            _entrar_como_tenant(conn, "EMP-T1")
            conn.execute(
                """
                INSERT INTO leads (lead_id, empresa_id, punto_venta_id, fecha_registro,
                                   canal, nombre_cliente, telefono_valido, estado_gestion)
                VALUES ('LD-T9', 'EMP-T2', 'PV-T2', now(), 'WhatsApp', 'Intruso', true, 'sin_gestion')
                """
            )

    with conn.transaction():
        _entrar_como_tenant(conn, "EMP-T1")
        cursor = conn.execute("UPDATE leads SET nombre_cliente = 'x' WHERE lead_id = 'LD-T3'")
        assert cursor.rowcount == 0


def test_contexto_del_tenant_no_sobrevive_a_la_transaccion(conn: psycopg.Connection) -> None:
    """Protege contra la trampa de la transacción implícita: si la conexión
    no estuviera en autocommit, el rol y la empresa seguirían activos aquí."""
    with conn.transaction():
        _entrar_como_tenant(conn, "EMP-T1")

    fila = conn.execute(
        "SELECT current_user, current_setting('app.empresa_id', true)"
    ).fetchone()
    assert fila is not None
    usuario, empresa = fila
    assert usuario != "app_tenant"
    assert not empresa
